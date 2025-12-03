# app.py - Editor e Renderizador de Legendas Profissional
import os
import re
import json
import time
import subprocess
import base64
from typing import List, Dict, Any, Optional

import streamlit as st
# Manter moviepy, mas certifique-se de que está no requirements.txt
from moviepy.editor import VideoFileClip # Para extração de áudio
import requests
from io import BytesIO

# --- API Imports (Ajustado para Service Account) ---
from google.oauth2 import service_account # Importado conforme montagem.py
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
# CORREÇÃO: Importação das classes necessárias para o download
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload 

# Tente importar Whisper (dependência externa)
try:
    import whisper
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False
    
# --- CONSTANTES GLOBAIS ---
SCOPES = ['https://www.googleapis.com/auth/drive']
GAS_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbx5DZ52ohxKPl6Lh0DnkhHJejuPBx1Ud6B10Ag_xfnJVzGpE83n7gHdUHnk4yAgrpuidw/exec"
MONETIZA_DRIVE_FOLDER_VIDEOS = "Monetiza_Studio_Videos_Finais"
CONFIG_FILE = "legendas_config.json"
SAVED_FONT_FILE = "saved_custom_font.ttf"
# Removidos CREDENTIALS_FILE e TOKEN_FILE, pois focaremos no Service Account via Secrets

# ====================================================
# FUNÇÕES DE UTILIDADE E CONFIGURAÇÃO
# ====================================================

def run_cmd(cmd):
    """Executa comandos de shell (FFmpeg) e lida com erros."""
    clean = [arg.replace('\u00a0', ' ').strip() if isinstance(arg, str) else arg for arg in cmd if arg]
    st.info(f"Executando: {' '.join(clean)}", icon="💻")
    try:
        result = subprocess.run(clean, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        error_msg = f"Erro FFmpeg:\nStdout: {e.stdout}\nStderr: {e.stderr}"
        st.error(error_msg)
        raise Exception(error_msg)
    except FileNotFoundError:
        st.error("Comando 'ffmpeg' não encontrado. Certifique-se de que o FFmpeg está instalado e no PATH.")
        raise

def format_timestamp(seconds: float) -> str:
    """Formata segundos em formato de timestamp SRT (hh:mm:ss,ms)."""
    millis = int((seconds - int(seconds)) * 1000)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"

def hex_to_ass_color(hex_color: str) -> str:
    """Converte cor HEX (#RRGGBB) para o formato BGR ASS (&H00BBGGRR)."""
    h = hex_color.lstrip('#')
    if len(h) != 6: return "&HFFFFFF&"
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}"

