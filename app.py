# app.py — Studio Jhonata (COMPLETO v19.1 - Google TTS)
# Features: Música Persistente, Geração em Lote, Fix NameError, Transições, Overlay, Efeitos
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

# Import para Google Cloud TTS (tentativa de importação)
try:
    from google.cloud import texttospeech
    from google.oauth2 import service_account
except ImportError:
    texttospeech = None
    service_account = None
# Fim import TTS

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
                return default_settings
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
            from groq import Groq  # type: ignore

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
    texto_limpo = texto.replace("\n", " ").strip()
    texto_limpo = re.sub(r"\b(\d{1,3})(?=[A-Za-zÁ-Úá-ú])", "", texto_limpo)
    texto_limpo = re.sub(r"\s{2,}", " ", texto_limpo)
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
        "lucas": "Lucas", "lc": "Lucas",
        "joão": "João", "joao": "João", "jo": "João"
    }
    
    evangelista_encontrado = None
    for chave, valor in mapa_nomes.items():
        if re.search(rf"\b{chave}\b", titulo_lower):
            evangelista_encontrado = valor
            break
    
    if not evangelista_encontrado:
        m_fallback = re.search(r"(?:São|S\.|Sao|San|St\.?)\s*([A-Za-zÁ-Úá-ú]+)", titulo, re.IGNORECASE)
        if m_fallback:
            nome_cand = m_fallback.group(1).strip()
            if len(nome_cand) > 2:
                evangelista_encontrado = nome_cand
            else:
                return None
        else:
            return None

    m_nums = re.search(r"(\d{1,3})\s*[,:]\s*(\d+(?:[-–]\d+)?)", titulo)
    
    if m_nums:
        capitulo = m_nums.group(1)
        versiculos_raw = m_nums.group(2)
        versiculos = versiculos_raw.replace("-", " a ").replace("–", " a ")
    else:
        return None

    return {"evangelista": evangelista_encontrado, "capitulo": capitulo, "versiculos": versiculos}

def formatar_referencia_curta(ref_biblica):
    if not ref_biblica:
        return ""
    return f"{ref_biblica['evangelista']}, Cap. {ref_biblica['capitulo']}, {ref_biblica['versiculos']}"

# =========================
# Análise de personagens via Groq
# =========================
def analisar_personagens_groq(texto_evangelho: str, banco_personagens: dict):
    client = inicializar_groq()
    system_prompt = (
        "Você é especialista em análise bíblica.\n"
        "Analise o texto e identifique TODOS os personagens bíblicos mencionados.\n\n"
        "Formato EXATO da resposta:\n\n"
        "PERSONAGENS: nome1; nome2; nome3\n\n"
        "NOVOS: NomeNovo|descrição_detalhada_aparência_física_roupas_idade_estilo (apenas se não existir no banco)\n\n"
        f"BANCO EXISTENTE: {'; '.join(banco_personagens.keys())}\n\n"
        "Exemplo:\n"
        "PERSONAGENS: Jesus; Pedro; fariseus\n"
        "NOVOS: Mulher Samaritana|mulher de 35 anos, pele morena, véu colorido, jarro d'água, expressão curiosa, túnica tradicional\n"
    )
    try:
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"TEXTO: {texto_evangelho[:1500]}"},
            ],
            temperature=0.3,
            max_tokens=400,
        )
        resultado = resp.choices[0].message.content
        personagens_detectados = {}
        m = re.search(r"PERSONAGENS:\s*(.+)", resultado)
        if m:
            nomes = [n.strip() for n in m.group(1).split(";") if n.strip()]
            for nome in nomes:
                if nome in banco_personagens:
                    personagens_detectados[nome] = banco_personagens[nome]
        m2 = re.search(r"NOVOS:\s*(.+)", resultado)
        if m2:
            novos = m2.group(1).strip()
            blocos = re.split(r";|,", novos)
            for bloco in blocos:
                if "|" in bloco:
                    nome, desc = bloco.split("|", 1)
                    nome = nome.strip()
                    desc = desc.strip()
                    if not nome:
                        continue
                    personagens_detectados[nome] = desc
                    banco_personagens[nome] = desc
        return personagens_detectados
    except Exception:
        return {}

# =========================
# APIs Liturgia
# =========================
def buscar_liturgia_api1(data_str: str):
    url = f"https://api-liturgia-diaria.vercel.app/?date={data_str}"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        dados = resp.json()
        today = dados.get("today", {})
        readings = today.get("readings", {})
        gospel = readings.get("gospel")
        if not gospel:
            return None
        referencia_liturgica = today.get("entry_title", "").strip() or "Evangelho do dia"
        titulo = (
            gospel.get("head_title", "")
            or gospel.get("title", "")
            or "Evangelho de Jesus Cristo"
        ).strip()
        texto = gospel.get("text", "").strip()
        if not texto:
            return None
        texto_limpo = limpar_texto_evangelho(texto)
        ref_biblica = extrair_referencia_biblica(titulo)
        return {
            "fonte": "api-liturgia-diaria.vercel.app",
            "titulo": titulo,
            "referencia_liturgica": referencia_liturgica,
            "texto": texto_limpo,
            "ref_biblica": ref_biblica,
        }
    except Exception:
        return None

def buscar_liturgia_api2(data_str: str):
    url = f"https://liturgia.up.railway.app/v2/{data_str}"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        dados = resp.json()
        lit = dados.get("liturgia", {})
        ev = lit.get("evangelho") or lit.get("evangelho_do_dia") or {}
        if not ev:
            return None
        texto = ev.get("texto", "") or ev.get("conteudo", "")
        if not texto:
            return None
        texto_limpo = limpar_texto_evangelho(texto)
        return {
            "fonte": "liturgia.up.railway.app",
            "titulo": "Evangelho do dia",
            "referencia_liturgica": "Evangelho do dia",
            "texto": texto_limpo,
            "ref_biblica": None,
        }
    except Exception:
        return None

