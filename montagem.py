import os
import re
import json
import time
import tempfile
import traceback
import subprocess
import urllib.parse
import random
import base64
import shutil as _shutil

# Imports de Tipagem
from io import BytesIO
from datetime import date, datetime
from typing import List, Optional, Tuple, Dict 

# Imports de Bibliotecas Externas
import requests
from PIL import Image, ImageDraw, ImageFont
import streamlit as st

# Force ffmpeg path for imageio if needed (Streamlit Cloud)
os.environ.setdefault("IMAGEIO_FFMPEG_EXE", "/usr/bin/ffmpeg")

# Arquivos de configuração persistentes
CONFIG_FILE = "overlay_config.json"
SAVED_MUSIC_FILE = "saved_bg_music.mp3"

# =========================
# VARIÁVEIS DO NOVO FLUXO 
# =========================
# URL do endpoint do Google Apps Script que gerencia o Drive (POST/PULL)
GAS_API_URL = "https://script.google.com/macros/s/AKfycbwA9SzkkbtlZBL5r5FU-UZG9-d8utaG554hgIQTTBXwBuypszl8W2MbepvoEGYja1_d9g/exec" 

# =========================
# Page config
# =========================
st.set_page_config(
    page_title="Studio Jhonata - Montagem",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =========================
# Persistência de Configurações e Arquivos (MANTIDA)
# =========================
def load_config():
    """Carrega configurações do disco ou retorna padrão"""
    default_settings = {
        "line1_y": 40, "line1_size": 40, "line1_font": "Padrão (Sans)", "line1_anim": "Estático",
        "line2_y": 90, "line2_size": 28, "line2_font": "Padrão (Sans)", "line2_anim": "Estático",
        "line3_y": 130, "line3_size": 24, "line3_font": "Padrão (Sans)", "line3_anim": "Estático",
        "effect_type": "Zoom In (Ken Burns)", "effect_speed": 3,
        "trans_type": "Fade (Escurecer)", "trans_dur": 0.5,
        "music_vol": 0.15,
    }
    
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                saved = json.load(f)
                
                for key in list(saved.keys()):
                    if key not in default_settings:
                        del saved[key]
                for key in default_settings:
                    if key not in saved:
                        saved[key] = default_settings[key]
                
                return saved
        except Exception as e:
            st.warning(f"Erro ao carregar configurações salvas: {e}")
    
    return default_settings

def save_config(settings):
    """Salva configurações no disco"""
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(settings, f, indent=4)
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
# FUNÇÕES DE COMUNICAÇÃO COM APPS SCRIPT/DRIVE
# (Removedora das funções de Geração/IA/Busca)
# =========================

def fetch_job_metadata(job_id: str) -> Optional[Dict]:
    """
    Solicita ao Apps Script os metadados do Job ID e lista de URLs de arquivos.
    """
    st.info(f"🌐 Solicitando metadados do Job ID: {job_id}...")
    
    try:
        response = requests.post(
            f"{GAS_API_URL}?action=fetch_job",
            json={"job_id": job_id},
            timeout=30
        )
        response.raise_for_status()
        data = response.json()
        
        if data.get("status") == "success":
            return data.get("payload")
        else:
            st.error(f"Erro ao buscar Job ID: {data.get('message', 'Resposta inválida do GAS.')}")
            return None
    except Exception as e:
        st.error(f"Erro de comunicação com o Apps Script: {e}")
        return None

def download_files_from_urls(urls_arquivos: List[Dict]) -> Tuple[Dict, Dict, Optional[BytesIO]]:
    """Baixa os arquivos de áudio, imagem e o SRT de URLs temporárias do Drive."""
    images = {}
    audios = {}
    srt_content = None
    st.info(f"⬇️ Baixando {len(urls_arquivos)} arquivos do Google Drive...")
    
    for item in urls_arquivos:
        url = item["url"]
        block_id = item["block_id"] 
        file_type = item["type"] 
        
        try:
            r = requests.get(url, timeout=60)
            r.raise_for_status()
            bio = BytesIO(r.content)
            bio.seek(0)

            if file_type == "image": 
                images[block_id] = bio
            elif file_type == "audio": 
                audios[block_id] = bio
            elif file_type == "srt":
                # Salva o SRT na memória para uso direto pelo FFmpeg
                srt_content = bio
            st.write(f"✅ Baixado: {block_id} ({file_type})")
        except Exception as e:
            st.error(f"❌ Falha ao baixar {block_id} ({file_type}): {e}")
            
    return images, audios, srt_content

def finalize_job_on_drive(job_id: str, video_bytes: BytesIO, metadata_description: str):
    """
    Envia o vídeo final e os metadados para o Apps Script para upload e limpeza.
    """
    st.info(f"⬆️ Finalizando Job {job_id} e limpando arquivos...")
    
    try:
        files = {
            'video_file': ('final_video.mp4', video_bytes, 'video/mp4'),
            'metadata_file': ('metadata.json', metadata_description.encode('utf-8'), 'application/json')
        }
        
        response = requests.post(
            f"{GAS_API_URL}?action=finalize_job&job_id={job_id}",
            files=files,
            timeout=120
        )
        response.raise_for_status()
        
        data = response.json()
        if data.get("status") == "success":
            st.success(f"Job {job_id} concluído com sucesso e arquivos temporários limpos no Drive!")
            st.markdown(f"**URL do Vídeo Final no Drive:** {data.get('final_url', 'N/A')}")
            return True
        else:
            st.error(f"Falha na finalização do Job no Drive: {data.get('message', 'Erro desconhecido.')}")
            return False
            
    except Exception as e:
        st.error(f"Erro ao finalizar Job no Apps Script: {e}")
        return False

# =========================
# FUNÇÕES DE ÁUDIO & IMAGEM (POLLINATIONS/gTTS - MANTIDAS APENAS PARA FALLBACK/RENDER)
# =========================

# NOTA: Estas funções não serão mais chamadas pelo fluxo principal da Tab 4, 
# mas são mantidas em caso de necessidade de re-renderizar assets.

def gerar_audio_gtts(texto: str) -> Optional[BytesIO]:
    if not texto or not texto.strip(): return None
    mp3_fp = BytesIO()
    try:
        from gtts import gTTS 
        tts = gTTS(text=texto, lang="pt", slow=False)
        tts.write_to_fp(mp3_fp)
        mp3_fp.seek(0)
        return mp3_fp
    except Exception as e:
        raise RuntimeError(f"Erro gTTS: {e}")

def despachar_geracao_audio(texto: str) -> Optional[BytesIO]:
    return gerar_audio_gtts(texto)

def get_resolution_params(choice: str) -> dict:
    if "9:16" in choice: return {"w": 720, "h": 1280, "ratio": "9:16"}
    elif "16:9" in choice: return {"w": 1280, "h": 720, "ratio": "16:9"}
    else: return {"w": 1024, "h": 1024, "ratio": "1:1"}

def gerar_imagem_pollinations_flux(prompt: str, width: int, height: int) -> BytesIO:
    prompt_clean = prompt.replace("\n", " ").strip()[:800]
    prompt_encoded = urllib.parse.quote(prompt_clean)
    seed = random.randint(0, 999999)
    url = f"https://image.pollinations.ai/prompt/{prompt_encoded}?model=flux&width={width}&height={height}&seed={seed}&nologo=true"
    r = requests.get(url, timeout=40)
    r.raise_for_status()
    bio = BytesIO(r.content); bio.seek(0); return bio

def gerar_imagem_pollinations_turbo(prompt: str, width: int, height: int) -> BytesIO:
    prompt_clean = prompt.replace("\n", " ").strip()[:800]
    prompt_encoded = urllib.parse.quote(prompt_clean)
    seed = random.randint(0, 999999)
    url = f"https://image.pollinations.ai/prompt/{prompt_encoded}?width={width}&height={height}&seed={seed}&nologo=true"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    bio = BytesIO(r.content); bio.seek(0); return bio

def despachar_geracao_imagem(prompt: str, motor: str, res_choice: str) -> BytesIO:
    params = get_resolution_params(res_choice)
    if motor == "Pollinations Turbo":
        return gerar_imagem_pollinations_turbo(prompt, params["w"], params["h"])
    else:
        return gerar_imagem_pollinations_flux(prompt, params["w"], params["h"])

# =========================
# Helpers e Utilitários (MANTIDOS)
# =========================

def shutil_which(bin_name: str) -> Optional[str]: return _shutil.which(bin_name)
def run_cmd(cmd: List[str]):
    try: subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e: raise RuntimeError(f"Comando falhou: {' '.join(cmd)}\nSTDERR: {e.stderr.decode('utf-8', errors='replace') if e.stderr else ''}")
def get_audio_duration_seconds(path: str) -> Optional[float]:
    if not shutil_which("ffprobe"): return None
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path]
    try:
        p = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out = p.stdout.decode().strip()
        return float(out) if out else None
    except Exception: return None

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
    if anim_type == "Fade In": return f"alpha='min(1,t/1)'"
    elif anim_type == "Fade In/Out": return f"alpha='min(1,t/1)*min(1,({duration}-t)/1)'"
    else: return "alpha=1"

