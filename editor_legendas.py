# pages/4_🎬_Editor_Legendas.py - Editor de Legendas - VERSÃO C/ INTEGRAÇÃO DO ROTEIRO
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
GAS_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbx5DZ52ohxKPl6Lh0DnkhHJejuPBx1Ud6B10Ag_xfnJVzGpE83n7gHdUHnk4yAgrpuidw/exec"
MONETIZA_DRIVE_FOLDER_VIDEOS = "Monetiza_Studio_Videos_Finais" 
MONETIZA_DRIVE_FOLDER_LEGENDADOS = "Monetiza_Studio_Videos_Legendados" 

os.environ.setdefault("IMAGEIO_FFMPEG_EXE", "/usr/bin/ffmpeg")

# =========================
# Page Config
# =========================
st.set_page_config(
    page_title="Editor de Legendas",
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
    millis = int((seconds - int(seconds)) * 1000)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"

def hex_to_ass_color(hex_color):
    h = hex_color.lstrip('#')
    if len(h) != 6: return "&HFFFFFF&"
    # ASS usa formato BGR em hexadecimal
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}"

def get_full_roteiro_text(roteiro_data: Dict[str, Any]) -> str:
    """Extrai e formata o texto completo do roteiro JSON."""
    if not roteiro_data or 'roteiro' not in roteiro_data:
        return "Roteiro não encontrado ou em formato inválido."
        
    full_text = ""
    roteiro = roteiro_data.get('roteiro', {})
    
    # Adiciona os blocos principais, se existirem
    if 'hook' in roteiro and 'text' in roteiro['hook']:
        full_text += "--- HOOK ---\n" + roteiro['hook']['text'] + "\n\n"
    
    if 'leitura' in roteiro and 'text' in roteiro['leitura']:
        full_text += "--- LEITURA ---\n" + roteiro['leitura']['text'] + "\n\n"
        
    # Ajuste este bloco se a estrutura do seu JSON de roteiro tiver mais blocos de texto
    
    return full_text.strip()


# =========================
# Google Drive Service
# =========================
_drive_service = None # Cache global para evitar re-criação

def get_drive_service(json_file=None):
    """Obtém o serviço Drive, priorizando st.secrets ou usando JSON File."""
    global _drive_service
    
    if _drive_service: return _drive_service

    creds = None
    required_keys = ["type", "project_id", "private_key_id", "private_key", "client_email", "client_id", "auth_uri", "token_uri", "auth_provider_x509_cert_url", "client_x509_cert_url", "universe_domain"]
    prefix = "gcp_service_account_"

    # TENTA CARREGAR DE ST.SECRETS
    try:
        creds_info = {}
        found_all_secrets = True
        for key in required_keys:
            val = st.secrets.get(prefix + key)
            if val is None: 
                found_all_secrets = False
                break
            creds_info[key] = val
        
        if found_all_secrets:
            if "private_key" in creds_info: 
                creds_info["private_key"] = creds_info["private_key"].replace("\\n", "\n")
            
            creds = service_account.Credentials.from_service_account_info(
                creds_info, scopes=['https://www.googleapis.com/auth/drive'] 
            )
            st.session_state["drive_connected_via_secrets"] = True
    except Exception as e:
        pass

    # TENTA CARREGAR VIA UPLOAD DE JSON FILE (FALLBACK)
    if creds is None and json_file is not None:
        try:
            file_content = json_file.getvalue().decode("utf-8")
            info = json.loads(file_content)
            creds = service_account.Credentials.from_service_account_info(
                info, scopes=['https://www.googleapis.com/auth/drive']
            )
            st.session_state["drive_connected_via_secrets"] = False
        except Exception as e:
            st.error(f"Erro JSON Upload: {e}")
            return None

    if creds:
        try: 
            _drive_service = build('drive', 'v3', credentials=creds)
            return _drive_service
        except Exception as e: 
            st.error(f"Erro ao construir serviço Drive: {e}")
            return None
    
    st.session_state["drive_connected_via_secrets"] = False
    return None