def obter_evangelho_com_fallback(data_str: str):
    ev = buscar_liturgia_api1(data_str)
    if ev:
        st.info("📡 Usando api-liturgia-diaria.vercel.app")
        return ev
    ev = buscar_liturgia_api2(data_str)
    if ev:
        st.info("📡 Usando liturgia.up.railway.app")
        return ev
    st.error("❌ Não foi possível obter o Evangelho")
    return None

# =========================
# Roteiro + Prompts
# =========================
def extrair_bloco(rotulo: str, texto: str) -> str:
    padrao = rf"{rotulo}:\s*(.*?)(?=\n[A-ZÁÉÍÓÚÃÕÇ]{{3,}}:\s*|\nPROMPT_|$)"
    m = re.search(padrao, texto, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else ""

def extrair_prompt(rotulo: str, texto: str) -> str:
    padrao = rf"{rotulo}:\s*(.*?)(?=\n[A-ZÁÉÍÓÚÃÕÇ]{{3,}}:\s*|\nPROMPT_|$)"
    m = re.search(padrao, texto, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else ""

def gerar_roteiro_com_prompts_groq(texto_evangelho: str, referencia_liturgica: str, personagens: dict):
    client = inicializar_groq()
    texto_limpo = limpar_texto_evangelho(texto_evangelho)
    personagens_str = json.dumps(personagens, ensure_ascii=False)
    system_prompt = f"""Crie roteiro + 6 prompts visuais CATÓLICOS para vídeo devocional.

PERSONAGENS FIXOS: {personagens_str}

IMPORTANTE:
- 4 PARTES EXATAS: HOOK, REFLEXÃO, APLICAÇÃO, ORAÇÃO
- PROMPT_LEITURA separado (momento da leitura do Evangelho, mais calmo e reverente)
- PROMPT_GERAL para thumbnail
- USE SEMPRE as descrições exatas dos personagens
- Estilo: artístico renascentista católico, luz suave, cores quentes

Formato EXATO:

HOOK: [texto 5-8s]
PROMPT_HOOK: [prompt visual com personagens fixos]

REFLEXÃO: [texto 20-25s]
PROMPT_REFLEXÃO: [prompt visual com personagens fixos]

APLICAÇÃO: [texto 20-25s]
PROMPT_APLICACAO: [prompt visual com personagens fixos]

ORAÇÃO: [texto 20-25s]
PROMPT_ORACAO: [prompt visual com personagens fixos]

PROMPT_LEITURA: [prompt visual específico para a leitura do Evangelho, mais calmo e reverente]

PROMPT_GERAL: [prompt para thumbnail/capa]"""
    try:
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Evangelho: {referencia_liturgica}\n\n{texto_limpo[:2000]}"},
            ],
            temperature=0.7,
            max_tokens=1200,
        )
        texto_gerado = resp.choices[0].message.content
        partes: dict[str, str] = {}
        partes["hook"] = extrair_bloco("HOOK", texto_gerado)
        partes["reflexão"] = extrair_bloco("REFLEXÃO", texto_gerado)
        partes["aplicação"] = extrair_bloco("APLICAÇÃO", texto_gerado)
        partes["oração"] = extrair_bloco("ORAÇÃO", texto_gerado)
        partes["prompt_hook"] = extrair_prompt("PROMPT_HOOK", texto_gerado)
        partes["prompt_reflexão"] = extrair_prompt("PROMPT_REFLEXÃO", texto_gerado)
        partes["prompt_aplicacao"] = extrair_prompt("PROMPT_APLICACAO", texto_gerado)
        partes["prompt_oração"] = extrair_prompt("PROMPT_ORACAO", texto_gerado)
        partes["prompt_leitura"] = extrair_prompt("PROMPT_LEITURA", texto_gerado)
        m_geral = re.search(r"PROMPT_GERAL:\s*(.+)", texto_gerado, re.DOTALL | re.IGNORECASE)
        partes["prompt_geral"] = m_geral.group(1).strip() if m_geral else ""
        return partes
    except Exception as e:
        st.error(f"❌ Erro Groq: {e}")
        return None

def montar_leitura_com_formula(texto_evangelho: str, ref_biblica):
    if ref_biblica:
        abertura = (
            f"Proclamação do Evangelho de Jesus Cristo, segundo São "
            f"{ref_biblica['evangelista']}, "
            f"Capítulo {ref_biblica['capitulo']}, "
            f"versículos {ref_biblica['versiculos']}. "
            "Glória a vós, Senhor!"
        )
    else:
        abertura = (
            "Proclamação do Evangelho de Jesus Cristo, segundo São Lucas. "
            "Glória a vós, Senhor!"
        )
    fechamento = "Palavra da Salvação. Glória a vós, Senhor!"
    return f"{abertura} {texto_evangelho} {fechamento}"

# =========================
# FUNÇÕES DE ÁUDIO & VÍDEO
# =========================

def _gerar_audio_gtts_impl(texto: str) -> Optional[BytesIO]:
    """Gera áudio usando gTTS (implantação padrão)"""
    if not texto or not texto.strip():
        return None
    mp3_fp = BytesIO()
    try:
        from gtts import gTTS  # type: ignore
        tts = gTTS(text=texto, lang="pt", slow=False)
        tts.write_to_fp(mp3_fp)
        mp3_fp.seek(0)
        return mp3_fp
    except Exception as e:
        raise RuntimeError(f"Erro gTTS: {e}")

