# editor_legendas.py - Editor de Legendas Avançado (Pós-Produção)
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
import requests
import streamlit as st
from PIL import Image, ImageDraw, ImageFont

# --- Imports de IA ---
import whisper

# --- API Imports ---
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# --- CONFIGURAÇÃO ---
# URL do Script GAS para interação com Drive
GAS_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbx5DZ52ohxKPl6Lh0DnkhHJejuPBx1Ud6B10Ag_xfnJVzGpE83n7gHdUHnk4yAgrpuidw/exec"
MONETIZA_DRIVE_FOLDER_VIDEOS = "Monetiza_Studio_Videos_Finais" # Pasta onde videos sem legenda estao
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
def run_cmd(cmd):
    """Executa comandos de shell (FFmpeg)"""
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
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
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}"

# =========================
# Google Drive Service
# =========================
_drive_service = None

def get_drive_service():
    global _drive_service
    required_keys = ["type", "project_id", "private_key_id", "private_key", "client_email", "client_id", "auth_uri", "token_uri", "auth_provider_x509_cert_url", "client_x509_cert_url", "universe_domain"]
    prefix = "gcp_service_account_"

    if _drive_service is None:
        try:
            creds_info = {}
            for key in required_keys:
                val = st.secrets.get(prefix + key)
                if val is None: 
                    st.error(f"Falta chave de credencial: {prefix + key}")
                    st.stop()
                creds_info[key] = val

            creds = service_account.Credentials.from_service_account_info(
                creds_info, scopes=['https://www.googleapis.com/auth/drive.readonly']
            )
            _drive_service = build('drive', 'v3', credentials=creds)
        except Exception as e:
            st.error(f"Erro ao conectar Drive: {e}")
            st.stop()
    return _drive_service