def sanitize_text_for_ffmpeg(text: str) -> str:
    if not text: return ""
    t = text.replace(":", "\:").replace("'", "")
    return t

# =========================
# Interface principal
# =========================
st.title("✨ Studio Jhonata - Montagem de Vídeo")
st.markdown("---")

# ---- SIDEBAR CONFIG ----
st.sidebar.title("⚙️ Configurações")

# --- Opções de Fallback (Mantidas visíveis para edição de prompt, mas não geração principal)
image_motor_options = ["Pollinations Flux (Padrão)", "Pollinations Turbo"]
motor_escolhido = st.sidebar.selectbox("🎨 Motor de Imagem (Fallback)", image_motor_options, index=0)

resolucao_escolhida = st.sidebar.selectbox("📏 Resolução do Vídeo", ["9:16 (Vertical/Stories)", "16:9 (Horizontal/YouTube)", "1:1 (Quadrado/Feed)"], index=0)

st.sidebar.markdown("---")

# --- Motor TTS (Fallback) ---
st.sidebar.markdown("### 🗣️ Motor TTS (Fallback)")
st.sidebar.info("Modo de Voz: gTTS (Padrão - Gratuito)")
tts_motor_escolhido = "gTTS (Padrão)" # Valor fixo

st.sidebar.markdown("---")
st.sidebar.markdown("### 🅰️ Upload de Fonte (Global)")
uploaded_font_file = st.sidebar.file_uploader("Arquivo .ttf (para opção 'Upload Personalizada')", type=["ttf"])

