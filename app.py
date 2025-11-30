# app.py — Studio Jhonata (COMPLETO v19.1)
# Features: Música Persistente, Geração em Lote, Fix NameError, Transições, Overlay, Efeitos, EdgeTTS

import os
import re
import json
import time
import tempfile
import traceback
import subprocess
import urllib.parse
import random
import asyncio
from io import BytesIO
from datetime import date
from typing import List, Optional, Tuple, Dict
import base64
import requests
from PIL import Image, ImageDraw, ImageFont
import streamlit as st

# EdgeTTS imports
try:
    import edge_tts
except ImportError:
    edge_tts = None

# Force ffmpeg path for imageio if needed (Streamlit Cloud)
os.environ.setdefault("IMAGEIO_FFMPEG_EXE", "/usr/bin/ffmpeg")

# Arquivos de configuração persistentes
CONFIG_FILE = "overlay_config.json"
SAVED_MUSIC_FILE = "saved_bg_music.mp3"

# =========================
# Page config
# =========================
st.set_page_config(
    page_title="Studio Jhonata",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =========================
# Persistência de Configurações e Arquivos
# =========================
def load_config():
    """Carrega configurações do disco ou retorna padrão"""
    default_settings = {
        "line1_y": 40, "line1_size": 40, "line1_font": "Padrão (Sans)", "line1_anim": "Estático",
        "line2_y": 90, "line2_size": 28, "line2_font": "Padrão (Sans)", "line2_anim": "Estático",
        "line3_y": 130, "line3_size": 24, "line3_font": "Padrão (Sans)", "line3_anim": "Estático",
        "effect_type": "Zoom In (Ken Burns)", "effect_speed": 3,
        "trans_type": "Fade (Escurecer)", "trans_dur": 0.5,
        "music_vol": 0.15
    }

    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                saved = json.load(f)
                default_settings.update(saved)
        except Exception as e:
            st.warning(f"Erro ao carregar configurações salvas: {e}")
    
    return default_settings

def save_config(settings):
    """Salva configurações no disco"""
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(settings, f)
        return True
    except Exception as e:
        st.error(f"Erro ao salvar configurações: {e}")
        return False

def save_music_file(file_bytes):
    """Salva a música padrão no disco"""
    try:
        with open(SAVED_MUSIC_FILE, "wb") as f:
            f.write(file_bytes)
        return True
    except Exception as e:
        st.error(f"Erro ao salvar música: {e}")
        return False

def delete_music_file():
    """Remove a música padrão"""
    try:
        if os.path.exists(SAVED_MUSIC_FILE):
            os.remove(SAVED_MUSIC_FILE)
        return True
    except Exception as e:
        st.error(f"Erro ao deletar música: {e}")
        return False

# =========================
# Groq - lazy init
# =========================
_client = None

def inicializar_groq():
    global _client
    if _client is None:
        try:
            from groq import Groq # type: ignore
            if "GROQ_API_KEY" not in st.secrets and not os.getenv("GROQ_API_KEY"):
                st.error("❌ Configure GROQ_API_KEY em Settings → Secrets no Streamlit Cloud.")
                st.stop()
            api_key = st.secrets.get("GROQ_API_KEY") or os.getenv("GROQ_API_KEY")
            _client = Groq(api_key=api_key)
        except Exception as e:
            st.error(f"Erro ao inicializar Groq client: {e}")
            st.stop()
    return _client

# =========================
# Inicializar banco de personagens
# =========================
@st.cache_data
def inicializar_personagens():
    return {
        "Jesus": (
            "homem de 33 anos, pele morena clara, cabelo castanho ondulado na altura dos ombros, "
            "barba bem aparada, olhos castanhos penetrantes e serenos, túnica branca tradicional "
            "com detalhes vermelhos, manto azul, expressão de autoridade amorosa, estilo renascentista clássico"
        ),
        "São Pedro": (
            "homem robusto de 50 anos, pele bronzeada, cabelo curto grisalho, barba espessa, olhos "
            "determinados, túnica de pescador bege com remendos, mãos calejadas, postura forte, estilo realista bíblico"
        ),
        "São João": (
            "jovem de 25 anos, magro, cabelo castanho longo liso, barba rala, olhos expressivos, túnica "
            "branca limpa, expressão contemplativa, estilo renascentista"
        ),
    }

# =========================
# Limpeza do texto bíblico
# =========================
def limpar_texto_evangelho(texto: str) -> str:
    if not texto:
        return ""
    texto_limpo = texto.replace("
", " ").strip()
    texto_limpo = re.sub(r"\b(d{1,3})(?=[A-Za-zÁ-Úá-ú])", "", texto_limpo)
    texto_limpo = re.sub(r"s{2,}", " ", texto_limpo)
    return texto_limpo.strip()

# =========================
# Extrair referência bíblica (ROBUSTO)
# =========================
def extrair_referencia_biblica(titulo: str):
    if not titulo:
        return None
    
    titulo_lower = titulo.lower()
    mapa_nomes = {
        "mateus": "Mateus", "mt": "Mateus",
        "marcos": "Marcos", "mc": "Marcos",
        "lucas": "Lucas", "lc": "Lucas