# pages/4_🎬_Editor_Legendas.py - Editor de Legendas Avançado (Pós-Produção) - CORRIGIDO
import os
import re
import json
import time
import tempfile
import subprocess
import base64
import shutil
from io import BytesIO
from datetime import datetime
from typing import List, Optional, Dict, Any

import requests
import streamlit as st
from PIL import Image, ImageDraw, ImageFont

# --- Imports de IA ---
try:
    import whisper
except ImportError:
    whisper = None

# --- API Imports ---
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# --- CONFIGURAÇÃO ---
# URL do Script GAS para interação com Drive (mesma do app principal)
# Substitua pela sua URL correta se for diferente
GAS_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbx5DZ52ohxKPl6Lh0DnkhHJejuPBx1Ud6B10Ag_xfnJVzGpE83n7gHdUHnk4yAgrpuidw/exec"
MONETIZA_DRIVE_FOLDER_VIDEOS = "Monetiza_Studio_Videos_Finais" # Pasta onde videos sem legenda estao
# Opcional: Pasta de destino para vídeos legendados (se quiser separar)
MONETIZA_DRIVE_FOLDER_LEGENDADOS = "Monetiza_Studio_Videos_Legendados" 

os.environ.setdefault("IMAGEIO_FFMPEG_EXE", "/usr/bin/ffmpeg")

