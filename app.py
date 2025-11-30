import os
import re
import json
import time
import tempfile
import traceback
import subprocess
import urllib.parse
import random
from io import BytesIO
from datetime import date
from typing import List, Optional, Tuple, Dict
import base64
import requests
from PIL import Image, ImageDraw, ImageFont
import streamlit as st
import asyncio

# Edge-TTS integration
try:
    import edge_tts
    EDGETTS_AVAILABLE = True
except ImportError:
    EDGETTS_AVAILABLE = False

TITLE = "Studio Jhonata - Automacao Liturgica"
CONFIG_FILE = "overlayconfig.json"
SAVED_MUSIC_FILE = "savedbgmusic.mp3"

os.environ.setdefault("IMAGEIO_FFMPEG_EXE", "/usr/bin/ffmpeg")

st.set_page_config(
    page_title="Studio Jhonata",
    layout="wide",
    initial_sidebar_state="expanded"
)

def load_config():
    default_settings = {
        "line1_y": 40, "line1_size": 40, "line1_font": "Padrao Sans", "line1_anim": "Estatico",
        "line2_y": 90, "line2_size": 28, "line2_font": "Padrao Sans", "line2_anim": "Estatico",
        "line3_y": 130, "line3_size": 24, "line3_font": "Padrao Sans", "line3_anim": "Estatico",
        "effect_type": "Zoom In Ken Burns", "effect_speed": 3,
        "trans_type": "Fade Escurecer", "trans_dur": 0.5, "music_vol": 0.15
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                saved = json.load(f)
                default_settings.update(saved)
                return default_settings
        except Exception as e:
            st.warning(f"Erro ao carregar configuracoes salvas: {e}")
    return default_settings

def save_config(settings):
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(settings, f)
        return True
    except Exception as e:
        st.error(f"Erro ao salvar configuracoes: {e}")
        return False

def save_music_file(file_bytes):
    try:
        with open(SAVED_MUSIC_FILE, 'wb') as f:
            f.write(file_bytes)
        return True
    except Exception as e:
        st.error(f"Erro ao salvar musica: {e}")
        return False

def delete_music_file():
    try:
        if os.path.exists(SAVED_MUSIC_FILE):
            os.remove(SAVED_MUSIC_FILE)
        return True
    except Exception as e:
        st.error(f"Erro ao deletar musica: {e}")
        return False

_groq_client = None

def inicializar_groq():
    global _groq_client
    if _groq_client is None:
        try:
            from groq import Groq
            if "GROQ_API_KEY" not in st.secrets and not os.getenv("GROQ_API_KEY"):
                st.error("Configure GROQ_API_KEY em Settings > Secrets no Streamlit Cloud.")
                st.stop()
            apikey = st.secrets.get("GROQ_API_KEY") or os.getenv("GROQ_API_KEY")
            _groq_client = Groq(api_key=apikey)
        except Exception as e:
            st.error(f"Erro ao inicializar Groq client: {e}")
            st.stop()
    return _groq_client

@st.cache_data
def inicializar_personagens():
    return {
        "Jesus": "homem de 33 anos, pele morena clara, cabelo castanho ondulado na altura dos ombros, barba bem aparada, olhos castanhos penetrantes e serenos, tunica branca tradicional com detalhes vermelhos, manto azul, expressao de autoridade amorosa, estilo renascentista classico",
        "Sao Pedro": "homem robusto de 50 anos, pele bronzeada, cabelo curto grisalho, barba espessa, olhos determinados, tunica de pescador bege com remendos, maos calejadas, postura forte, estilo realista biblico",
        "Sao Joao": "jovem de 25 anos, magro, cabelo castanho longo liso, barba rala, olhos expressivos, tunica branca limpa, expressao contemplativa, estilo renascentista"
    }

def limpar_texto_evangelho(texto: str) -> str:
    if not texto:
        return ""
    texto_limpo = texto.replace('
', ' ').strip()
    texto_limpo = re.sub(r'[1-3]?d?[A-Za-zÀ-Úà-ú]+', '', texto_limpo)
    texto_limpo = re.sub(r's+', ' ', texto_limpo)
    return texto_limpo.strip()

def extrair_referencia_biblica(titulo: str):
    if not titulo:
        return None
    titulo_lower = titulo.lower()
    mapa_nomes = {
        'mateus': 'Mateus', 'mt': 'Mateus',
        'marcos': 'Marcos', 'mc': 'Marcos',
        'lucas': 'Lucas', 'lc': 'Lucas',
        'joao': 'João', 'jo': 'João'
    }
    evangelista_encontrado = None
    for chave, valor in mapa_nomes.items():
        if re.search(rf'{chave}', titulo_lower):
            evangelista_encontrado = valor
            break
    if not evangelista_encontrado:
        m_fallback = re.search(r'(?:São|S.|Sao|San|St.?s?)([A-Za-zÀ-Úà-ú]+)', titulo, re.IGNORECASE)
        if m_fallback:
            nome_cand = m_fallback.group(1).strip()
            if len(nome_cand) > 2:
                evangelista_encontrado = nome_cand
            else:
                return None
    m_nums = re.search(r'(d{1,3})[,:]?[-—]?d*', titulo)
    if m_nums:
        capitulo = m_nums.group(1)
        versiculos_raw = m_nums.group(2) if len(m_nums.groups()) > 1 else ""
        versiculos = versiculos_raw.replace('-', ' a ').replace(',', ' a ')
    else:
        return None
    return {'evangelista': evangelista_encontrado, 'capitulo': capitulo, 'versiculos