def gerar_audio_google_tts(texto: str) -> Optional[BytesIO]:
    """Gera áudio usando Google Cloud Text-to-Speech (necessita credenciais)"""
    if not texttospeech or not service_account:
        raise RuntimeError("Biblioteca google-cloud-texttospeech não instalada ou dependência faltante.")

    # 1. Tentar configurar as credenciais a partir do segredo do Streamlit
    credentials = None
    try:
        credentials_info = st.secrets.get("GOOGLE_CREDENTIALS_JSON")
        if credentials_info:
            # Assumir que o segredo contém o JSON da conta de serviço
            if isinstance(credentials_info, str):
                credentials_info = json.loads(credentials_info)
            credentials = service_account.Credentials.from_service_account_info(credentials_info)
        
        # Cliente
        client = texttospeech.TextToSpeechClient(credentials=credentials)
        
    except Exception as e:
        st.error(f"❌ Erro ao inicializar Google TTS Client. Verifique 'GOOGLE_CREDENTIALS_JSON' em Secrets: {e}")
        raise RuntimeError(f"Erro de credenciais/inicialização do Google TTS: {e}")

    # 2. Configurar a requisição
    synthesis_input = texttospeech.SynthesisInput(text=texto)
    
    # Voz neural de alta qualidade em Português do Brasil
    voice = texttospeech.VoiceSelectionParams(
        language_code="pt-BR", 
        name="pt-BR-Wavenet-B" # Voz Wavenet (Neural)
    )
    
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3 
    )
    
    # 3. Chamar a API
    response = client.synthesize_speech(
        input=synthesis_input, voice=voice, audio_config=audio_config
    )
    
    audio_fp = BytesIO(response.audio_content)
    audio_fp.seek(0)
    return audio_fp

def despachar_geracao_audio(texto: str, motor: str) -> Optional[BytesIO]:
    """Despacha a geração de áudio para o motor escolhido."""
    if not texto or not texto.strip():
        return None
        
    if motor == "Google Cloud TTS (Premium)":
        return gerar_audio_google_tts(texto)
    else: # "gTTS (Padrão)"
        return _gerar_audio_gtts_impl(texto)

# =========================
# FUNÇÕES DE IMAGEM
# =========================

def get_resolution_params(choice: str) -> dict:
    if "9:16" in choice:
        return {"w": 720, "h": 1280, "ratio": "9:16"}
    elif "16:9" in choice:
        return {"w": 1280, "h": 720, "ratio": "16:9"}
    else: # 1:1
        return {"w": 1024, "h": 1024, "ratio": "1:1"}

def gerar_imagem_pollinations_flux(prompt: str, width: int, height: int) -> BytesIO:
    prompt_clean = prompt.replace("\n", " ").strip()[:800]
    prompt_encoded = urllib.parse.quote(prompt_clean)
    seed = random.randint(0, 999999)
    url = f"https://image.pollinations.ai/prompt/{prompt_encoded}?model=flux&width={width}&height={height}&seed={seed}&nologo=true"
    r = requests.get(url, timeout=40)
    r.raise_for_status()
    bio = BytesIO(r.content)
    bio.seek(0)
    return bio

def gerar_imagem_pollinations_turbo(prompt: str, width: int, height: int) -> BytesIO:
    prompt_clean = prompt.replace("\n", " ").strip()[:800]
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
        raise RuntimeError("GEMINI_API_KEY não encontrada.")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-001:predict?key={gem_key}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "instances": [{"prompt": prompt}],
        "parameters": {"sampleCount": 1, "aspectRatio": ratio}
    }
    r = requests.post(url, headers=headers, json=payload, timeout=45)
    r.raise_for_status()
    data = r.json()
    if "predictions" in data and len(data["predictions"]) > 0:
        b64 = data["predictions"][0]["bytesBase64Encoded"]
        bio = BytesIO(base64.b64decode(b64))
        bio.seek(0)
        return bio
    else:
        raise RuntimeError("Resposta inválida do Google Imagen.")

def despachar_geracao_imagem(prompt: str, motor: str, res_choice: str) -> BytesIO:
    params = get_resolution_params(res_choice)
    if motor == "Pollinations Flux (Padrão)":
        return gerar_imagem_pollinations_flux(prompt, params["w"], params["h"])
    elif motor == "Pollinations Turbo":
        return gerar_imagem_pollinations_turbo(prompt, params["w"], params["h"])
    elif motor == "Google Imagen":
        return gerar_imagem_google_imagen(prompt, params["ratio"])
    else:
        return gerar_imagem_pollinations_flux(prompt, params["w"], params["h"])

# =========================
# Helpers
# =========================
import shutil as _shutil

def shutil_which(bin_name: str) -> Optional[str]:
    return _shutil.which(bin_name)

def run_cmd(cmd: List[str]):
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""
        raise RuntimeError(f"Comando falhou: {' '.join(cmd)}\nSTDERR: {stderr}")

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
        "Padrão (Sans)": ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", "arial.ttf"],
        "Serif": ["/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf", "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf", "times.ttf"],
        "Monospace": ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", "courier.ttf"]
    }
    candidates = system_fonts.get(font_choice, system_fonts["Padrão (Sans)"])
    for font in candidates:
        if os.path.exists(font): return font
    return None

def criar_preview_overlay(width: int, height: int, texts: List[Dict], global_upload: Optional[BytesIO]) -> BytesIO:
    img = Image.new("RGB", (width, height), "black")
    draw = ImageDraw.Draw(img)
    for item in texts:
        text = item.get("text", "")
        if not text: continue
        size = item.get("size", 30)
        y = item.get("y", 0)
        color = item.get("color", "white")
        font_style = item.get("font_style", "Padrão (Sans)")
        font_path = resolve_font_path(font_style, global_upload)
        try:
            if font_path and os.path.exists(font_path):
                font = ImageFont.truetype(font_path, size)
            else:
                font = ImageFont.load_default()
        except:
             font = ImageFont.load_default()
        try:
            length = draw.textlength(text, font=font)
        except:
             length = len(text) * size * 0.5
        x = (width - length) / 2
        draw.text((x, y), text, fill=color, font=font)
    bio = BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    return bio