# =========================
# SESSION STATE E ABAS
# =========================

# session state
if "roteiro_gerado" not in st.session_state: st.session_state["roteiro_gerado"] = None
if "leitura_montada" not in st.session_state: st.session_state["leitura_montada"] = ""
if "generated_images_blocks" not in st.session_state: st.session_state["generated_images_blocks"] = {}
if "generated_audios_blocks" not in st.session_state: st.session_state["generated_audios_blocks"] = {}
if "video_final_bytes" not in st.session_state: st.session_state["video_final_bytes"] = None
if "meta_dados" not in st.session_state: st.session_state["meta_dados"] = {"data": "", "ref": ""}
if "job_id_ativo" not in st.session_state: st.session_state["job_id_ativo"] = None 
if "srt_content_bio" not in st.session_state: st.session_state["srt_content_bio"] = None # Novo estado para SRT

# Carregar Settings persistentes
if "overlay_settings" not in st.session_state:
    st.session_state["overlay_settings"] = load_config()

# REMOVIDAS TABAS 1 (ROTEIRO) E 2 (PERSONAGENS)
tab_ov, tab_fab, tab_hist = st.tabs(
    ["🎚️ Overlay & Efeitos", "🎥 Fábrica Vídeo (Montagem)", "📊 Histórico"]
)

