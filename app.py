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

st.set_page_config(page_title="Studio Jhonata", layout="wide", initial_sidebar_state="expanded")

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
    texto_limpo = re.sub(r'[1-3]?d?[A-Za-z]+', '', texto_limpo)
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
        'joao': 'Joao', 'jo': 'Joao'
    }
    evangelista_encontrado = None
    for chave, valor in mapa_nomes.items():
        if re.search(rf'{chave}', titulo_lower):
            evangelista_encontrado = valor
            break
    if not evangelista_encontrado:
        m_fallback = re.search(r'(?:Sao|S.|San|St.?s?)([A-Za-z]+)', titulo, re.IGNORECASE)
        if m_fallback:
            nome_cand = m_fallback.group(1).strip()
            if len(nome_cand) > 2:
                evangelista_encontrado = nome_cand
    m_nums = re.search(r'(d{1,3})[,:]?[-—]?d*', titulo)
    if m_nums:
        capitulo = m_nums.group(1)
        versiculos_raw = m_nums.group(2) if len(m_nums.groups()) > 1 else ""
        versiculos = versiculos_raw.replace('-', ' a ').replace(',', ' a ')
        return {'evangelista': evangelista_encontrado, 'capitulo': capitulo, 'versiculos': versiculos}
    return None

def formatar_referencia_curta(ref_biblica):
    if not ref_biblica:
        return ""
    return f"{ref_biblica['evangelista']}, Cap. {ref_biblica['capitulo']}, {ref_biblica['versiculos']}"