def get_text_alpha_expr(anim_type: str, duration: float) -> str:
    """Retorna expressão de alpha para o drawtext baseado na animação escolhida"""
    if anim_type == "Fade In":
        # Aparece em 1s
        return f"alpha='min(1,t/1)'"
    elif anim_type == "Fade In/Out":
        # Aparece em 1s, some 1s antes do fim
        # min(1,t/1) * min(1,(dur-t)/1)
        return f"alpha='min(1,t/1)*min(1,({duration}-t)/1)'"
    else:
        # Estático
        return "alpha=1"

def sanitize_text_for_ffmpeg(text: str) -> str:
    """Limpa texto para evitar quebra do filtro drawtext (vírgulas, dois pontos, aspas)"""
    if not text: return ""
    t = text.replace(":", "\:")
    t = t.replace("'", "") 
    return t

# =========================
# Interface principal
# =========================
st.title("✨ Studio Jhonata - Automação Litúrgica")
st.markdown("---")

# ---- SIDEBAR CONFIG ----
st.sidebar.title("⚙️ Configurações")

motor_escolhido = st.sidebar.selectbox("🎨 Motor de Imagem", ["Pollinations Flux (Padrão)", "Pollinations Turbo", "Google Imagen"], index=0)
resolucao_escolhida = st.sidebar.selectbox("📏 Resolução do Vídeo", ["9:16 (Vertical/Stories)", "16:9 (Horizontal/YouTube)", "1:1 (Quadrado/Feed)"], index=0)

st.sidebar.markdown("---")

# --- NOVO: Motor TTS ---
st.sidebar.markdown("### 🗣️ Motor TTS")
tts_motor_options = ["Google Cloud TTS (Premium)", "gTTS (Padrão)"]
if not texttospeech:
    # Remove a opção premium se a biblioteca não estiver disponível
    tts_motor_options = ["gTTS (Padrão)"]
    st.sidebar.warning("⚠️ Instale 'google-cloud-texttospeech' e configure 'GOOGLE_CREDENTIALS_JSON' em Secrets para usar a opção Premium.")
tts_motor_escolhido = st.sidebar.selectbox("Motor de Voz", tts_motor_options, index=0)
# FIM NOVO

st.sidebar.markdown("---")
st.sidebar.markdown("### 🅰️ Upload de Fonte (Global)")
uploaded_font_file = st.sidebar.file_uploader("Arquivo .ttf (para opção 'Upload Personalizada')", type=["ttf"])

st.sidebar.info(f"Modo: {motor_escolhido}\nFormato: {resolucao_escolhida}\nTTS: {tts_motor_escolhido}")

if "personagens_biblicos" not in st.session_state:
    st.session_state.personagens_biblicos = inicializar_personagens()

# session state
if "roteiro_gerado" not in st.session_state:
    st.session_state["roteiro_gerado"] = None
if "leitura_montada" not in st.session_state:
    st.session_state["leitura_montada"] = ""
if "generated_images_blocks" not in st.session_state:
    st.session_state["generated_images_blocks"] = {}
if "generated_audios_blocks" not in st.session_state:
    st.session_state["generated_audios_blocks"] = {}
if "video_final_bytes" not in st.session_state:
    st.session_state["video_final_bytes"] = None
if "meta_dados" not in st.session_state:
    st.session_state["meta_dados"] = {"data": "", "ref": ""}
    
# Carregar Settings persistentes
if "overlay_settings" not in st.session_state:
    st.session_state["overlay_settings"] = load_config()

tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["📖 Gerar Roteiro", "🎨 Personagens", "🎚️ Overlay & Efeitos", "🎥 Fábrica Vídeo (Editor)", "📊 Histórico"]
)

# --------- TAB 1: ROTEIRO ----------
with tab1:
    st.header("🚀 Gerador de Roteiro")
    col1, col2 = st.columns([2, 1])
    with col1:
        data_selecionada = st.date_input("📅 Data da liturgia:", value=date.today(), min_value=date(2023, 1, 1))
    with col2:
        st.info("Status: ✅ pronto para gerar")

    if st.button("🚀 Gerar Roteiro Completo", type="primary"):
        data_str = data_selecionada.strftime("%Y-%m-%d")
        data_formatada_display = data_selecionada.strftime("%d.%m.%Y") 

        with st.status("📝 Gerando roteiro...", expanded=True) as status:
            st.write("🔍 Buscando Evangelho...")
            liturgia = obter_evangelho_com_fallback(data_str)
            if not liturgia:
                status.update(label="Falha ao buscar evangelho", state="error")
                st.stop()

            ref_curta = formatar_referencia_curta(liturgia.get("ref_biblica"))
            st.session_state["meta_dados"] = {
                "data": data_formatada_display,
                "ref": ref_curta or "Evangelho do Dia"
            }

            st.write("🤖 Analisando personagens com IA...")
            personagens_detectados = analisar_personagens_groq(liturgia["texto"], st.session_state.personagens_biblicos)

            st.write("✨ Criando roteiro e prompts...")
            roteiro = gerar_roteiro_com_prompts_groq(liturgia["texto"], liturgia["referencia_liturgica"], {**st.session_state.personagens_biblicos, **personagens_detectados})

            if roteiro:
                status.update(label="Roteiro gerado com sucesso!", state="complete", expanded=False)
            else:
                status.update(label="Erro ao gerar roteiro", state="error")
                st.stop()

        leitura_montada = montar_leitura_com_formula(liturgia["texto"], liturgia.get("ref_biblica"))
        st.session_state["roteiro_gerado"] = roteiro
        st.session_state["leitura_montada"] = leitura_montada
        st.rerun()

    if st.session_state.get("roteiro_gerado"):
        roteiro = st.session_state["roteiro_gerado"]
        st.markdown("---")
        col_esq, col_dir = st.columns(2)
        with col_esq:
            st.markdown("### 🎣 HOOK"); st.markdown(roteiro.get("hook", "")); st.code(roteiro.get("prompt_hook", ""), language="text")
            st.markdown("### 📖 LEITURA"); st.markdown(st.session_state.get("leitura_montada", "")[:300] + "..."); st.code(roteiro.get("prompt_leitura", ""), language="text")
        with col_dir:
            st.markdown("### 💭 REFLEXÃO"); st.markdown(roteiro.get("reflexão", "")); st.code(roteiro.get("prompt_reflexão", ""), language="text")
            st.markdown("### 🌟 APLICAÇÃO"); st.markdown(roteiro.get("aplicação", "")); st.code(roteiro.get("prompt_aplicacao", ""), language="text")
        st.markdown("### 🙏 ORAÇÃO"); st.markdown(roteiro.get("oração", "")); st.code(roteiro.get("prompt_oração", ""), language="text")
        st.markdown("### 🖼️ THUMBNAIL"); st.code(roteiro.get("prompt_geral", ""), language="text")
        st.success("Roteiro gerado! Vá para 'Overlay & Efeitos' para ajustar o visual.")