def list_videos_ready():
    """Lista vídeos prontos para legendagem (status READY_FOR_PUBLISH, sem legenda)"""
    service = get_drive_service()
    videos = []
    try:
        # Busca pastas de video
        q_f = f"name = '{MONETIZA_DRIVE_FOLDER_VIDEOS}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        folders = service.files().list(q=q_f, fields="files(id)").execute().get('files', [])
        if not folders: return []
        folder_id = folders[0]['id']

        # Lista vídeos mp4
        q_v = f"mimeType = 'video/mp4' and '{folder_id}' in parents and trashed = false"
        files = service.files().list(q=q_v, orderBy="createdTime desc", pageSize=20, fields="files(id, name, description)").execute().get('files', [])
        
        for f in files:
            # Filtra vídeos que já foram legendados (opcional, por enquanto mostra tudo)
            videos.append(f)
            
    except Exception as e:
        st.error(f"Erro listar vídeos: {e}")
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
    """Extrai áudio e transcreve com Whisper"""
    try:
        # Extrai áudio temporário
        audio_path = "temp_audio.wav"
        run_cmd(["ffmpeg", "-y", "-i", video_path, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", audio_path])
        
        model = whisper.load_model(model_size)
        result = model.transcribe(audio_path, language="pt")
        
        segments = result['segments']
        srt_content = ""
        for i, seg in enumerate(segments):
            start = format_timestamp(seg['start'])
            end = format_timestamp(seg['end'])
            text = seg['text'].strip()
            srt_content += f"{i+1}\n{start} --> {end}\n{text}\n\n"
            
        os.remove(audio_path)
        return srt_content, segments
    except Exception as e:
        st.error(f"Erro Transcrição: {e}")
        return None, None

# =========================
# Interface Principal
# =========================
def main():
    st.title("🎬 Editor de Legendas Pro")
    
    if "current_video_path" not in st.session_state: st.session_state.current_video_path = None
    if "srt_content" not in st.session_state: st.session_state.srt_content = ""
    if "video_id" not in st.session_state: st.session_state.video_id = None

    # --- Sidebar: Seleção de Vídeo ---
    st.sidebar.header("📁 Vídeos Prontos")
    videos = list_videos_ready()
    
    video_opts = {v['name']: v['id'] for v in videos}
    selected_video_name = st.sidebar.selectbox("Escolha um vídeo:", list(video_opts.keys()) if video_opts else ["Nenhum"])
    
    if st.sidebar.button("⬇️ Carregar Vídeo") and selected_video_name != "Nenhum":
        vid_id = video_opts[selected_video_name]
        with st.spinner("Baixando vídeo do Drive..."):
            # Limpa temp anterior
            if st.session_state.current_video_path and os.path.exists(st.session_state.current_video_path):
                os.remove(st.session_state.current_video_path)
                
            local_path = f"temp_{vid_id}.mp4"
            download_video(vid_id, local_path)
            st.session_state.current_video_path = local_path
            st.session_state.video_id = vid_id
            st.session_state.srt_content = "" # Reseta legenda
            st.rerun()

    # --- Área Principal ---
    if st.session_state.current_video_path:
        col_video, col_editor = st.columns([1, 1])
        
        with col_video:
            st.subheader("📺 Preview Original")
            st.video(st.session_state.current_video_path)
            
            st.markdown("---")
            st.subheader("🧠 IA Transcrição")
            col_ai1, col_ai2 = st.columns(2)
            with col_ai1:
                model_size = st.selectbox("Modelo Whisper", ["tiny", "base", "small"], index=0)
            with col_ai2:
                if st.button("✨ Gerar Legendas (Auto)"):
                    with st.spinner("Transcrevendo áudio..."):
                        srt, segs = transcribe_audio(st.session_state.current_video_path, model_size)
                        if srt:
                            st.session_state.srt_content = srt
                            st.success("Transcrição concluída!")
                            st.rerun()

        with col_editor:
            st.subheader("✏️ Editor de Legendas")
            if st.session_state.srt_content:
                srt_edit = st.text_area("Editor SRT (Raw)", st.session_state.srt_content, height=300)
                st.session_state.srt_content = srt_edit
                
                st.markdown("### 🎨 Estilo")
                style_tabs = st.tabs(["TikTok / Reels", "Clássico", "Karaokê (Simples)"])
                
                font_size = 0
                primary_color = ""
                outline_color = ""
                
                with style_tabs[0]: # TikTok
                    st.caption("Fonte grande, cores vibrantes, fundo opcional")
                    s_tik_size = st.slider("Tamanho (TikTok)", 10, 100, 60)
                    s_tik_color = st.color_picker("Cor Texto", "#FFFF00")
                    s_tik_border = st.color_picker("Cor Borda", "#000000")
                    # Salva configs
                    font_size = s_tik_size
                    primary_color = hex_to_ass_color(s_tik_color)
                    outline_color = hex_to_ass_color(s_tik_border)
                    
                with style_tabs[1]: # Clássico
                    st.caption("Legenda padrão de cinema/TV")
                
                if st.button("🔥 Renderizar Vídeo com Legenda"):
                    with st.status("Renderizando vídeo final...") as status:
                        # 1. Salva SRT
                        srt_path = "temp_subs.srt"
                        with open(srt_path, "w", encoding="utf-8") as f:
                            f.write(st.session_state.srt_content)
                        
                        # 2. Configura Estilo ASS
                        # Margem V para centralizar ou base
                        margin_v = 250 # Fixo por enquanto, pode virar slider
                        
                        ass_style = (
                            f"FontName=Arial,FontSize={font_size},"
                            f"PrimaryColour={primary_color},OutlineColour={outline_color},"
                            f"BackColour=&H80000000,BorderStyle=1,Outline=3,Shadow=0,"
                            f"Alignment=2,MarginV={margin_v}"
                        )
                        
                        # 3. FFmpeg Burn-in
                        output_vid = f"legendado_{st.session_state.video_id}.mp4"
                        # Importante: path relativo para evitar erros de filtro
                        cmd = [
                            "ffmpeg", "-y",
                            "-i", st.session_state.current_video_path,
                            "-vf", f"subtitles={srt_path}:force_style='{ass_style}'",
                            "-c:a", "copy",
                            output_vid
                        ]
                        
                        try:
                            run_cmd(cmd)
                            status.update(label="Renderização concluída!", state="complete")
                            st.session_state.final_video_path = output_vid
                        except Exception as e:
                            status.update(label="Erro na renderização", state="error")
                            
            else:
                st.info("Gere as legendas primeiro para editar.")

        # --- Área de Download / Upload Final ---
        if "final_video_path" in st.session_state and os.path.exists(st.session_state.final_video_path):
            st.markdown("---")
            st.subheader("✅ Resultado Final")
            col_res1, col_res2 = st.columns(2)
            with col_res1:
                st.video(st.session_state.final_video_path)
            with col_res2:
                with open(st.session_state.final_video_path, "rb") as f:
                    st.download_button("💾 Baixar MP4 Legendado", f, "video_legendado.mp4")
                
                if st.button("☁️ Enviar para 'Vídeos Legendados' (Drive)"):
                    # Lógica de upload para pasta final (pode ser implementada similar ao montagem.py)
                    st.info("Funcionalidade de upload final a ser implementada na v2.")

    else:
        st.info("👈 Selecione um vídeo na barra lateral para começar.")

if __name__ == "__main__":
    main()