def list_videos_ready(service):
    """Lista vídeos para legenda na pasta final e adiciona diagnóstico."""
    videos = []
    if not service: return []
    
    try:
        # 1. Busca a pasta 'Monetiza_Studio_Videos_Finais'
        st.info("Buscando pasta 'Monetiza_Studio_Videos_Finais'...")
        q_f = f"name = '{MONETIZA_DRIVE_FOLDER_VIDEOS}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        folders = service.files().list(q=q_f, fields="files(id)").execute().get('files', [])
        
        if not folders:
            st.error(f"ERRO: A conta de serviço NÃO encontrou a pasta '{MONETIZA_DRIVE_FOLDER_VIDEOS}'.")
            return []
            
        folder_id = folders[0]['id']
        st.info(f"✅ Pasta encontrada (ID: {folder_id}). Buscando arquivos MP4...")
        
        # 2. Busca os arquivos MP4 dentro da pasta
        # Filtra por arquivos que tenham 'video_final_' no nome para garantir que são Jobs Finalizados
        q_v = f"mimeType = 'video/mp4' and name contains 'video_final_' and '{folder_id}' in parents and trashed = false"
        files = service.files().list(q=q_v, orderBy="createdTime desc", pageSize=20, fields="files(id, name, description, createdTime)").execute().get('files', [])
        
        if not files:
            st.warning(f"A pasta foi encontrada, mas NÃO há arquivos MP4 visíveis.")
        
        for f in files: videos.append(f)
        
    except HttpError as e:
        st.error(f"Erro da API do Drive (HTTP {e.resp.status}): Verifique se o serviço tem permissão de leitura.")
        return []
    except Exception as e:
        st.error(f"Erro inesperado ao listar vídeos: {e}")
        return []
        
    return videos

# =========================
# GAS JOB ROTEIRO
# =========================
def get_job_roteiro(job_id: str) -> Optional[Dict[str, Any]]:
    """Busca o JSON do roteiro original via GAS (usando doGet)."""
    url = f"{GAS_SCRIPT_URL}?action=get_job&job_id={job_id}"
    st.info(f"Buscando roteiro para {job_id}...")
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status() # Levanta erro para 4xx/5xx
        
        # O GAS retorna o conteúdo do arquivo JSON diretamente no doGet
        data = response.json() 
        if data.get('status') == 'error':
             st.error(f"Erro GAS: {data.get('message')}")
             return None
        return data
        
    except requests.exceptions.RequestException as e:
        st.error(f"Erro de conexão com o GAS para {job_id}: {e}")
        return None
    except json.JSONDecodeError:
        st.error(f"Erro ao decodificar JSON do roteiro para {job_id}. O arquivo pode estar vazio ou corrompido.")
        return None