# --------- TAB 2: PERSONAGENS ----------
with tab2:
    st.header("🎨 Banco de Personagens")
    banco = st.session_state.personagens_biblicos.copy()
    col1, col2 = st.columns(2)
    with col1:
        for i, (nome, desc) in enumerate(banco.items()):
            with st.expander(f"✏️ {nome}"):
                novo_nome = st.text_input(f"Nome", value=nome, key=f"n_{i}")
                nova_desc = st.text_area(f"Desc", value=desc, key=f"d_{i}")
                if st.button("Salvar", key=f"s_{i}"):
                    if novo_nome != nome: del st.session_state.personagens_biblicos[nome]
                    st.session_state.personagens_biblicos[novo_nome] = nova_desc
                    st.rerun()
                if st.button("Apagar", key=f"a_{i}"):
                    del st.session_state.personagens_biblicos[nome]
                    st.rerun()
    with col2:
        st.markdown("### ➕ Novo")
        nn = st.text_input("Nome", key="new_n")
        nd = st.text_area("Descrição", key="new_d")
        if st.button("Adicionar") and nn and nd:
            st.session_state.personagens_biblicos[nn] = nd
            st.rerun()

# --------- TAB 3: OVERLAY & EFEITOS ----------
with tab3:
    st.header("🎚️ Editor de Overlay & Efeitos")
    
    col_settings, col_preview = st.columns([1, 1])
    ov_sets = st.session_state["overlay_settings"]
    font_options = ["Padrão (Sans)", "Serif", "Monospace", "Upload Personalizada"]
    anim_options = ["Estático", "Fade In", "Fade In/Out"]
    
    with col_settings:
        with st.expander("✨ Efeitos Visuais (Movimento)", expanded=True):
            effect_opts = ["Zoom In (Ken Burns)", "Zoom Out", "Panorâmica Esquerda", "Panorâmica Direita", "Estático (Sem movimento)"]
            curr_eff = ov_sets.get("effect_type", effect_opts[0])
            if curr_eff not in effect_opts: curr_eff = effect_opts[0]
            ov_sets["effect_type"] = st.selectbox("Tipo de Movimento", effect_opts, index=effect_opts.index(curr_eff))
            ov_sets["effect_speed"] = st.slider("Intensidade do Movimento", 1, 10, ov_sets.get("effect_speed", 3), help="1 = Muito Lento, 10 = Rápido")

        with st.expander("🎬 Transições de Cena", expanded=True):
            trans_opts = ["Fade (Escurecer)", "Corte Seco (Nenhuma)"]
            curr_trans = ov_sets.get("trans_type", trans_opts[0])
            if curr_trans not in trans_opts: curr_trans = trans_opts[0]
            ov_sets["trans_type"] = st.selectbox("Tipo de Transição", trans_opts, index=trans_opts.index(curr_trans))
            ov_sets["trans_dur"] = st.slider("Duração da Transição (s)", 0.1, 2.0, ov_sets.get("trans_dur", 0.5), 0.1)

        with st.expander("📝 Texto Overlay (Cabeçalho)", expanded=True):
            st.markdown("**Linha 1: Título**")
            curr_f1 = ov_sets.get("line1_font", font_options[0])
            if curr_f1 not in font_options: curr_f1 = font_options[0]
            ov_sets["line1_font"] = st.selectbox("Fonte L1", font_options, index=font_options.index(curr_f1), key="f1")
            ov_sets["line1_size"] = st.slider("Tamanho L1", 10, 150, ov_sets.get("line1_size", 40), key="s1")
            ov_sets["line1_y"] = st.slider("Posição Y L1", 0, 800, ov_sets.get("line1_y", 40), key="y1")
            
            curr_a1 = ov_sets.get("line1_anim", anim_options[0])
            if curr_a1 not in anim_options: curr_a1 = anim_options[0]
            ov_sets["line1_anim"] = st.selectbox("Animação L1", anim_options, index=anim_options.index(curr_a1), key="a1")
            
            st.markdown("---")
            st.markdown("**Linha 2: Data**")
            curr_f2 = ov_sets.get("line2_font", font_options[0])
            if curr_f2 not in font_options: curr_f2 = font_options[0]
            ov_sets["line2_font"] = st.selectbox("Fonte L2", font_options, index=font_options.index(curr_f2), key="f2")
            ov_sets["line2_size"] = st.slider("Tamanho L2", 10, 150, ov_sets.get("line2_size", 28), key="s2")
            ov_sets["line2_y"] = st.slider("Posição Y L2", 0, 800, ov_sets.get("line2_y", 90), key="y2")
            
            curr_a2 = ov_sets.get("line2_anim", anim_options[0])
            if curr_a2 not in anim_options: curr_a2 = anim_options[0]
            ov_sets["line2_anim"] = st.selectbox("Animação L2", anim_options, index=anim_options.index(curr_a2), key="a2")

            st.markdown("---")
            st.markdown("**Linha 3: Referência**")
            curr_f3 = ov_sets.get("line3_font", font_options[0])
            if curr_f3 not in font_options: curr_f3 = font_options[0]
            ov_sets["line3_font"] = st.selectbox("Fonte L3", font_options, index=font_options.index(curr_f3), key="f3")
            ov_sets["line3_size"] = st.slider("Tamanho L3", 10, 150, ov_sets.get("line3_size", 24), key="s3")
            ov_sets["line3_y"] = st.slider("Posição Y L3", 0, 800, ov_sets.get("line3_y", 130), key="y3")
            
            curr_a3 = ov_sets.get("line3_anim", anim_options[0])
            if curr_a3 not in anim_options: curr_a3 = anim_options[0]
            ov_sets["line3_anim"] = st.selectbox("Animação L3", anim_options, index=anim_options.index(curr_a3), key="a3")

        st.session_state["overlay_settings"] = ov_sets
        if st.button("💾 Salvar Configurações (Persistente)"):
            if save_config(ov_sets):
                st.success("Configuração salva no disco com sucesso!")

    with col_preview:
        st.subheader("Pré-visualização (Overlay)")
        res_params = get_resolution_params(resolucao_escolhida)
        preview_scale_factor = 0.4
        preview_w = int(res_params["w"] * preview_scale_factor)
        preview_h = int(res_params["h"] * preview_scale_factor)
        text_scale = preview_scale_factor

        meta = st.session_state.get("meta_dados", {})
        txt_l1 = "EVANGELHO"
        txt_l2 = meta.get("data", "29.11.2025")
        txt_l3 = meta.get("ref", "Lucas, Cap. 1, 26-38")
        
        preview_texts = [
            {"text": txt_l1, "size": int(ov_sets["line1_size"] * text_scale), "y": int(ov_sets["line1_y"] * text_scale), "font_style": ov_sets["line1_font"], "color": "white"},
            {"text": txt_l2, "size": int(ov_sets["line2_size"] * text_scale), "y": int(ov_sets["line2_y"] * text_scale), "font_style": ov_sets["line2_font"], "color": "white"},
            {"text": txt_l3, "size": int(ov_sets["line3_size"] * text_scale), "y": int(ov_sets["line3_y"] * text_scale), "font_style": ov_sets["line3_font"], "color": "white"},
        ]
        
        prev_img = criar_preview_overlay(preview_w, preview_h, preview_texts, uploaded_font_file)
        st.image(prev_img, caption=f"Preview Overlay em {resolucao_escolhida}", use_column_width=False)


