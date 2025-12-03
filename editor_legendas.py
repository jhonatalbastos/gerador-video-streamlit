# app.py - Editor e Renderizador de Legendas Profissional
import os
import re
import json
import time
import subprocess
import base64
from typing import List, Dict, Any, Optional

import streamlit as st
from moviepy.editor import VideoFileClip # Para extração de áudio
import requests
from io import BytesIO

# --- Configuração Google Drive API ---
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
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
CREDENTIALS_FILE = "client_secrets.json"
TOKEN_FILE = "token.json"


# ====================================================
# FUNÇÕES DE UTILIDADE E CONFIGURAÇÃO
# ====================================================

def run_cmd(cmd):
    """Executa comandos de shell (FFmpeg) e lida com erros."""
    clean = [arg.replace('\u00a0', ' ').strip() if isinstance(arg, str) else arg for arg in cmd if arg]
    st.info(f"Executando: {' '.join(clean)}", icon="💻")
    try:
        # Usa subprocess.run para capturar stdout e stderr
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
    # O formato ASS é &H00BBGGRR. O canal Alpha (AA) é ignorado aqui.
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}"

def load_config() -> Dict[str, Any]:
    """Carrega as configurações salvas de estilo de legenda."""
    default = {
        "f_size": 60, 
        "margin_v": 250, 
        "color": "#FFFF00", 
        "border": "#000000",
        "font_style": "Padrão (Arial)" # ou o caminho da fonte
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
        # Retorna o caminho absoluto do arquivo salvo
        return os.path.abspath(SAVED_FONT_FILE) 
    
    # Se for uma fonte padrão (como Arial, Helvetica, etc.), o FFmpeg tentará encontrá-la.
    # Para sistemas Windows/Linux/macOS que podem ter nomes de fontes padrão diferentes, 
    # é melhor usar o nome.
    return choice


# ====================================================
# FUNÇÕES DE INTEGRAÇÃO GOOGLE DRIVE / GAS
# ====================================================

@st.cache_resource(ttl=3600)
def get_drive_service() -> Optional[Any]:
    """Cria e retorna o serviço da API Google Drive."""
    creds = None
    
    # 1. Tenta carregar credenciais salvas (token.json)
    if os.path.exists(TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        except Exception as e:
            st.error(f"Erro ao carregar token.json: {e}")
            
    # 2. Se não houver credenciais válidas, tenta obter via Secrets (Streamlit Cloud)
    if not creds or not creds.valid:
        if "google_service_account" in st.secrets:
            # Lógica para Streamlit Cloud com Service Account (mais complexo para OAuth, mas comum)
            # Para OAuth em cloud, o método mais comum é forçar o login ou usar um Service Account.
            # Usando o padrão de carregamento de credenciais via arquivo JSON:
            try:
                # Se o JSON de credenciais do app web estiver no secrets
                secrets_content = st.secrets["google_service_account"]["credentials"]
                if not os.path.exists(CREDENTIALS_FILE):
                    with open(CREDENTIALS_FILE, "w") as f:
                        f.write(secrets_content)
            except:
                pass # Falha na extração de secrets
    
    # 3. Se ainda não há credenciais válidas, tenta o fluxo OAuth local (se houver client_secrets.json)
    if not creds or not creds.valid:
        if os.path.exists(CREDENTIALS_FILE):
            try:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
                    
                    # Usa o fluxo no terminal/navegador (pode ser problemático no Streamlit)
                    st.warning("Executando fluxo OAuth. Verifique o terminal para o link de autorização (se estiver rodando localmente).")
                    creds = flow.run_local_server(port=0)

                # Salva as credenciais para a próxima vez
                with open(TOKEN_FILE, 'w') as token:
                    token.write(creds.to_json())
            except Exception as e:
                st.error(f"Falha no fluxo OAuth. Certifique-se de que {CREDENTIALS_FILE} está correto e o ambiente local está configurado. Erro: {e}")
                return None
        else:
            st.warning("Nenhuma credencial Google Drive válida encontrada. Faça upload do `client_secrets.json` ou configure os `secrets`.")
            return None

    try:
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        st.error(f"Falha ao construir o serviço Drive: {e}")
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
        # Excluir vídeos que já têm a propriedade 'LEGENDADO: True'
        # Infelizmente, a busca por propriedades customizadas na API v3 é complexa
        # Simplesmente verificamos se o nome não contém a tag final
        query += " and not name contains '[LEGENDADO]'"

        results = service.files().list(
            q=query,
            fields="files(id, name, createdTime, properties)",
            pageSize=100
        ).execute()
        
        videos = results.get('files', [])
        
        # Filtro final manual (pode ser removido se a query for ajustada)
        final_videos = [v for v in videos if not '[LEGENDADO]' in v['name']]
        
        return final_videos
    except Exception as e:
        st.error(f"Erro ao listar vídeos prontos: {e}")
        return []

def download_video(service: Any, file_id: str, filename: str):
    """Baixa um arquivo do Google Drive."""
    request = service.files().get_media(fileId=file_id)
    fh = BytesIO()
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
# FUNÇÕES DE TRANSCRIPT E RE-ALINHAMENTO (CHAVE!)
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
        # Usa moviepy para extração de áudio mais confiável
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
            word_timestamps=True, # <--- CRUCIAL: Habilita timing por palavra
            verbose=False
        )
        
        segments = result.get('segments', [])
        
        # Limpeza do arquivo de áudio
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
    # Remove as tags de alto-falante e limpa múltiplos espaços
    clean_text = re.sub(r'--- [A-ZÁÉÕÇ ]+ ---\n', '', full_roteiro_text).strip()
    clean_text = re.sub(r'\s+', ' ', clean_text)
    perfect_words = clean_text.split()
    
    if not perfect_words or not segments:
        return ""

    # 2. Coletar todos os Timestamps de Palavra do Whisper
    whisper_words = []
    for seg in segments:
        # A biblioteca Whisper fornece 'words' apenas se word_timestamps=True for usado
        if 'words' in seg:
            for w in seg['words']:
                # O texto do Whisper pode ter espaços ou pontuação grudada, mas o timing é o que importa
                whisper_words.append({
                    'text': w['text'].strip(), 
                    'start': w['start'],
                    'end': w['end']
                })

    if not whisper_words:
        st.warning("Whisper não gerou timestamps de palavra. Verifique se a transcrição foi executada corretamente.")
        return ""

    # 3. Mapeamento e Geração do SRT em Blocos Curtos
    # Assumimos que a ordem das palavras do roteiro (perfect_words) é a mesma
    # da ordem dos timings de palavra do Whisper (whisper_words).
    
    min_len = min(len(perfect_words), len(whisper_words))
    
    srt_content = ""
    subtitle_index = 1
    i = 0 # Índice de Palavra
    
    while i < min_len:
        # Define o tamanho do bloco (máximo 4 palavras)
        block_size = min(4, min_len - i)
        
        # O bloco de texto é retirado do ROTEIRO PERFEITO (perfect_words)
        block_text = perfect_words[i : i + block_size]
        text_to_use = " ".join(block_text)
        
        # O timing é retirado do WHISPER_WORDS
        
        # Início do bloco é o 'start' da primeira palavra do bloco
        block_start = whisper_words[i]['start']
        
        # Fim do bloco é o 'end' da última palavra do bloco
        block_end = whisper_words[i + block_size - 1]['end']
        
        # Formatação SRT
        if text_to_use and block_end > block_start:
            start_str = format_timestamp(block_start)
            end_str = format_timestamp(block_end)
            
            srt_content += f"{subtitle_index}\n{start_str} --> {end_str}\n{text_to_use}\n\n"
            subtitle_index += 1
        
        i += block_size # Move o índice para o início do próximo bloco

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
        
        # 1. Salva o SRT gerado
        with open(srt_path, "w", encoding="utf-8") as f: 
            f.write(srt_content)
            
        # 2. Prepara os estilos ASS
        font_path = resolve_font(settings["font_style"])
        
        # Para FFmpeg, se a fonte for um arquivo TTF, precisamos garantir que ele use o nome
        # ou o caminho correto, dependendo da instalação.
        # Aqui, usamos o caminho absoluto se for um arquivo customizado.
        if settings["font_style"] == "Upload Personalizada" and os.path.exists(font_path):
            font_name_for_style = font_path # Usar o caminho completo
        else:
            font_name_for_style = settings["font_style"] # Usar o nome da fonte
            
        ass_c = hex_to_ass_color(settings["color"])
        ass_b = hex_to_ass_color(settings["border"])
        
        # Cria a string de estilo ASS, usando Outline=2 (Padrão)
        style = (
            f"Fontname={font_name_for_style},FontSize={settings['f_size']},PrimaryColour={ass_c},"
            f"OutlineColour={ass_b},BackColour=&H80000000,BorderStyle=1,Outline=2,Shadow=0,"
            f"Alignment=2,MarginV={settings['margin_v']}"
        )
        
        # 3. Comando FFmpeg
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
        # Limpeza temporária (mantemos o vídeo legendado aqui por enquanto)
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
            
            # Escolha da Fonte
            font_options = ["Padrão (Arial)", "Upload Personalizada"]
            
            font_choice = st.selectbox("Fonte:", font_options, index=font_options.index(current_settings["font_style"]) if current_settings["font_style"] in font_options else 0)
            
            if font_choice == "Upload Personalizada":
                font_file = st.file_uploader("Upload do arquivo .ttf/.otf", type=['ttf', 'otf'])
                if font_file:
                    with open(SAVED_FONT_FILE, "wb") as f:
                        f.write(font_file.getbuffer())
                    st.success("Fonte personalizada salva!")
            
            # Parâmetros de Estilo
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
            if st.session_state.drive_service:
                with st.spinner("Buscando vídeos..."):
                    st.session_state.videos_list = list_videos_ready(st.session_state.drive_service)
                    if not st.session_state.videos_list:
                         st.warning("Nenhum vídeo 'video_final_' sem tag '[LEGENDADO]' encontrado.")
        
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
                
                # Botão para Download
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
                            
                # Botão para buscar Roteiro
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

        # --- Exibição de Vídeo/Roteiro/SRT ---
        
        # 1. Player de Vídeo
        if st.session_state.current_video_path and os.path.exists(st.session_state.current_video_path):
            st.video(st.session_state.current_video_path)
        elif st.session_state.final_video_path and os.path.exists(st.session_state.final_video_path):
            st.video(st.session_state.final_video_path)
        else:
            st.info("Aguardando download de vídeo...")
            
        st.markdown("---")
        
        # 2. Geração do SRT (CRUCIAL)
        if st.session_state.current_video_path and st.session_state.roteiro_text:
            
            st.subheader("✨ Geração de Legenda Re-alinhada")
            
            if not WHISPER_AVAILABLE:
                st.error("O processamento de timing requer a biblioteca 'whisper'.")
            else:
                mod = st.radio("Modelo Whisper (Timing):", ["tiny", "base"], horizontal=True)
                
                if st.button("🚀 3. Gerar Legenda Re-alinhada (Correção de Sincronia)", type="primary"):
                    
                    with st.status("Iniciando Re-alinhamento...", expanded=True) as status:
                        
                        # --- ETAPA DE TIMING E RE-ALINHAMENTO ---
                        status.update(label=f"1. Transcrevendo áudio para TIMING (Modelo {mod})...")
                        # Usa a função que retorna os timestamps de palavra
                        segments = transcribe_audio_for_word_timing(st.session_state.current_video_path, mod)
                    
                    if segments:
                        with st.status("2. Mapeando Texto Perfeito para o Timing em Blocos Curtos...", expanded=True) as status:
                            # CHAMADA DA NOVA FUNÇÃO REVISADA QUE USA O TEXTO PERFEITO
                            srt_content = generate_perfect_srt_realigned(segments, st.session_state.roteiro_text)
                            st.session_state.srt_content = srt_content
                            status.update(label="SRT Gerado e Re-alinhado (Correção de Sincronia)!", state="complete")
                            st.success("Legenda Re-alinhada gerada com sucesso!")
                            st.rerun()

        # 3. Edição/Visualização do SRT
        if st.session_state.srt_content:
            st.subheader("✍️ SRT Gerado (Para Revisão)")
            st.session_state.srt_content = st.text_area(
                "Edite o SRT aqui:", 
                st.session_state.srt_content, 
                height=300
            )

        # 4. Renderização
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

            # 5. Upload Final
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
    # Cria diretórios temporários se não existirem
    if not os.path.exists("temp_download"): os.makedirs("temp_download")
    if not os.path.exists("temp_render"): os.makedirs("temp_render")
    
    # Limpeza de arquivos temporários ao iniciar a sessão (opcional, mas bom)
    # for f in os.listdir("temp_download"): os.remove(os.path.join("temp_download", f))
    # for f in os.listdir("temp_render"): os.remove(os.path.join("temp_render", f))
    
    main_app()