# --------- TAB 1 (nova 1): OVERLAY & EFEITOS ----------
with tab_ov:
    st.header("🎚️ Editor de Overlay & Efeitos")
    
    col_settings, col_preview = st.columns([1, 1])
    ov_sets = st.session_state["overlay_settings"]
    font_options = ["Padrão (Sans)", "Serif", "Monospace", "Upload Personalizada"]
    anim_options = ["Estático", "Fade In", "Fade In/Out"]
    
    # ... (Lógica de configuração do Overlay e Preview permanece inalterada) ...
    with col_settings:
        with st.expander("✨ Efeitos Visuais (Movimento)", expanded=True):
            effect_opts = ["Zoom In (Ken Burns)", "Zoom Out", "Panorâmica Esquerda", "Panorâmica Direita", "Estático (Sem movimento)"]
            curr_eff = ov_sets.get("effect_type", effect_opts[0]); ov_sets["effect_type"] = st.selectbox("Tipo de Movimento", effect_opts, index=effect_opts.index(curr_eff))
            ov_sets["effect_speed"] = st.slider("Intensidade do Movimento", 1, 10, ov_sets.get("effect_speed", 3), help="1 = Muito Lento, 10 = Rápido")

        with st.expander("🎬 Transições de Cena", expanded=True):
            trans_opts = ["Fade (Escurecer)", "Corte Seco (Nenhuma)"]
            curr_trans = ov_sets.get("trans_type", trans_opts[0]); ov_sets["trans_type"] = st.selectbox("Tipo de Transição", trans_opts, index=trans_opts.index(curr_trans))
            ov_sets["trans_dur"] = st.slider("Duração da Transição (s)", 0.1, 2.0, ov_sets.get("trans_dur", 0.5), 0.1)

        with st.expander("📝 Texto Overlay (Cabeçalho)", expanded=True):
            st.markdown("**Linha 1: Título**")
            curr_f1 = ov_sets.get("line1_font", font_options[0]); ov_sets["line1_font"] = st.selectbox("Fonte L1", font_options, index=font_options.index(curr_f1), key="f1")
            ov_sets["line1_size"] = st.slider("Tamanho L1", 10, 150, ov_sets.get("line1_size", 40), key="s1")
            ov_sets["line1_y"] = st.slider("Posição Y L1", 0, 800, ov_sets.get("line1_y", 40), key="y1")
            curr_a1 = ov_sets.get("line1_anim", anim_options[0]); ov_sets["line1_anim"] = st.selectbox("Animação L1", anim_options, index=anim_options.index(curr_a1), key="a1")
            
            st.markdown("---"); st.markdown("**Linha 2: Data**")
            curr_f2 = ov_sets.get("line2_font", font_options[0]); ov_sets["line2_font"] = st.selectbox("Fonte L2", font_options, index=font_options.index(curr_f2), key="f2")
            ov_sets["line2_size"] = st.slider("Tamanho L2", 10, 150, ov_sets.get("line2_size", 28), key="s2")
            ov_sets["line2_y"] = st.slider("Posição Y L2", 0, 800, ov_sets.get("line2_y", 90), key="y2")
            curr_a2 = ov_sets.get("line2_anim", anim_options[0]); ov_sets["line2_anim"] = st.selectbox("Animação L2", anim_options, index=anim_options.index(curr_a2), key="a2")

            st.markdown("---"); st.markdown("**Linha 3: Referência**")
            curr_f3 = ov_sets.get("line3_font", font_options[0]); ov_sets["line3_font"] = st.selectbox("Fonte L3", font_options, index=font_options.index(curr_f3), key="f3")
            ov_sets["line3_size"] = st.slider("Tamanho L3", 10, 150, ov_sets.get("line3_size", 24), key="s3")
            ov_sets["line3_y"] = st.slider("Posição Y L3", 0, 800, ov_sets.get("line3_y", 130), key="y3")
            curr_a3 = ov_sets.get("line3_anim", anim_options[0]); ov_sets["line3_anim"] = st.selectbox("Animação L3", anim_options, index=anim_options.index(curr_a3), key="a3")

        st.session_state["overlay_settings"] = ov_sets
        if st.button("💾 Salvar Configurações (Persistente)", key="save_ov_config"):
            if save_config(ov_sets): st.success("Configuração salva no disco com sucesso!")

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