def analisar_personagens_groq(texto_evangelho: str, banco_personagens: dict):
    client = inicializar_groq()
    system_prompt = f"Voce e especialista em analise biblica. Analise o texto e identifique TODOS os personagens biblicos mencionados. Formato EXATO: PERSONAGENS: nome1 nome2 nome3 NOVOS: NomeNovo=descricao (apenas se nao existir no banco: {', '.join(banco_personagens.keys())})"
    try:
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": f"TEXTO: {texto_evangelho[:1500]}"},],
            temperature=0.3, max_tokens=400
        )
        resultado = resp.choices[0].message.content
        personagens_detectados = {}
        m = re.search(r'PERSONAGENS[:s]*(.*)', resultado)
        if m:
            nomes = [n.strip() for n in m.group(1).split() if n.strip()]
            for nome in nomes:
                if nome in banco_personagens:
                    personagens_detectados[nome] = banco_personagens[nome]
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
        titulo = gospel.get('head_title') or gospel.get('title') or "Evangelho de Jesus Cristo"
        texto = gospel.get('text', '').strip()
        if not texto:
            return None
        texto_limpo = limpar_texto_evangelho(texto)
        ref_biblica = extrair_referencia_biblica(titulo)
        return {
            'titulo': titulo.strip(),
            'referencia_liturgica': today.get('entry_title', 'Evangelho do dia').strip(),
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
        texto = ev.get('texto') or ev.get('conteudo', '')
        if not texto:
            return None
        texto_limpo = limpar_texto_evangelho(texto)
        return {
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

def gerar_roteiro_com_prompts_groq(texto_evangelho: str, referencia_liturgica: str, personagens: dict, personagens_detectados: dict):
    client = inicializar_groq()
    texto_limpo = limpar_texto_evangelho(texto_evangelho)
    system_prompt = """Crie roteiro CATOLICO para video devocional. 4 PARTES: HOOK, REFLEXAO, APLICACAO, ORACAO. USE personagense estil renascentista catolico. Formato: HOOK: texto PROMPT_HOOK: prompt REFLEXAO: texto PROMPT_REFLEXAO: prompt etc"""
    try:
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": f"{referencia_liturgica}
{texto_limpo[:2000]}"},],
            temperature=0.7, max_tokens=1200
        )
        texto_gerado = resp.choices[0].message.content
        partes = {}
        partes['hook'] = extrair_bloco("HOOK", texto_gerado)
        partes['reflexao'] = extrair_bloco("REFLEXAO", texto_gerado)
        partes['aplicacao'] = extrair_bloco("APLICACAO", texto_gerado)
        partes['oracao'] = extrair_bloco("ORACAO", texto_gerado)
        partes['prompt_hook'] = extrair_bloco("PROMPT_HOOK", texto_gerado)
        partes['prompt_reflexao'] = extrair_bloco("PROMPT_REFLEXAO", texto_gerado)
        partes['prompt_aplicacao'] = extrair_bloco("PROMPT_APLICACAO", texto_gerado)
        partes['prompt_oracao'] = extrair_bloco("PROMPT_ORACAO", texto_gerado)
        partes['prompt_leitura'] = "Cena calma de leitura do Evangelho, livro aberto, luz suave"
        partes['prompt_geral'] = "Thumbnail evangelho renascentista catolico"
        return partes
    except Exception as e:
        st.error(f"Erro Groq: {e}")
        return None

def montar_leitura_com_formulas(texto_evangelho: str, ref_biblica):
    if ref_biblica:
        abertura = f"Proclamacao do Evangelho de Jesus Cristo, segundo Sao {ref_biblica['evangelista']}. Capitulo {ref_biblica['capitulo']}, versiculos {ref_biblica['versiculos']}. Gloria a vos, Senhor!"
    else:
        abertura = "Proclamacao do Evangelho de Jesus Cristo, segundo Sao Lucas. Gloria a vos, Senhor!"
    fechamento = "Palavra da Salvacao. Gloria a vos, Senhor!"
    return f"{abertura}

{texto_evangelho}

{fechamento}"

async def gerar_audio_edgetts(texto: str) -> Optional[BytesIO]:
    if not EDGETTS_AVAILABLE:
        return None
    mp3_fp = BytesIO()
    try:
        communicate = edge_tts.Communicate(texto, "pt-BR-AnaNeural")
        await communicate.save(mp3_fp)
        mp3_fp.seek(0)
        return mp3_fp
    except Exception as e:
        st.error(f"Erro Edge-TTS: {e}")
        return None

def gerar_audio_gtts(texto: str) -> Optional[BytesIO]:
    try:
        from gtts import gTTS
        mp3_fp = BytesIO()
        tts = gTTS(text=texto, lang='pt', slow=False)
        tts.write_to_fp(mp3_fp)
        mp3_fp.seek(0)
        return mp3_fp
    except Exception as e:
        raise RuntimeError(f"Erro gTTS: {e}")

def gerar_audio_tts(texto: str, tts_motor: str = "edge") -> Optional[BytesIO]:
    if not texto or not texto.strip():
        return None
    if tts_motor == "edge" and EDGETTS_AVAILABLE:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        audio = loop.run_until_complete(gerar_audio_edgetts(texto))
        loop.close()
        if audio:
            return audio
    return gerar_audio_gtts(texto)

def get_resolution_params(choice: str) -> dict:
    if "9:16" in choice:
        return {"w": 720, "h": 1280, "ratio": "9:16"}
    elif "16:9" in choice:
        return {"w": 1280, "h": 720, "ratio": "16:9"}
    return {"w": 1024, "h": 1024, "ratio": "1:1"}

def gerar_imagem_pollinations_flux(prompt: str, width: int, height: int) -> BytesIO:
    prompt_clean = prompt.replace('
', ' ').strip()[:800]
    prompt_encoded = urllib.parse.quote(prompt_clean)
    seed = random.randint(0, 999999)
    url = f"https://image.pollinations.ai/prompt/{prompt_encoded}?model=flux&width={width}&height={height}&seed={seed}&nologo=true"
    r = requests.get(url, timeout=40)
    r.raise_for_status()
    bio = BytesIO(r.content)
    bio.seek(0)
    return bio

def gerar_imagem_pollinations_turbo(prompt: str, width: int, height: int) -> BytesIO:
    prompt_clean = prompt.replace('
', ' ').strip()[:800]
    prompt_encoded = urllib.parse.quote(prompt_clean)
    seed = random.randint(0, 999999)
    url = f"https://image.pollinations.ai/prompt/{prompt_encoded}?width={width}&height={height}&seed={seed}&nologo=true"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    bio = BytesIO(r.content)
    bio.seek(0)
    return bio

def gerar_imagem_google_imagen(prompt: str, ratio: str) -> BytesIO:
    gem_key = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not gem_key:
        raise RuntimeError("GEMINI_API_KEY nao encontrada.")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-001:predict?key={gem_key}"
    headers = {"Content-Type": "application/json"}
    payload = {"instances": [{"prompt": prompt}], "parameters": {"sampleCount": 1, "aspectRatio": ratio}}
    r = requests.post(url, headers=headers, json=payload, timeout=45)
    r.raise_for_status()
    data = r.json()
    if "predictions" in data and len(data["predictions"]) > 0:
        b64 = data["predictions"][0]["bytesBase64Encoded"]
        bio = BytesIO(base64.b64decode(b64))
        bio.seek(0)
        return bio
    raise RuntimeError("Resposta invalida do Google Imagen.")

def despachar_geracao_imagem(prompt: str, motor: str, res_choice: str) -> BytesIO:
    params = get_resolution_params(res_choice)
    if motor == "Pollinations Flux Padrao":
        return gerar_imagem_pollinations_flux(prompt, params["w"], params["h"])
    elif motor == "Pollinations Turbo":
        return gerar_imagem_pollinations_turbo(prompt, params["w"], params["h"])
    elif motor == "Google Imagen":
        return gerar_imagem_google_imagen(prompt, params["ratio"])
    return gerar_imagem_pollinations_flux(prompt, params["w"], params["h"])

import shutil

def shutil_which(bin_name: str) -> Optional[str]:
    return shutil.which(bin_name)

def run_cmd(cmd: List[str]):
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode('utf-8', errors='replace') if e.stderr else ""
        raise RuntimeError(f"Comando falhou: {' '.join(cmd)}
{stderr}")

def get_audio_duration_seconds(path: str) -> Optional[float]:
    if not shutil_which("ffprobe"):
        return None
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path]
    try:
        p = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out = p.stdout.decode().strip()
        return float(out) if out else None
    except Exception:
        return None

def resolve_font_path(font_choice: str, uploaded_font: Optional[BytesIO]) -> Optional[str]:
    if font_choice == "Upload Personalizada" and uploaded_font:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ttf") as tmp:
            tmp.write(uploaded_font.getvalue())
            return tmp.name
    system_fonts = {
        "Padrao Sans": ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"],
        "Serif": ["/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf", "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf"],
        "Monospace": ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"]
    }
    candidates = system_fonts.get(font_choice, system_fonts["Padrao Sans"])
    for font in candidates:
        if os.path.exists(font):
            return font
    return None

def criar_preview_overlay(width: int, height: int, texts: List[Dict], global_upload: Optional[BytesIO]) -> BytesIO:
    img = Image.new("