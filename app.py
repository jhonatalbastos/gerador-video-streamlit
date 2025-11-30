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
    st.warning("Instale edge-tts: `pip install edge-tts` para usar TTS premium")

TITLE = "Studio Jhonata - Automação Litúrgica"
CONFIG_FILE = "overlayconfig.json"
SAVED_MUSIC_FILE = "savedbgmusic.mp3"

# Force ffmpeg path for imageio if needed (Streamlit Cloud)
os.environ.setdefault("IMAGEIO_FFMPEG_EXE", "/usr/bin/ffmpeg")

st.set_page_config(
    page_title="Studio Jhonata",
    layout="wide",
    initial_sidebar_state="expanded"
)

def load_config():
    """Carrega configurações do disco ou retorna padrão"""
    default_settings = {
        "line1_y": 40, "line1_size": 40, "line1_font": "Padrão Sans", "line1_anim": "Estático",
        "line2_y": 90, "line2_size": 28, "line2_font": "Padrão Sans", "line2_anim": "Estático",
        "line3_y": 130, "line3_size": 24, "line3_font": "Padrão Sans", "line3_anim": "Estático",
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
            st.warning(f"Erro ao carregar configurações salvas: {e}")
    return default_settings

def save_config(settings):
    """Salva configurações no disco"""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(settings, f)
        return True
    except Exception as e:
        st.error(f"Erro ao salvar configurações: {e}")
        return False

def save_music_file(file_bytes):
    """Salva a música padrão no disco"""
    try:
        with open(SAVED_MUSIC_FILE, 'wb') as f:
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

# Groq client
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
    return {'evangelista': evangelista_encontrado, 'capitulo': capitulo, 'versiculos': versiculos}

def formatar_referencia_curta(ref_biblica):
    if not ref_biblica:
        return ""
    return f"{ref_biblica['evangelista']}, Cap. {ref_biblica['capitulo']}, {ref_biblica['versiculos']}"

def analisar_personagens_groq(texto_evangelho: str, banco_personagens: dict):
    client = inicializar_groq()
    system_prompt = f"""Voce e especialista em analise biblica. Analise o texto e identifique TODOS os personagens biblicos mencionados.
Formato EXATO da resposta:
PERSONAGENS: nome1 nome2 nome3
NOVOS: NomeNovo=descricao detalhada aparencia fisica/roupas/idade/estilo (apenas se nao existir no banco: {', '.join(banco_personagens.keys())})
Exemplo:
PERSONAGENS: Jesus Pedro fariseus
NOVOS: Mulher Samaritana=mulher de 35 anos, pele morena, veu colorido, jarro dagua, expressao curiosa, tunica tradicional"""
    try:
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"TEXTO: {texto_evangelho[:1500]}"},
            ],
            temperature=0.3,
            max_tokens=400
        )
        resultado = resp.choices[0].message.content
        personagens_detectados = {}
        m = re.search(r'PERSONAGENS[:s]*(.*)', resultado)
        if m:
            nomes = [n.strip() for n in m.group(1).split() if n.strip()]
            for nome in nomes:
                if nome in banco_personagens:
                    personagens_detectados[nome] = banco_personagens[nome]
        m2 = re.search(r'NOVOS[:s]*(.*)', resultado)
        if m2:
            novos = m2.group(1).strip()
            blocos = re.split(r',(?=w+=)', novos)
            for bloco in blocos:
                if '=' in bloco:
                    nome, desc = bloco.split('=', 1)
                    nome = nome.strip()
                    desc = desc.strip()
                    if nome:
                        personagens_detectados[nome] = desc
                        banco_personagens[nome] = desc
        return personagens_detectados
    except Exception:
        return {}

