# app.py — Gerador de Evangelho (v20.0 - Roteiro Intacto + Legendas)
# Base: v19.5 (Estável) + Feature de Legendas no Overlay
import os
import re
import json
import time
import tempfile
import traceback
import subprocess
import urllib.parse
import random
import textwrap
from io import BytesIO
from datetime import date
from typing import List, Optional, Tuple, Dict
import base64

import requests
from PIL import Image, ImageDraw, ImageFont
import streamlit as st

# Force ffmpeg path for imageio if needed (Streamlit Cloud)
os.environ.setdefault("IMAGEIO_FFMPEG_EXE", "/usr/bin/ffmpeg")

# Arquivos de configuração persistentes
CONFIG_FILE = "overlay_config.json"
SAVED_MUSIC_FILE = "saved_bg_music.mp3"

# =========================
# Page config
# =========================
st.set_page_config(
    page_title="Gerador de Evangelho",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =========================
# Persistência de Configurações
# =========================
def load_config():
    """Carrega configurações do disco ou retorna padrão"""
    default_settings = {
        # Overlay Cabeçalho
        "line1_y": 40, "line1_size": 40, "line1_font": "Padrão (Sans)", "line1_anim": "Estático",
        "line2_y": 90, "line2_size": 28, "line2_font": "Padrão (Sans)", "line2_anim": "Estático",
        "line3_y": 130, "line3_size": 24, "line3_font": "Padrão (Sans)", "line3_anim": "Estático",
        # Efeitos Vídeo
        "effect_type": "Zoom In (Ken Burns)", "effect_speed": 3,
        "trans_type": "Fade (Escurecer)", "trans_dur": 0.5,
        "music_vol": 0.15,
        # Legendas (Novos campos)
        "sub_enabled": False,
        "sub_font": "Padrão (Sans)",
        "sub_size": 45,
        "sub_y": 100,
        "sub_color": "#FFFFFF",
        "sub_outline_color": "#000000",
        "sub_bg_box": False
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
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(settings, f)
        return True
    except Exception as e:
        st.error(f"Erro ao salvar configurações: {e}")
        return False

def save_music_file(file_bytes):
    try:
        with open(SAVED_MUSIC_FILE, "wb") as f:
            f.write(file_bytes)
        return True
    except Exception as e:
        st.error(f"Erro ao salvar música: {e}")
        return False

def delete_music_file():
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
# Helpers de Texto
# =========================
def limpar_texto_evangelho(texto: str) -> str:
    if not texto: return ""
    texto_limpo = texto.replace("\n", " ").strip()
    texto_limpo = re.sub(r"\b(\d{1,3})(?=[A-Za-zÁ-Úá-ú])", "", texto_limpo)
    texto_limpo = re.sub(r"\s{2,}", " ", texto_limpo)
    return texto_limpo.strip()

def extrair_referencia_biblica(titulo: str):
    if not titulo: return None
    titulo_lower = titulo.lower()
    mapa_nomes = {
        "mateus": "Mateus", "mt": "Mateus", "marcos": "Marcos", "mc": "Marcos",
        "lucas": "Lucas", "lc": "Lucas", "joão": "João", "joao": "João", "jo": "João"
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
            if len(nome_cand) > 2: evangelista_encontrado = nome_cand
            else: return None
        else: return None

    m_nums = re.search(r"(\d{1,3})\s*[,:]\s*(\d+(?:[-–]\d+)?)", titulo)
    if m_nums:
        capitulo = m_nums.group(1)
        versiculos_raw = m_nums.group(2)
        versiculos = versiculos_raw.replace("-", " a ").replace("–", " a ")
    else: return None

    return {"evangelista": evangelista_encontrado, "capitulo": capitulo, "versiculos": versiculos}

def formatar_referencia_curta(ref_biblica):
    if not ref_biblica: return ""
    return f"{ref_biblica['evangelista']}, Cap. {ref_biblica['capitulo']}, {ref_biblica['versiculos']}"

def sanitize_text_for_ffmpeg(text: str) -> str:
    """Limpa texto para evitar quebra do filtro drawtext"""
    if not text: return ""
    t = text.replace("\n", " ")
    t = t.replace(":", "\\:")
    t = t.replace("'", "")
    t = t.replace("%", "\\%")
    return t

def wrap_text_ffmpeg(text: str, font_path: str, font_size: int, max_width: int) -> str:
    """Quebra o texto em linhas para caber na largura (Função Visual apenas)"""
    if not text: return ""
    # Estimativa de caracteres por linha
    avg_char_width = font_size * 0.5 
    chars_per_line = int(max_width / avg_char_width)
    
    wrapper = textwrap.TextWrapper(width=chars_per_line)
    lines = wrapper.wrap(text)
    return "\n".join(lines)

# =========================
# Lógica de Roteiro (ORIGINAL V19 - INTACTA)
# =========================
def extrair_bloco(rotulo: str, texto: str) -> str:
    padrao = rf"{rotulo}:\s*(.*?)(?=\n[A-ZÁÉÍÓÚÃÕÇ]{{3,}}:\s*|\nPROMPT_|$)"
    m = re.search(padrao, texto, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else ""

def extrair_prompt(rotulo: str, texto: str) -> str:
    padrao = rf"{rotulo}:\s*(.*?)(?=\n[A-ZÁÉÍÓÚÃÕÇ]{{3,}}:\s*|\nPROMPT_|$)"
    m = re.search(padrao, texto, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else ""

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
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": f"TEXTO: {texto_evangelho[:1500]}"}],
            temperature=0.3, max_tokens=400,
        )
        resultado = resp.choices[0].message.content
        personagens_detectados = {}
        m = re.search(r"PERSONAGENS:\s*(.+)", resultado)
        if m:
            nomes = [n.strip() for n in m.group(1).split(";") if n.strip()]
            for nome in nomes:
                if nome in banco_personagens: personagens_detectados[nome] = banco_personagens[nome]
        m2 = re.search(r"NOVOS:\s*(.+)", resultado)
        if m2:
            novos = m2.group(1).strip()
            blocos = re.split(r";|,", novos)
            for bloco in blocos:
                if "|" in bloco:
                    nome, desc = bloco.split("|", 1)
                    nome = nome.strip()
                    desc = desc.strip()
                    if not nome: continue
                    personagens_detectados[nome] = desc
                    banco_personagens[nome] = desc
        return personagens_detectados
    except Exception: return {}

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
- Estilo: artístico renascentista católico, luz suave, cores quentes
Formato EXATO:
HOOK: [texto 5-8s]
PROMPT_HOOK: [prompt visual]
REFLEXÃO: [texto 20-25s]
PROMPT_REFLEXÃO: [prompt visual]
APLICAÇÃO: [texto 20-25s]
PROMPT_APLICACAO: [prompt visual]
ORAÇÃO: [texto 20-25s]
PROMPT_ORACAO: [prompt visual]
PROMPT_LEITURA: [prompt visual]
PROMPT_GERAL: [prompt thumbnail]"""
    try:
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": f"Evangelho: {referencia_liturgica}\n\n{texto_limpo[:2000]}"}],
            temperature=0.7, max_tokens=1200,
        )
        texto_gerado = resp.choices[0].message.content
        partes = {}
        # Usando a lógica v19 original
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
        abertura = f"Proclamação do Evangelho de Jesus Cristo, segundo São {ref_biblica['evangelista']}, Capítulo {ref_biblica['capitulo']}, versículos {ref_biblica['versiculos']}. Glória a vós, Senhor!"
    else:
        abertura = "Proclamação do Evangelho de Jesus Cristo, segundo São Lucas. Glória a vós, Senhor!"
    fechamento = "Palavra da Salvação. Glória a vós, Senhor!"
    return f"{abertura} {texto_evangelho} {fechamento}"

# =========================
# APIs Externas
# =========================
def buscar_liturgia_api1(data_str: str):
    url = f"https://api-liturgia-diaria.vercel.app/?date={data_str}"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        dados = resp.json()
        gospel = dados.get("today", {}).get("readings", {}).get("gospel")
        if not gospel: return None
        ref = dados.get("today", {}).get("entry_title", "") or "Evangelho do dia"
        tit = gospel.get("head_title", "") or gospel.get("title", "") or "Evangelho"
        txt = gospel.get("text", "").strip()
        if not txt: return None
        return {"fonte": "api1", "titulo": tit, "referencia_liturgica": ref, "texto": limpar_texto_evangelho(txt), "ref_biblica": extrair_referencia_biblica(tit)}
    except: return None

def buscar_liturgia_api2(data_str: str):
    url = f"https://liturgia.up.railway.app/v2/{data_str}"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        dados = resp.json()
        ev = dados.get("liturgia", {}).get("evangelho") or dados.get("liturgia", {}).get("evangelho_do_dia") or {}
        if not ev: return None
        txt = ev.get("texto", "") or ev.get("conteudo", "")
        if not txt: return None
        return {"fonte": "api2", "titulo": "Evangelho", "referencia_liturgica": "Evangelho do dia", "texto": limpar_texto_evangelho(txt), "ref_biblica": None}
    except: return None

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
# Mídia Generation
# =========================
def gerar_audio_gtts(texto: str) -> Optional[BytesIO]:
    if not texto or not texto.strip(): return None
    mp3_fp = BytesIO()
    try:
        from gtts import gTTS  # type: ignore
        tts = gTTS(text=texto, lang="pt", slow=False)
        tts.write_to_fp(mp3_fp)
        mp3_fp.seek(0)
        return mp3_fp
    except Exception as e: raise RuntimeError(f"Erro gTTS: {e}")

def get_resolution_params(choice: str) -> dict:
    if "9:16" in choice: return {"w": 720, "h": 1280, "ratio": "9:16"}
    elif "16:9" in choice: return {"w": 1280, "h": 720, "ratio": "16:9"}
    else: return {"w": 1024, "h": 1024, "ratio": "1:1"}

def gerar_imagem_pollinations_flux(prompt: str, width: int, height: int) -> BytesIO:
    prompt_clean = prompt.replace("\n", " ").strip()[:800]
    prompt_encoded = urllib.parse.quote(prompt_clean)
    seed = random.randint(0, 999999)
    url = f"https://image.pollinations.ai/prompt/{prompt_encoded}?model=flux&width={width}&height={height}&seed={seed}&nologo=true"
    r = requests.get(url, timeout=40); r.raise_for_status()
    bio = BytesIO(r.content); bio.seek(0)
    return bio

def gerar_imagem_pollinations_turbo(prompt: str, width: int, height: int) -> BytesIO:
    prompt_clean = prompt.replace("\n", " ").strip()[:800]
    prompt_encoded = urllib.parse.quote(prompt_clean)
    seed = random.randint(0, 999999)
    url = f"https://image.pollinations.ai/prompt/{prompt_encoded}?width={width}&height={height}&seed={seed}&nologo=true"
    r = requests.get(url, timeout=30); r.raise_for_status()
    bio = BytesIO(r.content); bio.seek(0)
    return bio

def gerar_imagem_google_imagen(prompt: str, ratio: str) -> BytesIO:
    gem_key = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not gem_key: raise RuntimeError("GEMINI_API_KEY não encontrada.")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-001:predict?key={gem_key}"
    payload = {"instances": [{"prompt": prompt}], "parameters": {"sampleCount": 1, "aspectRatio": ratio}}
    r = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=45); r.raise_for_status()
    data = r.json()
    if "predictions" in data and len(data["predictions"]) > 0:
        b64 = data["predictions"][0]["bytesBase64Encoded"]
        bio = BytesIO(base64.b64decode(b64)); bio.seek(0)
        return bio
    else: raise RuntimeError("Resposta inválida do Google Imagen.")

def despachar_geracao_imagem(prompt: str, motor: str, res_choice: str) -> BytesIO:
    params = get_resolution_params(res_choice)
    if "Flux" in motor: return gerar_imagem_pollinations_flux(prompt, params["w"], params["h"])
    elif "Turbo" in motor: return gerar_imagem_pollinations_turbo(prompt, params["w"], params["h"])
    elif "Google" in motor: return gerar_imagem_google_imagen(prompt, params["ratio"])
    return gerar_imagem_pollinations_flux(prompt, params["w"], params["h"])

# =========================
# Helpers FFmpeg/System
# =========================
import shutil as _shutil
def shutil_which(bin_name: str) -> Optional[str]: return _shutil.which(bin_name)
def run_cmd(cmd: List[str]):
    try: subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e: raise RuntimeError(f"Comando falhou: {' '.join(cmd)}\nSTDERR: {e.stderr.decode('utf-8', errors='replace')}")

def get_audio_duration_seconds(path: str) -> Optional[float]:
    if not shutil_which("ffprobe"): return None
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path]
    try:
        p = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out = p.stdout.decode().strip()
        return float(out) if out else None
    except: return None

def resolve_font_path(font_choice: str, uploaded_font: Optional[BytesIO]) -> Optional[str]:
    if font_choice == "Upload Personalizada" and uploaded_font:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ttf") as tmp:
            tmp.write(uploaded_font.getvalue()); return tmp.name
    system_fonts = {
        "Padrão (Sans)": ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "arial.ttf"],
        "Serif": ["/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf", "times.ttf"],
        "Monospace": ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", "courier.ttf"]
    }
    candidates = system_fonts.get(font_choice, system_fonts["Padrão (Sans)"])
    for font in candidates:
        if os.path.exists(font): return font
    return None

def criar_preview_overlay(width: int, height: int, texts: List[Dict], global_upload: Optional[BytesIO], subtitle_preview: Dict = None) -> BytesIO:
    img = Image.new("RGB", (width, height), "black")
    draw = ImageDraw.Draw(img)
    
    # 1. Overlay (Cabeçalho)
    for item in texts:
        text = item.get("text", "")
        if not text: continue
        size = item.get("size", 30)
        y = item.get("y", 0)
        color = item.get("color", "white")
        font_style = item.get("font_style", "Padrão (Sans)")
        font_path = resolve_font_path(font_style, global_upload)
        try: font = ImageFont.truetype(font_path, size) if font_path and os.path.exists(font_path) else ImageFont.load_default()
        except: font = ImageFont.load_default()
        try: length = draw.textlength(text, font=font)
        except: length = len(text) * size * 0.5
        x = (width - length) / 2
        draw.text((x, y), text, fill=color, font=font)
    
    # 2. Legenda (Preview)
    if subtitle_preview and subtitle_preview.get("enabled"):
        text = "Exemplo de legenda do vídeo...\nQuebra de linha automática."
        size = subtitle_preview.get("size", 40)
        font_path = resolve_font_path(subtitle_preview.get("font", "Padrão (Sans)"), global_upload)
        color = subtitle_preview.get("color", "#FFFFFF")
        stroke_color = subtitle_preview.get("outline", "#000000")
        
        try: font = ImageFont.truetype(font_path, size) if font_path and os.path.exists(font_path) else ImageFont.load_default()
        except: font = ImageFont.load_default()
        
        margin = int(width * 0.1)
        lines = text.split("\n")
        total_h = len(lines) * (size + 5)
        y_pos = height - subtitle_preview.get("y", 100) - total_h
        
        for i, line in enumerate(lines):
            try: length = draw.textlength(line, font=font)
            except: length = len(line) * size * 0.5
            x = (width - length) / 2
            draw.text((x, y_pos + (i * (size + 5))), line, fill=color, font=font, stroke_width=2, stroke_fill=stroke_color)

    bio = BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    return bio

def get_text_alpha_expr(anim_type: str, duration: float) -> str:
    if anim_type == "Fade In": return f"alpha='min(1,t/1)'"
    elif anim_type == "Fade In/Out": return f"alpha='min(1,t/1)*min(1,({duration}-t)/1)'"
    else: return "alpha=1"

# =========================
# Interface principal
# =========================
st.markdown("<h3 style='text-align: center;'>Gerador de Evangelho</h3>", unsafe_allow_html=True)
st.markdown("---")

# ---- SIDEBAR CONFIG ----
st.sidebar.title("⚙️ Configurações")
motor_escolhido = st.sidebar.selectbox("🎨 Motor de Imagem", ["Pollinations Flux (Padrão)", "Pollinations Turbo", "Google Imagen"], index=0)
resolucao_escolhida = st.sidebar.selectbox("📏 Resolução do Vídeo", ["9:16 (Vertical/Stories)", "16:9 (Horizontal/YouTube)", "1:1 (Quadrado/Feed)"], index=0)
st.sidebar.markdown("---")
st.sidebar.markdown("### 🅰️ Fonte Global (Upload)")
font_choice = st.sidebar.selectbox("Estilo da Fonte Padrão", ["Padrão (Sans)", "Serif", "Monospace", "Upload Personalizada"], index=0)
uploaded_font_file = st.sidebar.file_uploader("Arquivo .ttf (para opção 'Upload Personalizada')", type=["ttf"])
st.sidebar.info(f"Modo: {motor_escolhido}\nFormato: {resolucao_escolhida}")

if "personagens_biblicos" not in st.session_state: st.session_state.personagens_biblicos = inicializar_personagens()
if "roteiro_gerado" not in st.session_state: st.session_state["roteiro_gerado"] = None
if "leitura_montada" not in st.session_state: st.session_state["leitura_montada"] = ""
if "generated_images_blocks" not in st.session_state: st.session_state["generated_images_blocks"] = {}
if "generated_audios_blocks" not in st.session_state: st.session_state["generated_audios_blocks"] = {}
if "video_final_bytes" not in st.session_state: st.session_state["video_final_bytes"] = None
if "meta_dados" not in st.session_state: st.session_state["meta_dados"] = {"data": "", "ref": ""}
if "overlay_settings" not in st.session_state: st.session_state["overlay_settings"] = load_config()

tab1, tab2, tab3, tab4, tab5 = st.tabs(["📖 Gerar Roteiro", "🎨 Personagens", "🎚️ Overlay & Legendas", "🎥 Fábrica Vídeo", "📊 Histórico"])

# --------- TAB 1: ROTEIRO ----------
with tab1:
    st.header("🚀 Gerador de Roteiro")
    col1, col2 = st.columns([2, 1])
    with col1: data_selecionada = st.date_input("📅 Data da liturgia:", value=date.today(), min_value=date(2023, 1, 1))
    with col2: st.info("Status: ✅ pronto para gerar")
    if st.button("🚀 Gerar Roteiro Completo", type="primary"):
        data_str = data_selecionada.strftime("%Y-%m-%d")
        data_display = data_selecionada.strftime("%d.%m.%Y")
        with st.status("📝 Gerando roteiro...", expanded=True) as status:
            st.write("🔍 Buscando Evangelho...")
            liturgia = obter_evangelho_com_fallback(data_str)
            if not liturgia: status.update(label="Falha ao buscar evangelho", state="error"); st.stop()
            ref_curta = formatar_referencia_curta(liturgia.get("ref_biblica"))
            st.session_state["meta_dados"] = {"data": data_display, "ref": ref_curta or "Evangelho do Dia"}
            st.write("🤖 Analisando personagens com IA...")
            personagens_detectados = analisar_personagens_groq(liturgia["texto"], st.session_state.personagens_biblicos)
            st.write("✨ Criando roteiro e prompts...")
            roteiro = gerar_roteiro_com_prompts_groq(liturgia["texto"], liturgia["referencia_liturgica"], {**st.session_state.personagens_biblicos, **personagens_detectados})
            if roteiro and roteiro.get("hook"):
                status.update(label="Roteiro gerado com sucesso!", state="complete", expanded=False)
                leitura_montada = montar_leitura_com_formula(liturgia["texto"], liturgia.get("ref_biblica"))
                st.session_state["roteiro_gerado"] = roteiro
                st.session_state["leitura_montada"] = leitura_montada
                st.rerun()
            else:
                status.update(label="Erro: Roteiro vazio ou incompleto.", state="error")
                st.error("A IA retornou um roteiro vazio. Tente novamente.")
                
    if st.session_state.get("roteiro_gerado"):
        roteiro = st.session_state["roteiro_gerado"]
        st.success("Roteiro gerado! Vá para 'Overlay & Legendas' para ajustar o visual.")
        c1, c2 = st.columns(2)
        with c1: st.markdown("### Hook"); st.caption(roteiro.get("hook", "Vazio"))
        with c2: st.markdown("### Reflexão"); st.caption(roteiro.get("reflexão", "Vazio"))

# --------- TAB 2: PERSONAGENS ----------
with tab2:
    st.header("🎨 Banco de Personagens")
    banco = st.session_state.personagens_biblicos.copy()
    col1, col2 = st.columns(2)
    with col1:
        for i, (nome, desc) in enumerate(banco.items()):
            with st.expander(f"✏️ {nome}"):
                nn = st.text_input(f"Nome", value=nome, key=f"n_{i}"); nd = st.text_area(f"Desc", value=desc, key=f"d_{i}")
                if st.button("Salvar", key=f"s_{i}"):
                    if nn != nome: del st.session_state.personagens_biblicos[nome]
                    st.session_state.personagens_biblicos[nn] = nd; st.rerun()
                if st.button("Apagar", key=f"a_{i}"): del st.session_state.personagens_biblicos[nome]; st.rerun()
    with col2:
        st.markdown("### ➕ Novo")
        nn = st.text_input("Nome", key="new_n"); nd = st.text_area("Descrição", key="new_d")
        if st.button("Adicionar") and nn and nd: st.session_state.personagens_biblicos[nn] = nd; st.rerun()

# --------- TAB 3: OVERLAY & LEGENDAS ----------
with tab3:
    st.header("🎚️ Editor Visual (Overlay & Legendas)")
    col_settings, col_preview = st.columns([1, 1])
    ov_sets = st.session_state["overlay_settings"]
    font_options = ["Padrão (Sans)", "Serif", "Monospace", "Upload Personalizada"]
    anim_options = ["Estático", "Fade In", "Fade In/Out"]
    
    with col_settings:
        with st.expander("📝 Legendas (Subtitles)", expanded=True):
            ov_sets["sub_enabled"] = st.toggle("Ativar Legendas", value=ov_sets.get("sub_enabled", False))
            if ov_sets["sub_enabled"]:
                c1, c2 = st.columns(2)
                with c1:
                    ov_sets["sub_color"] = st.color_picker("Cor Texto", ov_sets.get("sub_color", "#FFFFFF"))
                    ov_sets["sub_font"] = st.selectbox("Fonte Legenda", font_options, index=0)
                    ov_sets["sub_karaoke"] = st.checkbox("Efeito Karaoke (Wipe)", value=ov_sets.get("sub_karaoke", False))
                with c2:
                    ov_sets["sub_outline_color"] = st.color_picker("Cor Borda", ov_sets.get("sub_outline_color", "#000000"))
                    ov_sets["sub_size"] = st.slider("Tamanho", 20, 100, ov_sets.get("sub_size", 45))
                    ov_sets["sub_y"] = st.slider("Posição (do fundo)", 0, 500, ov_sets.get("sub_y", 100))
                
                ov_sets["sub_bg_box"] = st.checkbox("Fundo Escuro (Box)", value=ov_sets.get("sub_bg_box", False))

        with st.expander("✨ Efeitos de Vídeo", expanded=False):
            eo = ["Zoom In (Ken Burns)", "Zoom Out", "Panorâmica Esquerda", "Panorâmica Direita", "Estático (Sem movimento)"]
            ce = ov_sets.get("effect_type", eo[0])
            ov_sets["effect_type"] = st.selectbox("Movimento", eo, index=eo.index(ce) if ce in eo else 0)
            ov_sets["effect_speed"] = st.slider("Velocidade", 1, 10, ov_sets.get("effect_speed", 3))
            
            to = ["Fade (Escurecer)", "Corte Seco (Nenhuma)"]
            ct = ov_sets.get("trans_type", to[0])
            ov_sets["trans_type"] = st.selectbox("Transição", to, index=to.index(ct) if ct in to else 0)
            ov_sets["trans_dur"] = st.slider("Duração Transição (s)", 0.1, 2.0, ov_sets.get("trans_dur", 0.5))

        with st.expander("📑 Cabeçalho (Topo)", expanded=False):
            st.markdown("**Linha 1**"); ov_sets["line1_size"] = st.slider("Tam L1", 10, 100, ov_sets.get("line1_size", 40))
            ov_sets["line1_y"] = st.slider("Pos L1", 0, 800, ov_sets.get("line1_y", 40))
            st.markdown("**Linha 2**"); ov_sets["line2_size"] = st.slider("Tam L2", 10, 100, ov_sets.get("line2_size", 28))
            ov_sets["line2_y"] = st.slider("Pos L2", 0, 800, ov_sets.get("line2_y", 90))
            st.markdown("**Linha 3**"); ov_sets["line3_size"] = st.slider("Tam L3", 10, 100, ov_sets.get("line3_size", 24))
            ov_sets["line3_y"] = st.slider("Pos L3", 0, 800, ov_sets.get("line3_y", 130))

        st.session_state["overlay_settings"] = ov_sets
        if st.button("💾 Salvar Configurações"):
            if save_config(ov_sets): st.success("Salvo!")

    with col_preview:
        st.subheader("Pré-visualização")
        res_params = get_resolution_params(resolucao_escolhida)
        scale = 0.4
        pw = int(res_params["w"] * scale); ph = int(res_params["h"] * scale)
        meta = st.session_state.get("meta_dados", {})
        
        texts = [
            {"text": "EVANGELHO", "size": int(ov_sets["line1_size"] * scale), "y": int(ov_sets["line1_y"] * scale), "font_style": ov_sets.get("line1_font", "Padrão (Sans)"), "color": "white"},
            {"text": meta.get("data", "29.11.2025"), "size": int(ov_sets["line2_size"] * scale), "y": int(ov_sets["line2_y"] * scale), "font_style": ov_sets.get("line2_font", "Padrão (Sans)"), "color": "white"},
            {"text": meta.get("ref", "Lucas, Cap. 1"), "size": int(ov_sets["line3_size"] * scale), "y": int(ov_sets["line3_y"] * scale), "font_style": ov_sets.get("line3_font", "Padrão (Sans)"), "color": "white"},
        ]
        
        sub_preview = {
            "enabled": ov_sets["sub_enabled"],
            "size": int(ov_sets["sub_size"] * scale),
            "font": ov_sets["sub_font"],
            "color": ov_sets["sub_color"],
            "outline": ov_sets["sub_outline_color"],
            "y": int(ov_sets["sub_y"] * scale)
        }
        
        prev_img = criar_preview_overlay(pw, ph, texts, uploaded_font_file, sub_preview)
        st.image(prev_img, caption=f"Preview {resolucao_escolhida}", use_column_width=False)

# --------- TAB 4: FÁBRICA DE VÍDEO ----------
with tab4:
    st.header("🎥 Fábrica de Vídeo")
    if not st.session_state.get("roteiro_gerado"): st.warning("⚠️ Gere o roteiro na Aba 1 primeiro."); st.stop()
    roteiro = st.session_state["roteiro_gerado"]
    
    blocos_config = [
        {"id": "hook", "label": "🎣 HOOK", "prompt_key": "prompt_hook", "text_key": "hook"},
        {"id": "leitura", "label": "📖 LEITURA", "prompt_key": "prompt_leitura", "text_key": "leitura_montada"}, 
        {"id": "reflexão", "label": "💭 REFLEXÃO", "prompt_key": "prompt_reflexão", "text_key": "reflexão"},
        {"id": "aplicação", "label": "🌟 APLICAÇÃO", "prompt_key": "prompt_aplicacao", "text_key": "aplicação"},
        {"id": "oração", "label": "🙏 ORAÇÃO", "prompt_key": "prompt_oração", "text_key": "oração"},
        {"id": "thumbnail", "label": "🖼️ THUMBNAIL", "prompt_key": "prompt_geral", "text_key": None}
    ]
    st.info(f"⚙️ {motor_escolhido} | {resolucao_escolhida}")

    # Batch Actions
    cb1, cb2 = st.columns(2)
    with cb1:
        if st.button("🔊 Gerar Todos os Áudios", use_container_width=True):
            with st.status("Gerando áudios...", expanded=True) as s:
                for b in blocos_config:
                    if not b["text_key"]: continue
                    bid = b["id"]
                    txt = roteiro.get(b["text_key"]) if bid != "leitura" else st.session_state.get("leitura_montada", "")
                    if txt:
                        st.write(f"Gerando {b['label']}...")
                        try: st.session_state["generated_audios_blocks"][bid] = gerar_audio_gtts(txt)
                        except Exception as e: st.error(f"Erro {bid}: {e}")
                s.update(label="Áudios prontos!", state="complete"); st.rerun()
    with cb2:
        if st.button("✨ Gerar Todas as Imagens", use_container_width=True):
            with st.status("Gerando imagens...", expanded=True) as s:
                for b in blocos_config:
                    bid = b["id"]
                    pmt = roteiro.get(b["prompt_key"], "")
                    if pmt:
                        st.write(f"Criando {b['label']}...")
                        try: st.session_state["generated_images_blocks"][bid] = despachar_geracao_imagem(pmt, motor_escolhido, resolucao_escolhida)
                        except Exception as e: st.error(f"Erro {bid}: {e}")
                s.update(label="Imagens prontas!", state="complete"); st.rerun()

    st.divider()
    # Editor Individual (Simplificado para caber no limite)
    for b in blocos_config:
        bid = b["id"]
        with st.container(border=True):
            st.subheader(b["label"])
            c1, c2 = st.columns([1, 1.2])
            with c1:
                if b["text_key"]:
                    txt = roteiro.get(b["text_key"]) if bid != "leitura" else st.session_state.get("leitura_montada", "")
                    st.caption("Texto:"); st.markdown(f"_{txt[:100]}..._" if txt else "Vazio")
            with c2:
                img = st.session_state["generated_images_blocks"].get(bid)
                if img: st.image(img, width=150)
                else: st.info("Sem imagem")

    st.divider(); st.header("🎬 Finalização")
    usar_overlay = st.checkbox("Adicionar Overlay", value=True)
    
    st.subheader("🎵 Música")
    has_saved = os.path.exists(SAVED_MUSIC_FILE)
    if has_saved: st.success("Música Padrão Ativa"); st.audio(SAVED_MUSIC_FILE)
    mus_up = st.file_uploader("Upload Música", type=["mp3"])
    if mus_up and st.button("Salvar como Padrão"): save_music_file(mus_up.getvalue()); st.rerun()
    mus_vol = st.slider("Volume Música", 0.0, 1.0, load_config().get("music_vol", 0.15))

    if st.button("Renderizar Vídeo Final", type="primary"):
        with st.status("Renderizando...", expanded=True) as status:
            try:
                if not shutil_which("ffmpeg"): st.error("FFmpeg ausente"); st.stop()
                blocks = [b for b in blocos_config if b["id"] != "thumbnail"]
                font_p = resolve_font_path(font_choice, uploaded_font_file)
                
                # Configs
                sets = st.session_state["overlay_settings"]
                res = get_resolution_params(resolucao_escolhida)
                w, h = res["w"], res["h"]
                s_out = f"{w}x{h}"
                
                # Legendas Config
                sub_on = sets.get("sub_enabled", False)
                sub_font_p = resolve_font_path(sets.get("sub_font", "Padrão (Sans)"), uploaded_font_file)
                sub_size = sets.get("sub_size", 45)
                sub_col = sets.get("sub_color", "#FFFFFF")
                sub_out = sets.get("sub_outline_color", "#000000")
                sub_y = h - sets.get("sub_y", 100) # Inverter Y para FFmpeg (y=h-val)
                sub_karaoke = sets.get("sub_karaoke", False)
                sub_bg = sets.get("sub_bg_box", False)

                tmp = tempfile.mkdtemp(); clips = []
                map_t = {"hook": "EVANGELHO", "leitura": "EVANGELHO", "reflexão": "REFLEXÃO", "aplicação": "APLICAÇÃO", "oração": "ORAÇÃO"}
                meta = st.session_state.get("meta_dados", {})

                for b in blocks:
                    bid = b["id"]
                    im = st.session_state["generated_images_blocks"].get(bid)
                    au = st.session_state["generated_audios_blocks"].get(bid)
                    if not im or not au: continue
                    
                    p_im = os.path.join(tmp, f"{bid}.png"); p_au = os.path.join(tmp, f"{bid}.mp3"); p_out = os.path.join(tmp, f"{bid}.mp4")
                    im.seek(0); au.seek(0)
                    with open(p_im, "wb") as f: f.write(im.read())
                    with open(p_au, "wb") as f: f.write(au.read())
                    
                    dur = get_audio_duration_seconds(p_au) or 5.0
                    frames = int(dur * 25)
                    
                    # Filtros Base (Zoom)
                    spd = sets["effect_speed"] * 0.0005
                    typ = sets["effect_type"]
                    if typ == "Zoom In (Ken Burns)": z = f"z='min(zoom+{spd},1.5)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                    elif typ == "Zoom Out": z = f"z='max(1,1.5-{spd}*on)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                    elif typ == "Panorâmica Esquerda": z = f"z=1.2:x='min(x+{spd}*100,iw-iw/zoom)':y='(ih-ih/zoom)/2'"
                    elif typ == "Panorâmica Direita": z = f"z=1.2:x='max(0,x-{spd}*100)':y='(ih-ih/zoom)/2'"
                    else: z = "z=1:x=0:y=0"
                    
                    vf = [f"zoompan={z}:d={frames}:s={s_out}"]
                    
                    # Transição
                    if sets["trans_type"] == "Fade (Escurecer)":
                        td = sets["trans_dur"]
                        vf.append(f"fade=t=in:st=0:d={td},fade=t=out:st={dur-td}:d={td}")
                    
                    # Overlay Cabeçalho
                    if usar_overlay and font_p:
                        tit = map_t.get(bid, "EVANGELHO")
                        # Sanitize
                        t1, t2, t3 = sanitize_text_for_ffmpeg(tit), sanitize_text_for_ffmpeg(meta.get("data","")), sanitize_text_for_ffmpeg(meta.get("ref",""))
                        # Alphas
                        a1 = get_text_alpha_expr(sets.get("line1_anim", "Estático"), dur)
                        a2 = get_text_alpha_expr(sets.get("line2_anim", "Estático"), dur)
                        a3 = get_text_alpha_expr(sets.get("line3_anim", "Estático"), dur)
                        
                        vf.append(f"drawtext=fontfile='{font_p}':text='{t1}':fontcolor=white:fontsize={sets['line1_size']}:x=(w-text_w)/2:y={sets['line1_y']}:shadowcolor=black:shadowx=2:shadowy=2:{a1}")
                        vf.append(f"drawtext=fontfile='{font_p}':text='{t2}':fontcolor=white:fontsize={sets['line2_size']}:x=(w-text_w)/2:y={sets['line2_y']}:shadowcolor=black:shadowx=2:shadowy=2:{a2}")
                        vf.append(f"drawtext=fontfile='{font_p}':text='{t3}':fontcolor=white:fontsize={sets['line3_size']}:x=(w-text_w)/2:y={sets['line3_y']}:shadowcolor=black:shadowx=2:shadowy=2:{a3}")

                    # Legendas
                    if sub_on and sub_font_p:
                        # Obter texto do bloco e preparar
                        raw_text = roteiro.get(b["text_key"]) if bid != "leitura" else st.session_state.get("leitura_montada", "")
                        if raw_text:
                            # Quebrar texto para caber na largura (margem de 100px)
                            wrapped_text = wrap_text_ffmpeg(raw_text, sub_font_p, sub_size, w - 100)
                            safe_text = sanitize_text_for_ffmpeg(wrapped_text)
                            
                            # Opções de estilo
                            box_cmd = ":box=1:boxcolor=black@0.6:boxborderw=10" if sub_bg else ""
                            color_cmd = f"fontcolor={sub_col}"
                            
                            # Adicionar filtro
                            vf.append(f"drawtext=fontfile='{sub_font_p}':text='{safe_text}':fontsize={sub_size}:{color_cmd}:borderw=2:bordercolor={sub_out}:x=(w-text_w)/2:y={sub_y}{box_cmd}")

                    fc = ",".join(vf)
                    run_cmd(["ffmpeg", "-y", "-loop", "1", "-i", p_im, "-i", p_au, "-vf", fc, "-c:v", "libx264", "-t", f"{dur}", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", p_out])
                    clips.append(p_out)

                if clips:
                    list_txt = os.path.join(tmp, "l.txt")
                    with open(list_txt, "w") as f: 
                        for c in clips: f.write(f"file '{c}'\n")
                    
                    v_tmp = os.path.join(tmp, "v.mp4")
                    run_cmd(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_txt, "-c", "copy", v_tmp])
                    
                    final = os.path.join(tmp, "final.mp4")
                    mus = None
                    if mus_up: 
                        mus = os.path.join(tmp, "m.mp3"); 
                        with open(mus, "wb") as f: f.write(mus_up.getvalue())
                    elif has_saved: mus = SAVED_MUSIC_FILE
                    
                    if mus:
                        run_cmd(["ffmpeg", "-y", "-i", v_tmp, "-stream_loop", "-1", "-i", mus, "-filter_complex", f"[1:a]volume={mus_vol}[bg];[0:a][bg]amix=inputs=2:duration=first[a]", "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-shortest", final])
                    else: os.rename(v_tmp, final)
                    
                    with open(final, "rb") as f: st.session_state["video_final_bytes"] = BytesIO(f.read())
                    status.update(label="Pronto!", state="complete")
            
            except Exception as e: status.update(label="Erro!", state="error"); st.error(f"{e}")

    if st.session_state.get("video_final_bytes"):
        st.success("Vídeo Gerado!"); st.video(st.session_state["video_final_bytes"])
        st.download_button("⬇️ Baixar", st.session_state["video_final_bytes"], "video.mp4", "video/mp4")

with tab5: st.info("Histórico (Em breve)")
st.markdown("---"); st.caption("Studio Jhonata v20.0 - Legendas & Karaoke")