# =========================
# Whisper Transcription
# =========================
def transcribe_audio(video_path, model_size="tiny"):
    """Transcreve áudio e retorna conteúdo SRT e segmentos."""
    if whisper is None:
        st.error("Biblioteca 'whisper' não instalada.")
        return None, None
    try:
        audio_path = "temp_audio.wav"
        st.info("Extraindo áudio...")
        run_cmd(["ffmpeg", "-y", "-i", video_path, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", audio_path])
        st.info(f"Carregando modelo Whisper ({model_size})...")
        model = whisper.load_model(model_size, device="cpu") 
        st.info("Transcrevendo...")
        result = model.transcribe(audio_path, language="pt")
        segments = result['segments']
        
        # Constrói o SRT a partir da transcrição (Fallback)
        srt_content = ""
        for i, seg in enumerate(segments):
            start = format_timestamp(seg['start'])
            end = format_timestamp(seg['end'])
            text = seg['text'].strip()
            srt_content += f"{i+1}\n{start} --> {end}\n{text}\n\n"
            
        if os.path.exists(audio_path): os.remove(audio_path)
        return srt_content, segments
    except Exception as e:
        st.error(f"Erro Transcrição: {e}")
        return None, None

# =========================
# Upload Final
# =========================
def upload_legendado_to_gas(video_path, original_name):
    try:
        with open(video_path, "rb") as f: video_bytes = f.read()
        video_b64 = base64.b64encode(video_bytes).decode('utf-8')
        payload = {
            "action": "upload_video",
            "job_id": "LEGENDADO_" + str(int(time.time())),
            "video_data": video_b64,
            "filename": f"LEGENDADO_{original_name}",
            "meta_data": {"status": "LEGENDADO", "processed_at": datetime.now().isoformat()}
        }
        response = requests.post(GAS_SCRIPT_URL, json=payload, timeout=300)
        if response.status_code == 200:
            res = response.json()
            # Este GAS salva na pasta 'Monetiza_Studio_Videos_Finais', o ideal seria 'Monetiza_Studio_Videos_Legendados'
            return (True, res.get("file_id")) if res.get("status") == "success" else (False, res.get("message"))
        return False, f"HTTP {response.status_code}"
    except Exception as e: return False, str(e)

# =========================
# Interface Principal
# =========================
def main():
    st.title("🎬 Editor de Legendas Pro")
    
    # State Management (Adicionando job_id e roteiro_data)
    if "current_video_path" not in st.session_state: st.session_state.current_video_path = None
    if "srt_content" not in st.session_state: st.session_state.srt_content = ""
    if "video_id" not in st.session_state: st.session_state.video_id = None
    if "video_name" not in st.session_state: st.session_state.video_name = ""
    if "final_video_path" not in st.session_state: st.session_state.final_video_path = None
    if "drive_connected_via_secrets" not in st.session_state: st.session_state.drive_connected_via_secrets = False
    if "job_id" not in st.session_state: st.session_state.job_id = None # Novo: ID do Job
    if "roteiro_data" not in st.session_state: st.session_state.roteiro_data = None # Novo: Dados do Roteiro JSON


    # --- BARRA LATERAL: SELEÇÃO DE FONTE ---
    st.sidebar.header("📂 Fonte do Arquivo")
    source_option = st.sidebar.radio("Origem:", ["Google Drive", "Upload Local (PC)"], index=0)
    
    # --- OPÇÃO 1: GOOGLE DRIVE ---
    if source_option == "Google Drive":
        st.sidebar.divider()
        st.sidebar.caption("Conexão com Drive")
        
        drive_service = get_drive_service()
        uploaded_key = None

        if drive_service:
            if st.session_state.drive_connected_via_secrets:
                st.sidebar.success("Drive conectado via Secrets.")
            else:
                 st.sidebar.success("Drive conectado.")
        
        # Se não conectou automatico, pede JSON
        if not drive_service:
            st.sidebar.warning("Drive não conectado via secrets.")
            uploaded_key = st.sidebar.file_uploader("Credenciais (.json)", type="json")
            if uploaded_key:
                 drive_service = get_drive_service(uploaded_key)
                 if drive_service: st.sidebar.success("Drive conectado via upload.")


        if drive_service:
            if st.sidebar.button("🔄 Atualizar Lista"): st.rerun()
            
            videos = list_videos_ready(drive_service)
            
            if not videos:
                st.sidebar.info("Nenhum vídeo listado (Verifique a área principal para diagnóstico).")
            else:
                video_opts = {v['name']: v['id'] for v in videos}
                sel_vid = st.sidebar.selectbox("Vídeo:", ["Selecione..."] + list(video_opts.keys()))
                
                if st.sidebar.button("⬇️ Carregar do Drive") and sel_vid != "Selecione...":
                    vid_id = video_opts[sel_vid]
                    
                    # TENTA EXTRAIR JOB ID DO NOME DO VÍDEO
                    match = re.search(r'(JOB-[a-zA-Z0-9-]+)', sel_vid)
                    extracted_job_id = match.group(1) if match else None

                    with st.status("Baixando...", expanded=True) as status:
                        local_path = f"temp_{vid_id}.mp4"
                        download_video(drive_service, vid_id, local_path)
                        
                        # 1. Atualiza o estado do vídeo
                        st.session_state.current_video_path = local_path
                        st.session_state.video_id = vid_id
                        st.session_state.video_name = sel_vid
                        st.session_state.srt_content = ""
                        st.session_state.final_video_path = None
                        
                        # 2. Busca o roteiro se o Job ID for encontrado
                        if extracted_job_id:
                            status.update(label="Buscando roteiro...", state="running")
                            st.session_state.job_id = extracted_job_id
                            roteiro = get_job_roteiro(extracted_job_id)
                            st.session_state.roteiro_data = roteiro
                        else:
                            st.session_state.job_id = None
                            st.session_state.roteiro_data = None
                            st.warning("Job ID não encontrado no nome do arquivo. Apenas a transcrição por IA estará disponível.")

                        status.update(label="Pronto!", state="complete")
                        st.rerun()
        else:
            st.sidebar.error("Drive não conectado. Configure secrets ou faça upload.")

    # --- OPÇÃO 2: UPLOAD LOCAL ---
    else:
        # Lógica de upload local (sem roteiro)
        st.sidebar.divider()
        uploaded_video = st.sidebar.file_uploader("Envie um vídeo (.mp4, .mov)", type=["mp4", "mov", "avi"])
        if uploaded_video:
            if st.session_state.video_name != uploaded_video.name:
                with st.status("Processando upload...", expanded=True) as status:
                    local_path = f"temp_local_{int(time.time())}.mp4"
                    with open(local_path, "wb") as f:
                        f.write(uploaded_video.getbuffer())
                    
                    st.session_state.current_video_path = local_path
                    st.session_state.video_id = "local_upload"
                    st.session_state.video_name = uploaded_video.name
                    st.session_state.srt_content = ""
                    st.session_state.final_video_path = None
                    st.session_state.job_id = None
                    st.session_state.roteiro_data = None
                    status.update(label="Vídeo carregado!", state="complete")
                    st.rerun()
            else:
                st.sidebar.success(f"Arquivo atual: {uploaded_video.name}")

    # --- ÁREA PRINCIPAL (EDITOR) ---
    if st.session_state.current_video_path and os.path.exists(st.session_state.current_video_path):
        c1, c2 = st.columns([1, 1])
        with c1:
            st.subheader("📺 Original")
            st.video(st.session_state.current_video_path)
            
            st.divider()
            st.subheader("Ferramentas de Transcrição")
            c_ia1, c_ia2 = st.columns([1,1])
            with c_ia1:
                mod = st.selectbox("Modelo IA", ["tiny", "base"], help="Tiny é mais rápido.")
            
            with c_ia2:
                st.write("")
                
                # Se há roteiro, o botão é para gerar timing
                if st.session_state.roteiro_data:
                    if st.button("✨ Gerar Timing (Whisper)", type="primary"):
                        st.info("Esta função será implementada na próxima etapa. Por enquanto, use o Fallback.")
                    # Botão para gerar a transcrição completa como fallback (se o roteiro estiver incompleto)
                    if st.button("Transcrever Áudio (Fallback)"):
                        with st.spinner("Transcrevendo...") as status:
                            srt, _ = transcribe_audio(st.session_state.current_video_path, mod)
                            if srt:
                                st.session_state.srt_content = srt
                                status.update(label="Transcrição Gerada!", state="complete")
                                st.rerun()
                            else:
                                status.update(label="Erro!", state="error")
                
                # Se NÃO há roteiro (upload local ou Job ID não encontrado), o botão é o padrão
                else:
                    if st.button("✨ Gerar Legendas"):
                        with st.spinner("Transcrevendo...") as status:
                            srt, _ = transcribe_audio(st.session_state.current_video_path, mod)
                            if srt:
                                st.session_state.srt_content = srt
                                status.update(label="Transcrição Gerada!", state="complete")
                                st.rerun()
                            else:
                                status.update(label="Erro!", state="error")
                                

        with c2:
            st.subheader("✏️ Editor & Render")
            
            # NOVO: Exibe o Roteiro Original (Texto Perfeito)
            if st.session_state.roteiro_data:
                full_roteiro_text = get_full_roteiro_text(st.session_state.roteiro_data)
                st.info(f"Roteiro Original (Job ID: {st.session_state.job_id})")
                st.text_area("Texto Perfeito do Roteiro", full_roteiro_text, height=150, disabled=True)

            
            if st.session_state.srt_content:
                st.markdown("##### Legendas Geradas (Ajuste o Timing aqui)")
                # Mantemos o text_area aqui para que o usuário possa visualizar e ajustar o SRT
                srt_edit = st.text_area("SRT", st.session_state.srt_content, height=250)
                st.session_state.srt_content = srt_edit
                
                st.markdown("### Estilo")
                col_s1, col_s2 = st.columns(2)
                with col_s1:
                    f_size = st.slider("Tamanho", 10, 100, 60)
                    margin_v = st.slider("Posição Y", 0, 500, 250)
                with col_s2:
                    color = st.color_picker("Cor", "#FFFF00")
                    border = st.color_picker("Borda", "#000000")

                if st.button("🔥 Renderizar Final", type="primary"):
                    with st.status("Renderizando...") as status:
                        srt_path = "temp.srt"
                        with open(srt_path, "w", encoding="utf-8") as f: f.write(st.session_state.srt_content)
                        
                        ass_c = hex_to_ass_color(color)
                        ass_b = hex_to_ass_color(border)
                        style = f"Fontname=Arial,FontSize={f_size},PrimaryColour={ass_c},OutlineColour={ass_b},BackColour=&H80000000,BorderStyle=1,Outline=3,Shadow=0,Alignment=2,MarginV={margin_v}"
                        
                        out_vid = f"legendado_{st.session_state.video_id}.mp4"
                        cmd = ["ffmpeg", "-y", "-i", st.session_state.current_video_path, "-vf", f"subtitles={srt_path}:force_style='{style}'", "-c:a", "copy", "-c:v", "libx264", "-preset", "fast", "-crf", "23", out_vid]
                        
                        try:
                            run_cmd(cmd)
                            st.session_state.final_video_path = out_vid
                            status.update(label="Sucesso!", state="complete")
                        except: status.update(label="Erro!", state="error")
            else:
                if st.session_state.roteiro_data:
                    st.info("O roteiro foi carregado! Use 'Gerar Timing (Whisper)' para começar a edição.")
                else:
                    st.info("Gere as legendas para começar a edição.")

        if st.session_state.final_video_path and os.path.exists(st.session_state.final_video_path):
            st.divider()
            st.success("Finalizado!")
            c_fin1, c_fin2 = st.columns([1.5, 1])
            with c_fin1: st.video(st.session_state.final_video_path)
            with c_fin2:
                with open(st.session_state.final_video_path, "rb") as f:
                    st.download_button("💾 Baixar MP4", f, f"legendado_{st.session_state.video_name}", mime="video/mp4")
                if st.button("☁️ Enviar p/ Drive"):
                    with st.spinner("Enviando..."):
                        ok, msg = upload_legendado_to_gas(st.session_state.final_video_path, st.session_state.video_name)
                        if ok: st.success("Enviado!")
                        else: st.error(f"Erro: {msg}")

    else:
        st.info("👈 Escolha uma fonte na barra lateral.")

if __name__ == "__main__":
    main()