def buscar_liturgia_api1(data_str: str):
    url = f"https://api-liturgia-diaria.vercel.app/?date={data_str}"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        dados = resp.json()
        today = dados.get('today', {})
        readings = today.get('readings', {})
        gospel = readings.get('gospel', {})
        if not gospel:
            return None
        referencia_liturgica = today.get('entry_title', '').strip() or "Evangelho do dia"
        titulo = (gospel.get('head_title') or gospel.get('title') or "Evangelho de Jesus Cristo").strip()
        texto = gospel.get('text', '').strip()
        if not texto:
            return None
        texto_limpo = limpar_texto_evangelho(texto)
        ref_biblica = extrair_referencia_biblica(titulo)
        return {
            'fonte': 'api-liturgia-diaria.vercel.app',
            'titulo': titulo,
            'referencia_liturgica': referencia_liturgica,
            'texto': texto_limpo,
            'ref_biblica': ref_biblica
        }
    except Exception:
        return None

def buscar_liturgia_api2(data_str: str):
    url = f"https://liturgia.up.railway.app/v2/{data_str}"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        dados = resp.json()
        lit = dados.get('liturgia', {})
        ev = lit.get('evangelho') or lit.get('evangelho_do_dia') or lit
        if not ev:
            return None
        texto = ev.get('texto') or ev.get('conteudo', '')
        if not texto:
            return None
        texto_limpo = limpar_texto_evangelho(texto)
        return {
            'fonte': 'liturgia.up.railway.app',
            'titulo': "Evangelho do dia",
            'referencia_liturgica': "Evangelho do dia",
            'texto': texto_limpo,
            'ref_biblica': None
        }
    except Exception:
        return None

def obter_evangelho_com_fallback(data_str: str):
    ev = buscar_liturgia_api1(data_str)
    if ev:
        st.info("Usando api-liturgia-diaria.vercel.app")
        return ev
    ev = buscar_liturgia_api2(data_str)
    if ev:
        st.info("Usando liturgia.up.railway.app")
        return ev
    st.error("Nao foi possivel obter o Evangelho")
    return None

def extrair_bloco(rotulo: str, texto: str) -> str:
    padrao = rf"{rotulo}.*?([A-Z]{{3,}})"
    m = re.search(padrao, texto, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else ""

def extrair_prompt(rotulo: str, texto: str) -> str:
    padrao = rf"{rotulo}.*?([A-Z]{{3,}})"
    m = re.search(padrao, texto, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else ""

def gerar_roteiro_com_prompts_groq(texto_evangelho: str, referencia_liturgica: str, personagens: dict, personagens_detectados: dict):
    client = inicializar_groq()
    texto_limpo = limpar_texto_evangelho(texto_evangelho)
    personagens_str = json.dumps(personagens, ensure_ascii=False)
    system_prompt = f"""Crie roteiro + 6 prompts visuais CATOLICOS para video devocional.
PERSONAGENS FIXOS: {personagens_str}
IMPORTANTE:
- 4 PARTES EXATAS: HOOK, REFLEXAO, APLICACAO, ORACAO
- PROMPT_LEITURA: separado (momento da leitura do Evangelho, mais calmo e reverente)
- PROMPT_GERAL: para thumbnail/capa
- USE SEMPRE as descricoes exatas dos personagens
- Estilo artistico renascentista catolico, luz suave, cores quentes

Formato EXATO:
HOOK: texto (5-8s)
PROMPT_HOOK: prompt visual com personagens fixos
REFLEXAO: texto (20-25s)
PROMPT_REFLEXAO: prompt visual com personagens fixos
APLICACAO: texto (20-25s)
PROMPT_APLICACAO: prompt visual com personagens fixos
ORACAO: texto (20-25s)
PROMPT_ORACAO: prompt visual com personagens fixos
PROMPT_LEITURA: prompt visual especifico para a leitura do Evangelho, mais calmo e reverente
PROMPT_GERAL: prompt para thumbnail/capa"""
    try:
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Evangelho: {referencia_liturgica}\
{texto_limpo[:2000]}"},