def load_config() -> Dict[str, Any]:
    """Carrega as configurações salvas de estilo de legenda."""
    default = {
        "f_size": 60, 
        "margin_v": 250, 
        "color": "#FFFF00", 
        "border": "#000000",
        "font_style": "Padrão (Arial)" 
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                saved = json.load(f)
                default.update(saved)
        except: 
            st.warning("Configurações salvas inválidas. Usando padrões.")
            pass
    return default

def save_config(settings: Dict[str, Any]):
    """Salva as configurações de estilo de legenda."""
    with open(CONFIG_FILE, "w") as f:
        json.dump(settings, f, indent=4)
    st.session_state.settings = settings
    st.success("Configurações de estilo salvas com sucesso!")

def resolve_font(choice: str) -> str:
    """Resolve o caminho da fonte para o FFmpeg."""
    if choice == "Upload Personalizada" and os.path.exists(SAVED_FONT_FILE):
        return os.path.abspath(SAVED_FONT_FILE) 
    return choice


# ====================================================
# FUNÇÕES DE INTEGRAÇÃO GOOGLE DRIVE / GAS (CORRIGIDO)
# ====================================================

@st.cache_resource(ttl=3600)
def get_drive_service() -> Optional[Any]:
    """
    Cria e retorna o serviço da API Google Drive.
    Prioriza a autenticação via Service Account (Service Account) nos Secrets.
    """
    creds = None
    
    # 1. Tenta carregar credenciais da Service Account via Streamlit Secrets
    if "google_service_account" in st.secrets:
        try:
            creds_info = st.secrets["google_service_account"]
            # Usa o import do service_account, como no montagem.py
            creds = service_account.Credentials.from_service_account_info(
                creds_info, 
                scopes=SCOPES
            )
            st.success("Credenciais do Google Service Account carregadas com sucesso.")
        except Exception as e:
            st.error(f"❌ Erro ao carregar Service Account via Secrets: {e}")
            return None
    
    if creds:
        try:
            return build('drive', 'v3', credentials=creds)
        except Exception as e:
            st.error(f"❌ Falha ao construir o serviço Drive: {e}")
            return None
    else:
        # Este aviso é a solução para o erro do usuário, se as credenciais estiverem faltando
        st.warning("Nenhuma credencial Google Drive Service Account válida encontrada nos Secrets. Por favor, configure `secrets.toml`.")
        return None

def list_videos_ready(service: Any) -> List[Dict[str, Any]]:
    """Lista vídeos 'video_final_' na pasta Monetiza_Studio_Videos_Finais que NÃO estão LEGENDADOS."""
    
    # 1. Encontrar a pasta base
    folder_id = None
    try:
        results = service.files().list(
            q=f"name='{MONETIZA_DRIVE_FOLDER_VIDEOS}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
            fields="files(id)"
        ).execute()
        items = results.get('files', [])
        if items:
            folder_id = items[0]['id']
        else:
            st.warning(f"Pasta '{MONETIZA_DRIVE_FOLDER_VIDEOS}' não encontrada no seu Drive.")
            return []
    except Exception as e:
        st.error(f"Erro ao buscar a pasta base do Drive: {e}")
        return []

    # 2. Listar vídeos dentro da pasta
    try:
        query = (
            f"'{folder_id}' in parents and "
            f"name contains 'video_final_' and "
            f"mimeType!='application/vnd.google-apps.folder' and "
            f"trashed=false"
        )
        query += " and not name contains '[LEGENDADO]'"

        results = service.files().list(
            q=query,
            fields="files(id, name, createdTime, properties)",
            pageSize=100
        ).execute()
        
        videos = results.get('files', [])
        final_videos = [v for v in videos if not '[LEGENDADO]' in v['name']]
        
        return final_videos
    except Exception as e:
        st.error(f"Erro ao listar vídeos prontos: {e}")
        return []

def download_video(service: Any, file_id: str, filename: str):
    """Baixa um arquivo do Google Drive."""
    request = service.files().get_media(fileId=file_id)
    fh = BytesIO()
    # MediaIoBaseDownload é o que estava faltando!
    downloader = MediaIoBaseDownload(fh, request) 
    done = False
    while not done:
        status, done = downloader.next_chunk()
        st.progress(status.progress(), text=f"Baixando {status.total_size} bytes... {int(status.progress()*100)}%")
        
    with open(filename, 'wb') as f:
        f.write(fh.getvalue())

def get_job_roteiro(job_id: str) -> Optional[Dict[str, Any]]:
    """Busca os dados do roteiro via Google Apps Script (GAS)."""
    try:
        response = requests.get(GAS_SCRIPT_URL, params={'jobId': job_id})
        response.raise_for_status()
        data = response.json()
        
        if data.get('status') == 'SUCCESS' and data.get('data'):
            return data['data']
        else:
            st.warning(f"GAS não retornou dados válidos para JOB: {job_id}")
            return None
    except requests.exceptions.RequestException as e:
        st.error(f"Erro de conexão com GAS: {e}")
        return None

def get_full_roteiro_text(roteiro_data: Dict[str, Any]) -> str:
    """Extrai o texto completo do roteiro formatado."""
    full_text = ""
    for item in roteiro_data.get('roteiro', []):
        full_text += f"--- {item.get('speaker', 'NARRADOR')} ---\n{item.get('text', '')}\n"
    return full_text.strip()

def upload_legendado_to_gas(video_path: str, original_name: str) -> tuple[bool, str]:
    """Faz upload do vídeo legendado e move/renomeia no Drive via GAS."""
    try:
        st.info(f"Iniciando upload para o Drive. Vídeo: {os.path.basename(video_path)}")
        
        # 1. Upload do arquivo
        with open(video_path, 'rb') as f:
            video_content = f.read()
        
        encoded_content = base64.b64encode(video_content).decode('utf-8')
        
        # 2. Chamada para o GAS
        payload = {
            'action': 'uploadAndRename',
            'fileName': os.path.basename(video_path),
            'originalName': original_name,
            'folderName': MONETIZA_DRIVE_FOLDER_VIDEOS,
            'mimeType': 'video/mp4',
            'fileData': encoded_content
        }
        
        # O timeout é essencial para uploads grandes
        response = requests.post(GAS_SCRIPT_URL, json=payload, timeout=600) 
        response.raise_for_status()
        result = response.json()
        
        if result.get('status') == 'SUCCESS':
            return True, result.get('fileId', 'ID Desconhecido')
        else:
            return False, result.get('message', 'Erro desconhecido do GAS.')
        
    except requests.exceptions.Timeout:
        return False, "O servidor GAS excedeu o tempo limite (10 minutos)."
    except requests.exceptions.RequestException as e:
        return False, f"Erro de conexão/API durante o upload: {e}"
    except Exception as e:
        return False, f"Erro interno ao ler arquivo para upload: {e}"


# ====================================================
# FUNÇÕES DE TRANSCRIPT E RE-ALINHAMENTO 
# ====================================================

@st.cache_resource(show_spinner=False)
def load_whisper_model(model_size: str):
    """Carrega o modelo Whisper (cacheado)."""
    if not WHISPER_AVAILABLE:
        st.error("Biblioteca 'whisper' não encontrada. Instale para usar esta função.")
        return None
    try:
        return whisper.load_model(model_size)
    except Exception as e:
        st.error(f"Erro ao carregar modelo Whisper '{model_size}': {e}")
        return None

def transcribe_audio_for_word_timing(video_path: str, model_size: str) -> List[Dict[str, Any]]:
    """Extrai áudio e transcreve usando Whisper com timestamps de palavra."""
    audio_path = os.path.splitext(video_path)[0] + ".mp3"
    
    try:
        st.caption("Extraindo áudio...")
        clip = VideoFileClip(video_path)
        clip.audio.write_audiofile(audio_path, logger=None)
        clip.close()
        
        st.caption(f"Carregando modelo Whisper '{model_size}'...")
        model = load_whisper_model(model_size)
        if not model: return []
        
        st.caption("Iniciando transcrição com timestamps de palavra...")
        result = model.transcribe(
            audio_path, 
            language="pt", 
            word_timestamps=True, 
            verbose=False
        )
        
        segments = result.get('segments', [])
        
        if os.path.exists(audio_path): os.remove(audio_path)
        
        return segments

    except Exception as e:
        st.error(f"Falha na extração de áudio ou transcrição Whisper: {e}")
        if os.path.exists(audio_path): os.remove(audio_path)
        return []

def generate_perfect_srt_realigned(segments: List[Dict[str, Any]], full_roteiro_text: str) -> str:
    """
    USA OS TIMESTAMPS DE PALAVRA DO WHISPER PARA ALINHAR E GERAR O SRT 
    COM O TEXTO PERFEITO DO ROTEIRO EM BLOCOS CURTOS (máximo 4 palavras).
    """
    
    # 1. Preparação dos textos e palavras
    clean_text = re.sub(r'--- [A-ZÁÉÕÇ ]+ ---\n', '', full_roteiro_text).strip()
    clean_text = re.sub(r'\s+', ' ', clean_text)
    perfect_words = clean_text.split()
    
    if not perfect_words or not segments:
        return ""

    # 2. Coletar todos os Timestamps de Palavra do Whisper
    whisper_words = []
    for seg in segments:
        if 'words' in seg:
            for w in seg['words']:
                whisper_words.append({
                    'text': w['text'].strip(), 
                    'start': w['start'],
                    'end': w['end']
                })

    if not whisper_words:
        st.warning("Whisper não gerou timestamps de palavra. Verifique se a transcrição foi executada corretamente.")
        return ""

    # 3. Mapeamento e Geração do SRT em Blocos Curtos
    min_len = min(len(perfect_words), len(whisper_words))
    
    srt_content = ""
    subtitle_index = 1
    i = 0 
    
    while i < min_len:
        block_size = min(4, min_len - i)
        
        # Texto é do ROTEIRO PERFEITO
        block_text = perfect_words[i : i + block_size]
        text_to_use = " ".join(block_text)
        
        # Timing é do WHISPER_WORDS
        block_start = whisper_words[i]['start']
        block_end = whisper_words[i + block_size - 1]['end']
        
        if text_to_use and block_end > block_start:
            start_str = format_timestamp(block_start)
            end_str = format_timestamp(block_end)
            
            srt_content += f"{subtitle_index}\n{start_str} --> {end_str}\n{text_to_use}\n\n"
            subtitle_index += 1
        
        i += block_size 

    return srt_content


# ====================================================
# LÓGICA DE RENDERIZAÇÃO FFmpeg
# ====================================================

def render_subtitles(video_path: str, srt_content: str, settings: Dict[str, Any]) -> Optional[str]:
    """Renderiza o vídeo com legendas usando FFmpeg e as configurações ASS."""
    try:
        temp_dir = "temp_render"
        os.makedirs(temp_dir, exist_ok=True)
        
        srt_path = os.path.join(temp_dir, "temp.srt")
        final_video_path = os.path.join(temp_dir, f"legendado_{os.path.basename(video_path)}")
        
        with open(srt_path, "w", encoding="utf-8") as f: 
            f.write(srt_content)
            
        font_path = resolve_font(settings["font_style"])
        
        if settings["font_style"] == "Upload Personalizada" and os.path.exists(font_path):
            font_name_for_style = font_path
        else:
            font_name_for_style = settings["font_style"]
            
        ass_c = hex_to_ass_color(settings["color"])
        ass_b = hex_to_ass_color(settings["border"])
        
        style = (
            f"Fontname={font_name_for_style},FontSize={settings['f_size']},PrimaryColour={ass_c},"
            f"OutlineColour={ass_b},BackColour=&H80000000,BorderStyle=1,Outline=2,Shadow=0,"
            f"Alignment=2,MarginV={settings['margin_v']}"
        )
        
        cmd = [
            "ffmpeg", "-y", "-i", video_path, 
            "-vf", f"subtitles={srt_path}:force_style='{style}'", 
            "-c:a", "copy", 
            "-c:v", "libx264", 
            "-preset", "fast", 
            "-crf", "23", 
            final_video_path
        ]
        
        st.caption(f"Aplicando estilo ASS: {style}")
        run_cmd(cmd)
        
        return final_video_path

    except Exception as e:
        st.error(f"Falha na renderização FFmpeg: {e}")
        return None
    finally:
        if os.path.exists(srt_path): os.remove(srt_path)


# ====================================================
# INTERFACE STREAMLIT
# ====================================================

def main_app():
    st.set_page_config(page_title="Editor de Legendas Pro", layout="wide")
    st.title("🎬 Editor de Legendas Pro")

    # --- Inicialização de Estado ---
    if 'settings' not in st.session_state: st.session_state.settings = load_config()
    if 'drive_service' not in st.session_state: st.session_state.drive_service = get_drive_service()
    if 'videos_list' not in st.session_state: st.session_state.videos_list = []
    if 'selected_video' not in st.session_state: st.session_state.selected_video = None
    if 'job_id' not in st.session_state: st.session_state.job_id = None
    if 'roteiro_text' not in st.session_state: st.session_state.roteiro_text = ""
    if 'srt_content' not in st.session_state: st.session_state.srt_content = ""
    if 'current_video_path' not in st.session_state: st.session_state.current_video_path = None
    if 'final_video_path' not in st.session_state: st.session_state.final_video_path = None
    if 'video_info' not in st.session_state: st.session_state.video_info = None

    
    # --- Colunas Principais ---
    col1, col2 = st.columns([1, 2])

    with col1:
        st.subheader("⚙️ Configurações e Workflow")
        
        # --- 1. Configurações de Estilo ---
        with st.expander("Estilo da Legenda (Salvo)", expanded=True):
            current_settings = st.session_state.settings
            
            font_options = ["Padrão (Arial)", "Upload Personalizada"]
            
            font_choice = st.selectbox("Fonte:", font_options, index=font_options.index(current_settings["font_style"]) if current_settings["font_style"] in font_options else 0)
            
            if font_choice == "Upload Personalizada":
                font_file = st.file_uploader("Upload do arquivo .ttf/.otf", type=['ttf', 'otf'])
                if font_file:
                    with open(SAVED_FONT_FILE, "wb") as f:
                        f.write(font_file.getbuffer())
                    st.success("Fonte personalizada salva!")
            
            col1_c, col2_c = st.columns(2)
            with col1_c:
                f_size = st.slider("Tamanho da Fonte:", 30, 100, current_settings["f_size"])
                color = st.color_picker("Cor da Fonte:", current_settings["color"])
            with col2_c:
                margin_v = st.slider("Margem Vertical (px):", 100, 350, current_settings["margin_v"])
                border = st.color_picker("Cor da Borda/Outline:", current_settings["border"])

            new_settings = {
                "f_size": f_size,
                "margin_v": margin_v,
                "color": color,
                "border": border,
                "font_style": font_choice
            }

            if st.button("💾 Salvar Estilo"):
                save_config(new_settings)

        # --- 2. Seleção de Vídeo ---
        st.subheader("📹 Vídeo e Roteiro")
        
        if st.button("🔄 Buscar Vídeos Prontos no Drive"):
            # Verifica se o serviço do Drive foi inicializado com sucesso
            if st.session_state.drive_service:
                with st.spinner("Buscando vídeos..."):
                    st.session_state.videos_list = list_videos_ready(st.session_state.drive_service)
                    if not st.session_state.videos_list:
                         st.warning("Nenhum vídeo 'video_final_' sem tag '[LEGENDADO]' encontrado.")
            else:
                 st.error("Não foi possível conectar ao Google Drive. Verifique as credenciais no `secrets.toml`.")
                 return # Para evitar prosseguir sem conexão
        
        if st.session_state.videos_list:
            video_names = [v['name'] for v in st.session_state.videos_list]
            selected_name = st.selectbox("Selecione o Vídeo:", [""] + video_names)
            
            if selected_name and selected_name != st.session_state.selected_video:
                st.session_state.selected_video = selected_name
                st.session_state.video_info = next((v for v in st.session_state.videos_list if v['name'] == selected_name), None)
                st.session_state.job_id = None
                st.session_state.roteiro_text = ""
                st.session_state.srt_content = ""
                st.session_state.current_video_path = None
                st.session_state.final_video_path = None
                st.rerun()

            if st.session_state.video_info:
                match = re.search(r'(JOB-[a-zA-Z0-9-]+)', st.session_state.video_info['name'])
                st.session_state.job_id = match.group(1) if match else None
                
                st.caption(f"ID do Job Encontrado: **{st.session_state.job_id or 'N/A'}**")
                
                if st.button("⬇️ 1. Baixar Vídeo"):
                    if st.session_state.drive_service and st.session_state.video_info:
                        temp_dir = "temp_download"
                        os.makedirs(temp_dir, exist_ok=True)
                        file_id = st.session_state.video_info['id']
                        local_path = os.path.join(temp_dir, st.session_state.video_info['name'])
                        
                        try:
                            download_video(st.session_state.drive_service, file_id, local_path)
                            st.session_state.current_video_path = local_path
                            st.success(f"Vídeo baixado: {os.path.basename(local_path)}")
                        except Exception as e:
                            st.error(f"Falha no download: {e}")
                            st.session_state.current_video_path = None
                            
                if st.session_state.current_video_path and st.session_state.job_id and st.button("📝 2. Buscar Roteiro Perfeito"):
                    with st.spinner(f"Buscando roteiro para {st.session_state.job_id}..."):
                        roteiro = get_job_roteiro(st.session_state.job_id)
                        if roteiro:
                            st.session_state.roteiro_text = get_full_roteiro_text(roteiro)
                            st.success("Roteiro Perfeito obtido!")
                        else:
                            st.error("Falha ao obter o roteiro. Verifique o ID do Job.")
                            st.session_state.roteiro_text = ""
                        
    with col2:
        st.subheader("Workflow de Legenda")

        if st.session_state.current_video_path and os.path.exists(st.session_state.current_video_path):
            st.video(st.session_state.current_video_path)
        elif st.session_state.final_video_path and os.path.exists(st.session_state.final_video_path):
            st.video(st.session_state.final_video_path)
        else:
            st.info("Aguardando download de vídeo...")
            
        st.markdown("---")
        
        if st.session_state.current_video_path and st.session_state.roteiro_text:
            
            st.subheader("✨ Geração de Legenda Re-alinhada")
            
            if not WHISPER_AVAILABLE:
                st.error("O processamento de timing requer a biblioteca 'whisper'.")
            else:
                mod = st.radio("Modelo Whisper (Timing):", ["tiny", "base"], horizontal=True)
                
                if st.button("🚀 3. Gerar Legenda Re-alinhada (Correção de Sincronia)", type="primary"):
                    
                    with st.status("Iniciando Re-alinhamento...", expanded=True) as status:
                        
                        status.update(label=f"1. Transcrevendo áudio para TIMING (Modelo {mod})...")
                        segments = transcribe_audio_for_word_timing(st.session_state.current_video_path, mod)
                    
                    if segments:
                        with st.status("2. Mapeando Texto Perfeito para o Timing em Blocos Curtos...", expanded=True) as status:
                            srt_content = generate_perfect_srt_realigned(segments, st.session_state.roteiro_text)
                            st.session_state.srt_content = srt_content
                            status.update(label="SRT Gerado e Re-alinhado (Correção de Sincronia)!", state="complete")
                            st.success("Legenda Re-alinhada gerada com sucesso!")
                            st.rerun()

        if st.session_state.srt_content:
            st.subheader("✍️ SRT Gerado (Para Revisão)")
            st.session_state.srt_content = st.text_area(
                "Edite o SRT aqui:", 
                st.session_state.srt_content, 
                height=300
            )

        if st.session_state.srt_content and st.session_state.current_video_path:
            st.subheader("🎥 Renderização e Upload")
            
            if st.button("⚙️ 4. Renderizar Vídeo com Legendas"):
                with st.spinner("Renderizando vídeo com FFmpeg..."):
                    final_path = render_subtitles(
                        st.session_state.current_video_path, 
                        st.session_state.srt_content, 
                        st.session_state.settings
                    )
                    st.session_state.final_video_path = final_path
                    if final_path:
                        st.success("Renderização concluída! Vídeo pronto para upload.")
                        st.rerun()

            if st.session_state.final_video_path and os.path.exists(st.session_state.final_video_path):
                st.info("Vídeo Legendado Pronto para Upload no Drive.")
                
                new_video_name = st.session_state.video_info['name'].replace('video_final_', 'video_legendado_')
                st.markdown(f"**Nome Final:** `{new_video_name}`")
                
                if st.button("📤 5. Fazer Upload para o Drive (e Renomear)", type="secondary"):
                    with st.spinner("Enviando vídeo para o Google Drive via GAS..."):
                        ok, msg = upload_legendado_to_gas(st.session_state.final_video_path, st.session_state.video_info['name'])
                        if ok:
                            st.balloons()
                            st.success(f"Upload concluído! Vídeo marcado como [LEGENDADO] no Drive. File ID: {msg}")
                        else:
                            st.error(f"Falha no upload: {msg}")
                            
            
            st.markdown("---")
            st.caption(f"Roteiro Carregado: {len(st.session_state.roteiro_text.split())} palavras.")
            st.caption(f"SRT Gerado: {len(st.session_state.srt_content.split())} palavras.")

if __name__ == '__main__':
    if not os.path.exists("temp_download"): os.makedirs("temp_download")
    if not os.path.exists("temp_render"): os.makedirs("temp_render")
    
    main_app()