# =========================
# Page Config
# =========================
st.set_page_config(
    page_title="Editor de Legendas Pro",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =========================
# Utils & Helpers
# =========================
def shutil_which(name): return shutil.which(name)

def run_cmd(cmd):
    """Executa comandos de shell (FFmpeg)"""
    clean = [arg.replace('\u00a0', ' ').strip() if isinstance(arg, str) else arg for arg in cmd if arg]
    try:
        subprocess.run(clean, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        st.error(f"Erro FFmpeg: {e.stderr.decode()}")
        raise e

def format_timestamp(seconds):
    """Formata segundos para SRT (00:00:00,000)"""
    millis = int((seconds - int(seconds)) * 1000)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"

def hex_to_ass_color(hex_color):
    """Converte HEX (#RRGGBB) para formato ASS (&HBBGGRR&)"""
    h = hex_color.lstrip('#')
    if len(h) != 6: return "&HFFFFFF&"
    # Inverte RGB para BGR
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}"

# =========================
# Google Drive Service (CORRIGIDO COM BASE NO MONTAGEM.PY)
# =========================
_drive_service = None

def get_drive_service():
    global _drive_service
    # Lista exata de chaves que você usa no montagem.py
    required_keys = [
        "type", "project_id", "private_key_id", "private_key", 
        "client_email", "client_id", "auth_uri", "token_uri", 
        "auth_provider_x509_cert_url", "client_x509_cert_url", "universe_domain"
    ]
    # Prefixo usado no seu secrets.toml
    prefix = "gcp_service_account_"

    if _drive_service is None:
        try:
            creds_info = {}
            missing_keys = []
            for key in required_keys:
                # Busca com o prefixo correto
                secret_key = prefix + key
                val = st.secrets.get(secret_key)
                
                if val is None: 
                    # Tenta buscar sem prefixo como fallback
                    val = st.secrets.get(key)
                
                if val is None:
                    missing_keys.append(secret_key)
                else:
                    creds_info[key] = val
            
            if missing_keys:
                st.error(f"Faltam chaves no secrets (verifique o prefixo '{prefix}'): {', '.join(missing_keys)}")
                st.stop()

            creds = service_account.Credentials.from_service_account_info(
                creds_info, scopes=['https://www.googleapis.com/auth/drive.readonly']
            )
            _drive_service = build('drive', 'v3', credentials=creds)
        except Exception as e:
            st.error(f"Erro ao conectar Drive: {e}")
            st.stop()
    return _drive_service

def list_videos_ready():
    """Lista vídeos prontos para legendagem na pasta especificada."""
    service = get_drive_service()
    videos = []
    try:
        # 1. Busca pasta de origem
        q_f = f"name = '{MONETIZA_DRIVE_FOLDER_VIDEOS}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        folders = service.files().list(q=q_f, fields="files(id)").execute().get('files', [])
        
        if not folders: 
            st.warning(f"Pasta '{MONETIZA_DRIVE_FOLDER_VIDEOS}' não encontrada. Certifique-se de ter gerado vídeos no Montagem.")
            return []
            
        folder_id = folders[0]['id']

        # 2. Lista arquivos MP4
        q_v = f"mimeType = 'video/mp4' and '{folder_id}' in parents and trashed = false"
        # Pega nome, ID e descrição (onde guardamos metadados)
        files = service.files().list(q=q_v, orderBy="createdTime desc", pageSize=20, fields="files(id, name, description, createdTime)").execute().get('files', [])
        
        for f in files:
            videos.append(f)
            
    except Exception as e:
        st.error(f"Erro ao listar vídeos: {e}")
    return videos

def download_video(file_id, filename):
    service = get_drive_service()
    request = service.files().get_media(fileId=file_id)
    with open(filename, "wb") as f:
        f.write(request.execute())
    return filename

# =========================
# Whisper Transcription
# =========================
def transcribe_audio(video_path, model_size="tiny"):
    """Extrai áudio e transcreve com Whisper local"""
    if whisper is None:
        st.error("Biblioteca 'whisper' não instalada. Adicione 'openai-whisper' ao requirements.txt")
        return None, None
        
    try:
        # Extrai áudio temporário
        audio_path = "temp_audio.wav"
        run_cmd(["ffmpeg", "-y", "-i", video_path, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", audio_path])
        
        # Carrega modelo (força CPU para evitar erros de GPU no Streamlit Cloud)
        st.info(f"Carregando modelo Whisper ({model_size})...")
        model = whisper.load_model(model_size, device="cpu")
        
        # Transcreve
        st.info("Transcrevendo...")
        result = model.transcribe(audio_path, language="pt")
        
        segments = result['segments']
        srt_content = ""
        for i, seg in enumerate(segments):
            start = format_timestamp(seg['start'])
            end = format_timestamp(seg['end'])
            text = seg['text'].strip()
            srt_content += f"{i+1}\n{start} --> {end}\n{text}\n\n"
            
        if os.path.exists(audio_path):
            os.remove(audio_path)
            
        return srt_content, segments
    except Exception as e:
        st.error(f"Erro Transcrição: {e}")
        return None, None

# =========================
# Upload Final (GAS)
# =========================
def upload_legendado_to_gas(video_path, original_name):
    """Envia vídeo legendado para o Drive via GAS"""
    try:
        with open(video_path, "rb") as f:
            video_bytes = f.read()
            
        video_b64 = base64.b64encode(video_bytes).decode('utf-8')
        
        payload = {
            "action": "upload_video",
            "job_id": "LEGENDADO_" + str(int(time.time())), # ID único
            "video_data": video_b64,
            "filename": f"LEGENDADO_{original_name}",
            "meta_data": {
                "status": "LEGENDADO",
                "processed_at": datetime.now().isoformat()
            }
        }
        
        response = requests.post(GAS_SCRIPT_URL, json=payload, timeout=300) # Timeout maior para upload
        
        if response.status_code == 200:
            res = response.json()
            if res.get("status") == "success":
                return True, res.get("file_id")
            else:
                return False, res.get("message")
        return False, f"HTTP {response.status_code}"
        
    except Exception as e:
        return False, str(e)

# =========================
# Interface Principal
# =========================
def main():
    st.title("🎬 Editor de Legendas Pro")
    st.caption("Pós-produção: Adicione legendas a vídeos prontos")
    
    # State
    if "current_video_path" not in st.session_state: st.session_state.current_video_path = None
    if "srt_content" not in st.session_state: st.session_state.srt_content = ""
    if "video_id" not in st.session_state: st.session_state.video_id = None
    if "video_name" not in st.session_state: st.session_state.video_name = ""
    if "final_video_path" not in st.session_state: st.session_state.final_video_path = None

    # --- Sidebar: Seleção de Vídeo ---
    st.sidebar.header("📁 Vídeos Disponíveis")
    
    if st.sidebar.button("🔄 Atualizar Lista"):
        st.rerun()
        
    videos = list_videos_ready()
    
    if not videos:
        st.sidebar.info("Nenhum vídeo encontrado na pasta 'Monetiza_Studio_Videos_Finais'.")
    
    video_opts = {v['name']: v['id'] for v in videos}
    selected_video_name = st.sidebar.selectbox(
        "Escolha um vídeo:", 
        options=["Selecione..."] + list(video_opts.keys()),
        index=0
    )
    
    if st.sidebar.button("⬇️ Carregar Vídeo") and selected_video_name != "Selecione...":
        vid_id = video_opts[selected_video_name]
        with st.status("Baixando vídeo...", expanded=True) as status:
            # Limpa anteriores
            if st.session_state.current_video_path and os.path.exists(st.session_state.current_video_path):
                try: os.remove(st.session_state.current_video_path)
                except: pass
            if st.session_state.final_video_path and os.path.exists(st.session_state.final_video_path):
                try: os.remove(st.session_state.final_video_path)
                except: pass
                
            local_path = f"temp_{vid_id}.mp4"
            download_video(vid_id, local_path)
            
            st.session_state.current_video_path = local_path
            st.session_state.video_id = vid_id
            st.session_state.video_name = selected_video_name
            st.session_state.srt_content = "" 
            st.session_state.final_video_path = None
            
            status.update(label="Vídeo carregado!", state="complete")
            st.rerun()

    # --- Área Principal ---
    if st.session_state.current_video_path and os.path.exists(st.session_state.current_video_path):
        col_video, col_editor = st.columns([1, 1])
        
        with col_video:
            st.subheader("📺 Vídeo Original")
            st.video(st.session_state.current_video_path)
            
            st.divider()
            st.subheader("🧠 IA Transcrição")
            
            c_mod, c_btn = st.columns([1,1])
            with c_mod:
                model_size = st.selectbox("Modelo", ["tiny", "base", "small"], index=0, help="Tiny é rápido, Small é preciso.")
            with c_btn:
                st.write("") # Spacer
                if st.button("✨ Gerar Legendas (Auto)"):
                    with st.spinner("Transcrevendo áudio..."):
                        srt, segs = transcribe_audio(st.session_state.current_video_path, model_size)
                        if srt:
                            st.session_state.srt_content = srt
                            st.success("Legendas geradas!")
                            st.rerun()

        with col_editor:
            st.subheader("✏️ Editor & Estilo")
            
            if st.session_state.srt_content:
                # Editor de Texto SRT
                srt_edit = st.text_area("Conteúdo SRT (Edite tempo/texto aqui):", st.session_state.srt_content, height=300)
                st.session_state.srt_content = srt_edit
                
                st.markdown("### 🎨 Estilo da Legenda")
                
                # Opções de Estilo
                style_mode = st.radio("Estilo:", ["TikTok / Reels", "Clássico (TV)", "Karaokê (Amarelo)"], horizontal=True)
                
                c_font, c_color = st.columns(2)
                with c_font:
                    font_size = st.slider("Tamanho Fonte", 10, 100, 60 if style_mode == "TikTok / Reels" else 24)
                    margin_v = st.slider("Margem Vertical", 0, 500, 250 if style_mode == "TikTok / Reels" else 50)
                
                with c_color:
                    text_color_hex = st.color_picker("Cor Texto", "#FFFF00" if "Karaokê" in style_mode else "#FFFFFF")
                    outline_color_hex = st.color_picker("Cor Borda", "#000000")

                if st.button("🔥 Renderizar Vídeo com Legenda", type="primary"):
                    with st.status("Renderizando vídeo final...") as status:
                        # 1. Salva SRT Temporário
                        srt_path = "temp_subs.srt"
                        # IMPORTANTE: Encoding utf-8 para acentos
                        with open(srt_path, "w", encoding="utf-8") as f:
                            f.write(st.session_state.srt_content)
                        
                        # 2. Configura Estilo ASS (Advanced Substation Alpha)
                        ass_primary = hex_to_ass_color(text_color_hex)
                        ass_outline = hex_to_ass_color(outline_color_hex)
                        
                        # Configurações baseadas no modo
                        if style_mode == "TikTok / Reels":
                            # Fonte grande, borda grossa, centralizado
                            style = f"Fontname=Arial,FontSize={font_size},PrimaryColour={ass_primary},OutlineColour={ass_outline},BackColour=&H80000000,BorderStyle=1,Outline=3,Shadow=0,Alignment=2,MarginV={margin_v}"
                        elif style_mode == "Clássico (TV)":
                            # Fundo semi-transparente opcional, fonte menor
                            style = f"Fontname=Arial,FontSize={font_size},PrimaryColour={ass_primary},OutlineColour={ass_outline},BackColour=&H40000000,BorderStyle=3,Outline=1,Shadow=0,Alignment=2,MarginV={margin_v}"
                        else:
                            style = f"Fontname=Arial,FontSize={font_size},PrimaryColour={ass_primary},OutlineColour={ass_outline},BorderStyle=1,Outline=2,Alignment=2,MarginV={margin_v}"

                        # 3. Renderiza
                        output_vid = f"legendado_{st.session_state.video_id}.mp4"
                        
                        # Caminho relativo simples para evitar problemas de path
                        cmd = [
                            "ffmpeg", "-y",
                            "-i", st.session_state.current_video_path,
                            "-vf", f"subtitles={srt_path}:force_style='{style}'",
                            "-c:a", "copy", # Copia áudio sem reencodar (rápido)
                            "-c:v", "libx264", "-preset", "fast", "-crf", "23", # Reencoda vídeo para queimar legenda
                            output_vid
                        ]
                        
                        try:
                            run_cmd(cmd)
                            st.session_state.final_video_path = output_vid
                            status.update(label="Renderização concluída!", state="complete")
                        except Exception as e:
                            status.update(label="Erro na renderização", state="error")
                            st.error(f"Detalhes: {e}")
            else:
                st.info("Gere as legendas primeiro para habilitar a edição.")

        # --- Área de Download / Upload Final ---
        if st.session_state.final_video_path and os.path.exists(st.session_state.final_video_path):
            st.divider()
            st.subheader("✅ Resultado Final")
            
            c_res_view, c_res_act = st.columns([1.5, 1])
            with c_res_view:
                st.video(st.session_state.final_video_path)
            
            with c_res_act:
                with open(st.session_state.final_video_path, "rb") as f:
                    st.download_button(
                        "💾 Baixar MP4 Legendado", 
                        f, 
                        file_name=f"legendado_{st.session_state.video_name}",
                        mime="video/mp4"
                    )
                
                st.write("")
                if st.button("☁️ Enviar para Google Drive"):
                    with st.spinner("Enviando... (pode demorar)"):
                        ok, msg = upload_legendado_to_gas(
                            st.session_state.final_video_path, 
                            st.session_state.video_name
                        )
                        if ok:
                            st.success(f"Sucesso! Arquivo ID: {msg}")
                        else:
                            st.error(f"Falha no envio: {msg}")

    else:
        if not videos:
            st.info("Nenhum vídeo pronto encontrado no Drive. Use a aba 'Montagem' para criar vídeos primeiro.")
        else:
            st.info("👈 Selecione um vídeo na barra lateral para começar.")

if __name__ == "__main__":
    main()