# --------- TAB 2 (nova 2): FÁBRICA DE VÍDEO ----------
with tab_fab:
    st.header("🎥 Fábrica de Vídeo (Montagem)")
    
    # === BLOCO 1: CARREGAMENTO DO JOB ID ===
    st.subheader("🌐 Carregamento de Assets do Drive")
    st.info("O Google AI Studio deve ter disparado um Job para o Drive antes de carregá-lo aqui.")
    
    default_job_id = st.session_state.get("job_id_ativo") if st.session_state.get("job_id_ativo") else ""
    job_id_input = st.text_input("Insira o JOB ID (Nome da Pasta do Drive):", value=default_job_id, key="job_id_input", help="O ID da pasta criada pelo seu script no Apps Script.")
    
    if st.button("📥 Carregar Assets & Roteiro do Job", type="primary"):
        if job_id_input:
            with st.status(f"Carregando Job {job_id_input}...", expanded=True) as status:
                st.session_state["job_id_ativo"] = job_id_input 
                
                # 1. Busca metadados (inclui o roteiro)
                job_data = fetch_job_metadata(job_id_input)
                if job_data:
                    # Carrega o roteiro
                    st.session_state["roteiro_gerado"] = job_data.get("roteiro")
                    st.session_state["leitura_montada"] = job_data.get("leitura_montada", "")
                    st.session_state["meta_dados"] = job_data.get("meta_dados", {})

                    # 2. Baixa arquivos (Imagens, Áudios, SRT)
                    urls_arquivos = job_data.get("urls_arquivos", [])
                    images, audios, srt_content = download_files_from_urls(urls_arquivos)
                    
                    st.session_state["generated_images_blocks"] = images
                    st.session_state["generated_audios_blocks"] = audios
                    st.session_state["srt_content_bio"] = srt_content
                    
                    if not srt_content: st.warning("SRT (legendas) não encontrado no Job.")
                    if len(images) < 4 or len(audios) < 4: st.warning(f"Apenas {len(images)} imagens e {len(audios)} áudios carregados. Recomenda-se 4 de cada.")
                    
                    status.update(label=f"Job {job_id_input} carregado com sucesso!", state="complete")
                    st.rerun()
                else:
                    st.session_state["job_id_ativo"] = None 
                    status.update(label=f"Falha ao carregar Job {job_id_input}.", state="error")
        else:
            st.warning("Por favor, insira um Job ID.")

    st.markdown("---")
    
    if not st.session_state.get("roteiro_gerado"):
        st.info("⚠️ Carregue um Job ID acima para visualizar os assets e renderizar o vídeo.")
        st.stop()
    
    # === BLOCO 2: VISUALIZAÇÃO E FALLBACK ===
    st.subheader("Assets Carregados")
    st.success(f"Job Ativo: **{st.session_state['job_id_ativo']}**")
    
    if st.session_state.get("srt_content_bio"):
        st.markdown(f"**Legendas (SRT) Carregadas:** {st.session_state['srt_content_bio'].getbuffer().nbytes} bytes.")
    
    roteiro = st.session_state["roteiro_gerado"]
    blocos_config = [
        {"id": "hook", "label": "🎣 HOOK", "prompt_key": "prompt_hook", "text_key": "hook"},
        {"id": "leitura", "label": "📖 LEITURA", "prompt_key": "prompt_leitura", "text_key": "leitura_montada"}, 
        {"id": "reflexão", "label": "💭 REFLEXÃO", "prompt_key": "prompt_reflexão", "text_key": "reflexão"},
        {"id": "aplicação", "label": "🌟 APLICAÇÃO", "prompt_key": "prompt_aplicacao", "text_key": "aplicação"},
        {"id": "oração", "label": "🙏 ORAÇÃO", "prompt_key": "prompt_oração", "text_key": "oração"},
        {"id": "thumbnail", "label": "🖼️ THUMBNAIL", "prompt_key": "prompt_geral", "text_key": None}
    ]

    # Visualização dos assets (Com fallback de geração manual)
    for bloco in blocos_config:
        block_id = bloco["id"]
        with st.container(border=True):
            st.subheader(bloco["label"])
            col_text, col_media = st.columns([1, 1.2])
            with col_text:
                if bloco["text_key"]:
                    txt_content = roteiro.get(bloco["text_key"]) if block_id != "leitura" else st.session_state.get("leitura_montada", "")
                    st.caption("📜 Texto para Narração (Do Roteiro):")
                    st.markdown(f"_{txt_content[:250]}..._" if txt_content else "_Sem texto_")
                    
                    # Botão FALLBACK ÁUDIO (gTTS)
                    if st.button(f"🔊 Gerar Áudio (Fallback gTTS) - {block_id}", key=f"btn_audio_fallback_{block_id}"):
                        if txt_content:
                            try:
                                audio = despachar_geracao_audio(txt_content)
                                st.session_state["generated_audios_blocks"][bid] = audio
                                st.rerun()
                            except Exception as e:
                                st.error(f"Erro gTTS: {e}")
                                
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
                    
                # Botão FALLBACK IMAGEM (Pollinations)
                if st.button(f"✨ Gerar Imagem (Fallback Pollinations) - {block_id}", key=f"btn_gen_fallback_{block_id}"):
                    if prompt_content:
                        with st.spinner("Criando (Pollinations)..."):
                            try:
                                img = despachar_geracao_imagem(prompt_content, motor_escolhido, resolucao_escolhida)
                                st.session_state["generated_images_blocks"][block_id] = img
                                st.success("Gerada!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Erro Pollinations: {e}")


    st.divider()
    
    # === BLOCO 3: RENDERIZAÇÃO FINAL ===
    
    st.header("🎬 Renderização e Finalização")
    usar_overlay = st.checkbox("Adicionar Cabeçalho (Overlay Personalizado)", value=True)
    usar_legendas = st.checkbox("Adicionar Legendas (SRT) ao Vídeo", value=True, disabled=(st.session_state.get("srt_content_bio") is None))
    
    if st.session_state.get("srt_content_bio") is None and usar_legendas:
        st.warning("O arquivo SRT não foi carregado para este Job. Desmarque a opção ou carregue um Job com legendas.")

    st.subheader("🎵 Música de Fundo (Opcional)")
    music_upload = st.file_uploader("Upload Música (MP3)", type=["mp3"])
    music_vol = st.slider("Volume da Música (em relação à voz)", 0.0, 1.0, load_config().get("music_vol", 0.15))

    if st.button("Renderizar Vídeo Completo (Unir tudo)", type="primary"):
        
        if usar_legendas and st.session_state.get("srt_content_bio") is None:
            st.error("ERRO: As legendas foram selecionadas, mas o arquivo SRT não está carregado.")
            st.stop()
            
        with st.status("Renderizando vídeo com efeitos e legendas...", expanded=True) as status:
            try:
                blocos_relevantes = [b for b in blocos_config if b["id"] != "thumbnail"]
                if not shutil_which("ffmpeg"): status.update(label="FFmpeg não encontrado!", state="error"); st.stop()
                
                temp_dir = tempfile.mkdtemp()
                clip_files = []
                srt_path = None

                # 1. SALVAR SRT PARA USO DO FFmpeg (Se selecionado)
                if usar_legendas and st.session_state.get("srt_content_bio"):
                    srt_path = os.path.join(temp_dir, "legendas.srt")
                    st.session_state["srt_content_bio"].seek(0)
                    with open(srt_path, "wb") as f: 
                        f.write(st.session_state["srt_content_bio"].read())
                    status.write("SRT salvo para uso.")


                # 2. RENDERIZAR CADA CLIPE
                meta = st.session_state.get("meta_dados", {})
                txt_dt = meta.get("data", ""); txt_ref = meta.get("ref", "")
                map_titulos = {"hook": "EVANGELHO", "leitura": "EVANGELHO", "reflexão": "REFLEXÃO", "aplicação": "APLICAÇÃO", "oração": "ORAÇÃO"}
                res_params = get_resolution_params(resolucao_escolhida); s_out = f"{res_params['w']}x{res_params['h']}"
                sets = st.session_state["overlay_settings"]; speed_val = sets["effect_speed"] * 0.0005 

                if sets["effect_type"] == "Zoom In (Ken Burns)": zoom_expr = f"z='min(zoom+{speed_val},1.5)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                elif sets["effect_type"] == "Zoom Out": zoom_expr = f"z='max(1,1.5-{speed_val}*on)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                elif sets["effect_type"] == "Panorâmica Esquerda": zoom_expr = f"z=1.2:x='min(x+{speed_val}*100,iw-iw/zoom)':y='(ih-ih/zoom)/2'"
                elif sets["effect_type"] == "Panorâmica Direita": zoom_expr = f"z=1.2:x='max(0,x-{speed_val}*100)':y='(ih-ih/zoom)/2'"
                else: zoom_expr = "z=1:x=0:y=0" 

                for b in blocos_relevantes:
                    bid = b["id"]
                    img_bio = st.session_state["generated_images_blocks"].get(bid)
                    audio_bio = st.session_state["generated_audios_blocks"].get(bid)
                    if not img_bio or not audio_bio: continue
                        
                    status.write(f"Processando clipe: {bid}...")
                    img_path = os.path.join(temp_dir, f"{bid}.png")
                    audio_path = os.path.join(temp_dir, f"{bid}.mp3")
                    clip_path = os.path.join(temp_dir, f"{bid}.mp4")
                    
                    img_bio.seek(0); audio_bio.seek(0)
                    with open(img_path, "wb") as f: f.write(img_bio.read())
                    with open(audio_path, "wb") as f: f.write(audio_bio.read())
                    
                    dur = get_audio_duration_seconds(audio_path) or 5.0
                    frames = int(dur * 25)

                    vf_filters = []
                    if sets["effect_type"] != "Estático (Sem movimento)": vf_filters.append(f"zoompan={zoom_expr}:d={frames}:s={s_out}")
                    else: vf_filters.append(f"scale={s_out}")

                    if sets["trans_type"] == "Fade (Escurecer)":
                        td = sets["trans_dur"]; vf_filters.append(f"fade=t=in:st=0:d={td},fade=t=out:st={dur-td}:d={td}")

                    if usar_overlay:
                        # ... (lógica de overlay drawtext permanece a mesma) ...
                        titulo_atual = map_titulos.get(bid, "EVANGELHO")
                        f1_path = resolve_font_path(sets["line1_font"], uploaded_font_file)
                        f2_path = resolve_font_path(sets["line2_font"], uploaded_font_file)
                        f3_path = resolve_font_path(sets["line3_font"], uploaded_font_file)
                        alp1 = get_text_alpha_expr(sets.get("line1_anim", "Estático"), dur)
                        alp2 = get_text_alpha_expr(sets.get("line2_anim", "Estático"), dur)
                        alp3 = get_text_alpha_expr(sets.get("line3_anim", "Estático"), dur)
                        clean_t1 = sanitize_text_for_ffmpeg(titulo_atual); clean_t2 = sanitize_text_for_ffmpeg(txt_dt); clean_t3 = sanitize_text_for_ffmpeg(txt_ref)
                        if f1_path: vf_filters.append(f"drawtext=fontfile='{f1_path}':text='{clean_t1}':fontcolor=white:fontsize={sets['line1_size']}:x=(w-text_w)/2:y={sets['line1_y']}:shadowcolor=black:shadowx=2:shadowy=2:{alp1}")
                        if f2_path: vf_filters.append(f"drawtext=fontfile='{f2_path}':text='{clean_t2}':fontcolor=white:fontsize={sets['line2_size']}:x=(w-text_w)/2:y={sets['line2_y']}:shadowcolor=black:shadowx=2:shadowy=2:{alp2}")
                        if f3_path: vf_filters.append(f"drawtext=fontfile='{f3_path}':text='{clean_t3}':fontcolor=white:fontsize={sets['line3_size']}:x=(w-text_w)/2:y={sets['line3_y']}:shadowcolor=black:shadowx=2:shadowy=2:{alp3}")

                    filter_complex = ",".join(vf_filters)
                    
                    cmd = ["ffmpeg", "-y", "-loop", "1", "-i", img_path, "-i", audio_path, "-vf", filter_complex, "-c:v", "libx264", "-t", f"{dur}", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", clip_path]
                    run_cmd(cmd)
                    clip_files.append(clip_path)
                
                if clip_files:
                    # 3. CONCATENAR CLIPES
                    concat_list = os.path.join(temp_dir, "list.txt")
                    with open(concat_list, "w") as f:
                        for p in clip_files: f.write(f"file '{p}'\n")
                    temp_video = os.path.join(temp_dir, "temp_video.mp4")
                    run_cmd(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list, "-c", "copy", temp_video])
                    
                    # 4. APLICAR MÚSICA DE FUNDO E LEGENDAS (FINALIZAR)
                    final_path_no_srt = os.path.join(temp_dir, "video_sem_srt.mp4")
                    final_path = os.path.join(temp_dir, "final.mp4")
                    
                    # --- APLICAR MÚSICA DE FUNDO (Primeiro passo de pós-processamento) ---
                    music_source_path = music_upload and os.path.join(temp_dir, "bg.mp3")
                    if music_upload: with open(music_source_path, "wb") as f: f.write(music_upload.getvalue())
                    elif os.path.exists(SAVED_MUSIC_FILE): music_source_path = SAVED_MUSIC_FILE
                        
                    if music_source_path:
                        cmd_mix = [
                            "ffmpeg", "-y", "-i", temp_video, "-stream_loop", "-1", "-i", music_source_path,
                            "-filter_complex", f"[1:a]volume={music_vol}[bg];[0:a][bg]amix=inputs=2:duration=first:dropout_transition=2[a]",
                            "-map", "0:v", "-map", "[a]",
                            "-c:v", "copy", "-c:a", "aac", "-shortest",
                            final_path_no_srt
                        ]
                        run_cmd(cmd_mix)
                    else:
                        os.rename(temp_video, final_path_no_srt) # Se não tem música, renomeia o temp_video
                        
                    # --- APLICAR LEGENDAS (Segundo passo de pós-processamento) ---
                    if usar_legendas and srt_path:
                        # CRÍTICO: Usar o filtro 'subtitles' com fonte e cor
                        status.write("Aplicando legendas (SRT)...")
                        # Cor e Tamanho da legenda (ex: Amarelo, 36px, fundo semi-transparente)
                        # Assumindo que a fonte padrão DejavuSans-Bold.ttf está no sistema
                        font_srt = resolve_font_path("Padrão (Sans)", None)
                        
                        cmd_srt = [
                            "ffmpeg", "-y", "-i", final_path_no_srt, 
                            "-vf", f"subtitles='{srt_path}':force_style='Fontname={font_srt.replace(':', '\\:')},FontSize=36,PrimaryColour=&H0000FFFF,BorderStyle=3,BackColour=&H60000000,OutlineColour=&H00000000'",
                            "-c:a", "copy", final_path
                        ]
                        run_cmd(cmd_srt)
                    else:
                        os.rename(final_path_no_srt, final_path) # Se não tem legenda, renomeia o temp_video

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
            
    # --- NOVO FLUXO DE FINALIZAÇÃO (PÓS-RENDERIZAÇÃO) ---
    if st.session_state.get("video_final_bytes") and st.session_state.get("job_id_ativo"):
        job_id = st.session_state["job_id_ativo"]
        
        st.header("Upload e Finalização Automática")
        
        roteiro = st.session_state["roteiro_gerado"]
        meta_data_json = json.dumps({
            "job_id": job_id,
            "titulo_sugerido": "Evangelho do Dia",
            "descricao_completa": roteiro.get("hook", "") + "\n\n" + roteiro.get("reflexão", "") + "\n\n" + roteiro.get("aplicação", "") + "\n\n" + roteiro.get("oração", "")
        }, indent=4)
        
        st.code(meta_data_json, language="json", caption="Metadados Gerados (Descrição para Redes)")
        
        if st.button(f"🚀 Upload Finalizar & Limpar Drive ({job_id})", type="primary"):
            video_bytes = st.session_state["video_final_bytes"]
            
            if finalize_job_on_drive(job_id, video_bytes, meta_data_json):
                st.session_state["job_id_ativo"] = None
                st.session_state["video_final_bytes"] = None
                st.rerun()

    if st.session_state.get("video_final_bytes") and not st.session_state.get("job_id_ativo"):
        st.download_button("⬇️ Baixar MP4", st.session_state["video_final_bytes"], "video_jhonata.mp4", "video/mp4")

# --------- TAB 3 (nova 3): HISTÓRICO ----------
with tab_hist:
    st.info("Histórico em desenvolvimento.")