# --------- TAB 4: FÁBRICA DE VÍDEO ----------
with tab4:
    st.header("🎥 Editor de Cenas")
    
    if not st.session_state.get("roteiro_gerado"):
        st.warning("⚠️ Gere o roteiro na Aba 1 primeiro.")
        st.stop()
    
    roteiro = st.session_state["roteiro_gerado"]
    
    blocos_config = [
        {"id": "hook", "label": "🎣 HOOK", "prompt_key": "prompt_hook", "text_key": "hook"},
        {"id": "leitura", "label": "📖 LEITURA", "prompt_key": "prompt_leitura", "text_key": "leitura_montada"}, 
        {"id": "reflexão", "label": "💭 REFLEXÃO", "prompt_key": "prompt_reflexão", "text_key": "reflexão"},
        {"id": "aplicação", "label": "🌟 APLICAÇÃO", "prompt_key": "prompt_aplicacao", "text_key": "aplicação"},
        {"id": "oração", "label": "🙏 ORAÇÃO", "prompt_key": "prompt_oração", "text_key": "oração"},
        {"id": "thumbnail", "label": "🖼️ THUMBNAIL", "prompt_key": "prompt_geral", "text_key": None}
    ]

    st.info(f"⚙️ Config: **{motor_escolhido}** | Resolução: **{resolucao_escolhida}** | TTS: **{tts_motor_escolhido}**")

    # Botões de Geração em Lote (Topo da Fábrica)
    col_batch_1, col_batch_2 = st.columns(2)
    with col_batch_1:
        if st.button("🔊 Gerar Todos os Áudios", use_container_width=True):
            with st.status("Gerando áudios em lote...", expanded=True) as status:
                total = len([b for b in blocos_config if b["text_key"]])
                count = 0
                for b in blocos_config:
                    if not b["text_key"]: continue
                    bid = b["id"]
                    txt = roteiro.get(b["text_key"]) if bid != "leitura" else st.session_state.get("leitura_montada", "")
                    if txt:
                        st.write(f"Gerando áudio: {b['label']}...")
                        try:
                            # Chama o dispatcher com o motor TTS escolhido
                            audio = despachar_geracao_audio(txt, tts_motor_escolhido)
                            st.session_state["generated_audios_blocks"][bid] = audio
                            count += 1
                        except Exception as e:
                            st.error(f"Erro em {bid}: {e}")
                status.update(label=f"Concluído! {count}/{total} áudios gerados.", state="complete")
                st.rerun()

    with col_batch_2:
        if st.button("✨ Gerar Todas as Imagens", use_container_width=True):
            with st.status("Gerando imagens em lote...", expanded=True) as status:
                total = len(blocos_config)
                count = 0
                for i, b in enumerate(blocos_config):
                    bid = b["id"]
                    prompt = roteiro.get(b["prompt_key"], "")
                    if prompt:
                        st.write(f"Gerando imagem ({i+1}/{total}): {b['label']}...")
                        try:
                            img = despachar_geracao_imagem(prompt, motor_escolhido, resolucao_escolhida)
                            st.session_state["generated_images_blocks"][bid] = img
                            count += 1
                        except Exception as e:
                            st.error(f"Erro em {bid}: {e}")
                status.update(label=f"Concluído! {count}/{total} imagens geradas.", state="complete")
                st.rerun()

    st.divider()

    for bloco in blocos_config:
        block_id = bloco["id"]
        with st.container(border=True):
            st.subheader(bloco["label"])
            col_text, col_media = st.columns([1, 1.2])
            with col_text:
                if bloco["text_key"]:
                    txt_content = roteiro.get(bloco["text_key"]) if block_id != "leitura" else st.session_state.get("leitura_montada", "")
                    st.caption("📜 Texto para Narração:")
                    st.markdown(f"_{txt_content[:250]}..._" if txt_content else "_Sem texto_")
                    if st.button(f"🔊 Gerar Áudio ({block_id})", key=f"btn_audio_{block_id}"):
                        if txt_content:
                            try:
                                # Chama o dispatcher com o motor TTS escolhido
                                audio = despachar_geracao_audio(txt_content, tts_motor_escolhido)
                                st.session_state["generated_audios_blocks"][block_id] = audio
                                st.rerun()
                            except Exception as e:
                                st.error(f"Erro áudio: {e}")
                    if block_id in st.session_state["generated_audios_blocks"]:
                        st.audio(st.session_state["generated_audios_blocks"][block_id], format="audio/mp3")
                prompt_content = roteiro.get(bloco["prompt_key"], "")
                st.caption("📋 Prompt Visual:")
                st.code(prompt_content, language="text")
            with col_media:
                st.caption("🖼️ Imagem da Cena:")
                current_img = st.session_state["generated_images_blocks"].get(block_id)
                if current_img:
                    try:
                        current_img.seek(0)
                        st.image(current_img, use_column_width=True)
                    except Exception:
                        st.error("Erro ao exibir imagem.")
                else:
                    st.info("Nenhuma imagem definida.")
                c_gen, c_up = st.columns([1.5, 2])
                with c_gen:
                    if st.button(f"✨ Gerar ({resolucao_escolhida.split()[0]})", key=f"btn_gen_{block_id}"):
                        if prompt_content:
                            with st.spinner(f"Criando no formato {resolucao_escolhida}..."):
                                try:
                                    img = despachar_geracao_imagem(prompt_content, motor_escolhido, resolucao_escolhida)
                                    st.session_state["generated_images_blocks"][block_id] = img
                                    st.success("Gerada!")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Erro: {e}")
                        else:
                            st.warning("Sem prompt.")
                with c_up:
                    uploaded_file = st.file_uploader("Ou envie a sua:", type=["png", "jpg", "jpeg"], key=f"upload_{block_id}")
                    if uploaded_file is not None:
                        bytes_data = uploaded_file.read()
                        st.session_state["generated_images_blocks"][block_id] = BytesIO(bytes_data)
                        st.success("Enviada!")

    st.divider()
    st.header("🎬 Finalização")
    usar_overlay = st.checkbox("Adicionar Cabeçalho (Overlay Personalizado)", value=True)
    
    st.subheader("🎵 Música de Fundo (Opcional)")
    
    # Check if saved music exists
    saved_music_exists = os.path.exists(SAVED_MUSIC_FILE)
    
    col_mus_1, col_mus_2 = st.columns(2)
    
    with col_mus_1:
        if saved_music_exists:
            st.success("💾 Música Padrão Ativa")
            st.audio(SAVED_MUSIC_FILE)
            if st.button("❌ Remover Música Padrão"):
                if delete_music_file():
                    st.rerun()
        else:
            st.info("Nenhuma música padrão salva.")

    with col_mus_2:
        music_upload = st.file_uploader("Upload Música (MP3)", type=["mp3"])
        if music_upload:
            st.audio(music_upload)
            if st.button("💾 Salvar como Música Padrão"):
                if save_music_file(music_upload.getvalue()):
                    st.success("Música padrão salva!")
                    st.rerun()

    music_vol = st.slider("Volume da Música (em relação à voz)", 0.0, 1.0, load_config().get("music_vol", 0.15))

    if st.button("Renderizar Vídeo Completo (Unir tudo)", type="primary"):
        with st.status("Renderizando vídeo com efeitos...", expanded=True) as status:
            try:
                blocos_relevantes = [b for b in blocos_config if b["id"] != "thumbnail"]
                if not shutil_which("ffmpeg"):
                    status.update(label="FFmpeg não encontrado!", state="error")
                    st.stop()
                
                font_path = resolve_font_path(font_choice, uploaded_font_file)
                if usar_overlay and not font_path:
                    st.warning("⚠️ Fonte não encontrada. O overlay pode falhar.")
                
                temp_dir = tempfile.mkdtemp()
                clip_files = []
                
                meta = st.session_state.get("meta_dados", {})
                txt_dt = meta.get("data", "")
                txt_ref = meta.get("ref", "")
                
                map_titulos = {"hook": "EVANGELHO", "leitura": "EVANGELHO", "reflexão": "REFLEXÃO", "aplicação": "APLICAÇÃO", "oração": "ORAÇÃO"}
                
                res_params = get_resolution_params(resolucao_escolhida)
                s_out = f"{res_params['w']}x{res_params['h']}"
                
                sets = st.session_state["overlay_settings"]
                speed_val = sets["effect_speed"] * 0.0005 
                
                if sets["effect_type"] == "Zoom In (Ken Burns)":
                    zoom_expr = f"z='min(zoom+{speed_val},1.5)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                elif sets["effect_type"] == "Zoom Out":
                    zoom_expr = f"z='max(1,1.5-{speed_val}*on)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                elif sets["effect_type"] == "Panorâmica Esquerda":
                    zoom_expr = f"z=1.2:x='min(x+{speed_val}*100,iw-iw/zoom)':y='(ih-ih/zoom)/2'"
                elif sets["effect_type"] == "Panorâmica Direita":
                    zoom_expr = f"z=1.2:x='max(0,x-{speed_val}*100)':y='(ih-ih/zoom)/2'"
                else: 
                    zoom_expr = "z=1:x=0:y=0" 

                for b in blocos_relevantes:
                    bid = b["id"]
                    img_bio = st.session_state["generated_images_blocks"].get(bid)
                    audio_bio = st.session_state["generated_audios_blocks"].get(bid)
                    if not img_bio or not audio_bio: continue
                        
                    st.write(f"Processando clipe: {bid}...")
                    img_path = os.path.join(temp_dir, f"{bid}.png")
                    audio_path = os.path.join(temp_dir, f"{bid}.mp3")
                    clip_path = os.path.join(temp_dir, f"{bid}.mp4")
                    
                    img_bio.seek(0); audio_bio.seek(0)
                    with open(img_path, "wb") as f: f.write(img_bio.read())
                    with open(audio_path, "wb") as f: f.write(audio_bio.read())
                    
                    dur = get_audio_duration_seconds(audio_path) or 5.0
                    frames = int(dur * 25)

                    vf_filters = []
                    if sets["effect_type"] != "Estático (Sem movimento)":
                        vf_filters.append(f"zoompan={zoom_expr}:d={frames}:s={s_out}")
                    else:
                        vf_filters.append(f"scale={s_out}")

                    if sets["trans_type"] == "Fade (Escurecer)":
                        td = sets["trans_dur"]
                        vf_filters.append(f"fade=t=in:st=0:d={td},fade=t=out:st={dur-td}:d={td}")

                    if usar_overlay:
                        titulo_atual = map_titulos.get(bid, "EVANGELHO")
                        f1_path = resolve_font_path(sets["line1_font"], uploaded_font_file)
                        f2_path = resolve_font_path(sets["line2_font"], uploaded_font_file)
                        f3_path = resolve_font_path(sets["line3_font"], uploaded_font_file)
                        
                        alp1 = get_text_alpha_expr(sets.get("line1_anim", "Estático"), dur)
                        alp2 = get_text_alpha_expr(sets.get("line2_anim", "Estático"), dur)
                        alp3 = get_text_alpha_expr(sets.get("line3_anim", "Estático"), dur)

                        clean_t1 = sanitize_text_for_ffmpeg(titulo_atual)
                        clean_t2 = sanitize_text_for_ffmpeg(txt_dt)
                        clean_t3 = sanitize_text_for_ffmpeg(txt_ref)

                        if f1_path: vf_filters.append(f"drawtext=fontfile='{f1_path}':text='{clean_t1}':fontcolor=white:fontsize={sets['line1_size']}:x=(w-text_w)/2:y={sets['line1_y']}:shadowcolor=black:shadowx=2:shadowy=2:{alp1}")
                        if f2_path: vf_filters.append(f"drawtext=fontfile='{f2_path}':text='{clean_t2}':fontcolor=white:fontsize={sets['line2_size']}:x=(w-text_w)/2:y={sets['line2_y']}:shadowcolor=black:shadowx=2:shadowy=2:{alp2}")
                        if f3_path: vf_filters.append(f"drawtext=fontfile='{f3_path}':text='{clean_t3}':fontcolor=white:fontsize={sets['line3_size']}:x=(w-text_w)/2:y={sets['line3_y']}:shadowcolor=black:shadowx=2:shadowy=2:{alp3}")

                    filter_complex = ",".join(vf_filters)
                    
                    cmd = ["ffmpeg", "-y", "-loop", "1", "-i", img_path, "-i", audio_path, "-vf", filter_complex, "-c:v", "libx64", "-t", f"{dur}", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", clip_path]
                    run_cmd(cmd)
                    clip_files.append(clip_path)
                
                if clip_files:
                    concat_list = os.path.join(temp_dir, "list.txt")
                    with open(concat_list, "w") as f:
                        for p in clip_files: f.write(f"file '{p}'\n")
                    
                    temp_video = os.path.join(temp_dir, "temp_video.mp4")
                    run_cmd(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list, "-c", "copy", temp_video])
                    
                    final_path = os.path.join(temp_dir, "final.mp4")
                    
                    # Lógica de Música: 1. Uploaded, 2. Saved Default, 3. None
                    music_source_path = None
                    
                    if music_upload:
                        music_source_path = os.path.join(temp_dir, "bg.mp3")
                        with open(music_source_path, "wb") as f: f.write(music_upload.getvalue())
                    elif saved_music_exists:
                        music_source_path = SAVED_MUSIC_FILE
                        
                    if music_source_path:
                        cmd_mix = [
                            "ffmpeg", "-y",
                            "-i", temp_video,
                            "-stream_loop", "-1", "-i", music_source_path,
                            "-filter_complex", f"[1:a]volume={music_vol}[bg];[0:a][bg]amix=inputs=2:duration=first:dropout_transition=2[a]",
                            "-map", "0:v", "-map", "[a]",
                            "-c:v", "copy", "-c:a", "aac", "-shortest",
                            final_path
                        ]
                        run_cmd(cmd_mix)
                    else:
                        os.rename(temp_video, final_path)

                    with open(final_path, "rb") as f:
                        st.session_state["video_final_bytes"] = BytesIO(f.read())
                    status.update(label="Vídeo Renderizado com Sucesso!", state="complete")
                else:
                    status.update(label="Nenhum clipe válido gerado.", state="error")
            except Exception as e:
                status.update(label="Erro na renderização", state="error")
                st.error(f"Detalhes: {e}")
                st.error(traceback.format_exc())

    if st.session_state.get("video_final_bytes"):
        st.success("Vídeo pronto!")
        st.video(st.session_state["video_final_bytes"])
        st.download_button("⬇️ Baixar MP4", st.session_state["video_final_bytes"], "video_jhonata.mp4", "video/mp4")

# --------- TAB 5: HISTÓRICO ----------
with tab5:
    st.info("Histórico em desenvolvimento.")

st.markdown("---")
st.caption("Studio Jhonata v19.1 - Música Padrão + Google TTS")