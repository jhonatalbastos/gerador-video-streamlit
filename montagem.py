# app.py — Studio Jhonata (Versão Leve: Receptor & Fábrica de Vídeo)
# Features: Receptor de Jobs (Drive), Listagem de Pendentes, Edição de Assets, Overlay, Renderização FFmpeg.
import os
import re
import json
import time
import tempfile
import traceback
import subprocess
from io import BytesIO
from datetime import date, datetime # Importando datetime para manipulação de data
from typing import List, Optional, Tuple, Dict, Any
import base64
import shutil as _shutil # Import for rmtree

import requests
from PIL import Image, ImageDraw, ImageFont
import streamlit as st

# --- API Imports ---
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError 
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None 

# --- CONFIGURAÇÃO DE URL DO FRONTEND (AI STUDIO) ---
FRONTEND_AI_STUDIO_URL = "https://ai.studio/apps/drive/1gfrdHffzH67cCcZBJWPe6JfE1ZEttn6u"

# Force ffmpeg path for imageio if needed (Streamlit Cloud)
os.environ.setdefault("IMAGEIO_FFMPEG_EXE", "/usr/bin/ffmpeg")

# Arquivos de configuração persistentes
CONFIG_FILE = "overlay_config.json"
SAVED_MUSIC_FILE = "saved_bg_music.mp3"
MONETIZA_DRIVE_FOLDER_NAME = "Monetiza_Studio_Jobs"

# =========================
# Page config
# =========================
st.set_page_config(
    page_title="Studio Jhonata - Fábrica",
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
        "music_vol": 0.15,
        # Configurações de Legenda
        "sub_size": 50,
        "sub_color": "#FFFF00", 
        "sub_outline_color": "#000000",
        "sub_y_pos": 900 
    }

    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                saved = json.load(f)
                # Garante que os valores salvos de cor sejam strings hex válidas se existirem
                if 'sub_color' in saved and not saved['sub_color'].startswith('#'):
                     saved['sub_color'] = default_settings['sub_color']
                if 'sub_outline_color' in saved and not saved['sub_outline_color'].startswith('#'):
                     saved['sub_outline_color'] = default_settings['sub_outline_color']

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
# Google Drive API Client - lazy init
# =========================
_drive_service = None

def get_drive_service():
    global _drive_service
    # O novo sistema de leitura usa chaves separadas para evitar problemas de formatação JSON/TOML
    required_keys = [
        "type", "project_id", "private_key_id", "private_key",
        "client_email", "client_id", "auth_uri", "token_uri",
        "auth_provider_x509_cert_url", "client_x509_cert_url", "universe_domain"
    ]

    # Prefixos para as novas chaves no st.secrets
    prefix = "gcp_service_account_"

    if _drive_service is None:
        try:
            creds_info = {}
            missing_keys = []

            for key in required_keys:
                secret_key = prefix + key
                value = st.secrets.get(secret_key)

                if value is None:
                    # Verifica se a chave original existe se o novo formato falhar
                    original_secret = st.secrets.get("gcp_service_account")
                    if original_secret is None and prefix in secret_key:
                        missing_keys.append(key)
                else:
                    creds_info[key] = value

            if missing_keys:
                st.error(
                    f"❌ Erro de Configuração: As seguintes chaves de credenciais do Drive estão ausentes "
                    f"no Streamlit Secrets (use o prefixo '{prefix}'): {', '.join(missing_keys)}. "
                    f"Por favor, atualize o secrets.toml para o novo formato de múltiplas chaves."
                )
                st.stop()

            # Todas as chaves foram reunidas em creds_info
            creds = service_account.Credentials.from_service_account_info(
                creds_info,
                scopes=['https://www.googleapis.com/auth/drive.readonly']
            )
            _drive_service = build('drive', 'v3', credentials=creds)
            st.success("✅ Google Drive API inicializada com sucesso!")
        except Exception as e:
            st.error(f"❌ Erro ao inicializar Google Drive API: {e}. Verifique as credenciais da conta de serviço e permissões.")
            st.stop()
    return _drive_service

# =========================
# FUNÇÕES DE ÁUDIO & VÍDEO & IMAGEM (Auxiliares)
# =========================

def get_resolution_params(choice: str) -> dict:
    if "9:16" in choice:
        return {"w": 720, "h": 1280, "ratio": "9:16"}
    elif "16:9" in choice:
        return {"w": 1280, "h": 720, "ratio": "16:9"}
    else: # 1:1
        return {"w": 1024, "h": 1024, "ratio": "1:1"}

# =========================
# Google Drive Functions
# =========================
def find_file_in_drive_folder(service, file_name: str, folder_name: str) -> Optional[str]:
    """Busca um arquivo específico dentro de uma pasta no Google Drive."""
    try:
        # 1. Encontrar o ID da pasta "Monetiza_Studio_Jobs"
        query_folder = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        folders = service.files().list(q=query_folder, fields="files(id)").execute().get('files', [])

        if not folders:
            st.error(f"❌ Pasta '{folder_name}' não encontrada no Drive. Certifique-se de que o frontend já fez o upload de um job.")
            return None

        folder_id = folders[0]['id']
        st.info(f"✅ Pasta '{folder_name}' encontrada com ID: {folder_id}")

        # 2. Buscar o arquivo JSON dentro da pasta
        query_file = f"name = '{file_name}' and mimeType = 'application/json' and '{folder_id}' in parents and trashed = false"
        files = service.files().list(q=query_file, fields="files(id, name)").execute().get('files', [])

        if files:
            st.info(f"✅ Arquivo '{file_name}' encontrado no Drive.")
            return files[0]['id']
        else:
            st.warning(f"⚠️ Arquivo '{file_name}' não encontrado na pasta '{folder_name}'.")
            return None
    except HttpError as error:
        st.error(f"❌ Erro ao buscar arquivo no Google Drive: {error}")
        return None
    except Exception as e:
        st.error(f"❌ Erro inesperado ao buscar arquivo no Google Drive: {e}")
        return None

def download_file_content(service, file_id: str, silent: bool = False) -> Optional[str]:
    """Baixa o conteúdo de um arquivo do Google Drive."""
    try:
        request = service.files().get_media(fileId=file_id)
        content = request.execute().decode('utf-8')
        if not silent:
            st.info(f"✅ Conteúdo do arquivo '{file_id}' baixado com sucesso.")
        return content
    except HttpError as error:
        if not silent:
            st.error(f"❌ Erro ao baixar conteúdo do arquivo {file_id}: {error}")
        return None
    except Exception as e:
        if not silent:
            st.error(f"❌ Erro inesperado ao baixar conteúdo: {e}")
        return None

def list_recent_jobs(limit: int = 10) -> List[Dict]:
    """Lista os jobs recentes na pasta do Drive, extraindo data e categoria."""
    service = get_drive_service()
    if not service: return []

    jobs_list = []
    
    try:
        # 1. Encontrar ID da pasta
        query_folder = f"name = '{MONETIZA_DRIVE_FOLDER_NAME}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        folders = service.files().list(q=query_folder, fields="files(id)").execute().get('files', [])
        
        if not folders:
            st.error(f"Pasta '{MONETIZA_DRIVE_FOLDER_NAME}' não encontrada.")
            return []
        
        folder_id = folders[0]['id']

        # 2. Listar arquivos JSON mais recentes
        query_file = f"mimeType = 'application/json' and '{folder_id}' in parents and trashed = false"
        # Ordenar por data de criação decrescente
        results = service.files().list(q=query_file, orderBy="createdTime desc", pageSize=limit, fields="files(id, name, createdTime)").execute()
        files = results.get('files', [])

        if not files:
            return []

        # 3. Ler cada arquivo para extrair metadados (Data e Ref)
        with st.spinner(f"Lendo os {len(files)} jobs mais recentes..."):
            for f in files:
                content = download_file_content(service, f['id'], silent=True)
                if content:
                    try:
                        data_json = json.loads(content)
                        meta = data_json.get("meta_dados", {})
                        ref_full = meta.get("ref", "S/ Ref")
                        data_liturgia = meta.get("data", "S/ Data")
                        
                        # Tenta inferir categoria simplificada
                        categoria = "Outros"
                        ref_lower = ref_full.lower()
                        if "salmo" in ref_lower or "sl" in ref_lower:
                            categoria = "Salmo"
                        elif any(x in ref_lower for x in ["mt", "mc", "lc", "jo", "mateus", "marcos", "lucas", "joão"]):
                            categoria = "Evangelho"
                        elif "leitura" in ref_lower:
                            categoria = "Leitura"
                        
                        # Extrai o Job ID limpo do nome do arquivo
                        # Nome padrão: job_data_JOB-UUID.json
                        job_id_clean = f['name'].replace("job_data_", "").replace(".json", "")

                        jobs_list.append({
                            "display": f"{data_liturgia} | {categoria} | {ref_full}",
                            "job_id": job_id_clean,
                            "data": data_liturgia,
                            "categoria": categoria,
                            "ref": ref_full,
                            "file_id": f['id']
                        })
                    except:
                        continue
                        
    except Exception as e:
        st.error(f"Erro ao listar jobs: {e}")
        return []
        
    return jobs_list

def load_job_from_drive(job_id: str) -> Optional[Dict[str, Any]]:
    """Carrega um job payload completo do Google Drive usando o Job ID."""
    service = get_drive_service()
    if not service:
        return None

    file_name = f"job_data_{job_id}.json"
    file_id = find_file_in_drive_folder(service, file_name, MONETIZA_DRIVE_FOLDER_NAME)

    if file_id:
        json_content = download_file_content(service, file_id)
        if json_content:
            try:
                payload = json.loads(json_content)
                st.success(f"✅ Job '{job_id}' carregado do Google Drive!")
                return payload
            except json.JSONDecodeError as e:
                st.error(f"❌ Erro ao decodificar JSON do job: {e}")
                return None
        else:
            st.error(f"❌ Conteúdo JSON do job '{job_id}' está vazio.")
            return None
    return None

def process_job_payload_and_update_state(payload: Dict[str, Any], temp_dir: str):
    """
    Processa o payload do job, decodifica assets e atualiza o Streamlit session state.
    Retorna True em caso de sucesso, False em caso de falha.
    """
    try:
        # The frontend sends 'roteiro' with nested objects like {hook: {text: ..., prompt: ...}}
        st.session_state["roteiro_gerado"] = payload.get("roteiro", {})
        
        # Carrega metadados iniciais
        meta_recebido = payload.get("meta_dados", {"data": "", "ref": ""})
        data_string = meta_recebido.get("data", "")
        ref_string = meta_recebido.get("ref", "")
        
        # --- CORREÇÃO: Formatação da data para dd.mm.aaaa ---
        formatted_date = data_string
        try:
            # Tenta interpretar a data em formatos comuns (AAAA-MM-DD ou DD.MM.AAAA)
            if re.match(r"\d{4}-\d{2}-\d{2}", data_string):
                dt_obj = datetime.strptime(data_string, '%Y-%m-%d')
                formatted_date = dt_obj.strftime('%d.%m.%Y')
            elif re.match(r"\d{2}\.\d{2}\.\d{4}", data_string):
                pass # Já está no formato correto (DD.MM.AAAA)
            elif re.match(r"\d{4}\.\d{2}\.\d{2}", data_string):
                dt_obj = datetime.strptime(data_string, '%Y.%m.%d')
                formatted_date = dt_obj.strftime('%d.%m.%Y')
        except ValueError:
            st.warning(f"Não foi possível formatar a data '{data_string}'. Usando string bruta.")
        # ----------------------------------------------------

        # Sobrescreve ao carregar um novo job para garantir que os dados batam com o arquivo.
        st.session_state["meta_dados"] = meta_recebido
        st.session_state["data_display"] = formatted_date # Preenche com a data formatada
        st.session_state["ref_display"] = ref_string      # Preenche com a referência bruta

        st.session_state["generated_images_blocks"] = {} # Stores file paths to temp files
        st.session_state["generated_audios_blocks"] = {} # Stores file paths to temp files
        st.session_state["generated_srt_content"] = "" # Stores raw SRT string

        assets = payload.get("assets", [])
        for asset in assets:
            block_id = asset.get("block_id")
            asset_type = asset.get("type")
            data_b64 = asset.get("data_b64")

            if not block_id or not asset_type or not data_b64:
                st.warning(f"⚠️ Asset com dados incompletos, ignorando: {asset}")
                continue

            decoded_data = base64.b64decode(data_b64)

            # --- DEBUGGING: Verificar se o arquivo decodificado tem 0 bytes ---
            if len(decoded_data) == 0:
                 st.error(f"❌ O asset {block_id} ({asset_type}) chegou vazio ou corrompido (0 bytes).")
                 continue # Pula este asset corrompido

            if asset_type == "image":
                file_path = os.path.join(temp_dir, f"{block_id}.png")
                with open(file_path, "wb") as f:
                    f.write(decoded_data)
                st.session_state["generated_images_blocks"][block_id] = file_path # Store path

            # SALVA COMO .WAV PARA COMPATIBILIDADE FFMPEG
            elif asset_type == "audio":
                file_path = os.path.join(temp_dir, f"{block_id}.wav")
                with open(file_path, "wb") as f:
                    f.write(decoded_data)
                st.session_state["generated_audios_blocks"][block_id] = file_path # Store path

            elif asset_type == "srt" and block_id == "legendas":
                srt_content = decoded_data.decode('utf-8')
                st.session_state["generated_srt_content"] = srt_content

        st.success("✅ Assets decodificados (Audio como WAV) e estado atualizado!")
        return True
    except Exception as e:
        st.error(f"❌ Erro ao processar payload do job: {e}")
        return False


# =========================
# Helpers
# =========================
def shutil_which(bin_name: str) -> Optional[str]:
    return _shutil.which(bin_name)

def run_cmd(cmd: List[str]):
    # CORREÇÃO FFmpeg: Limpa argumentos de caracteres invisíveis (\u00a0)
    cleaned_cmd = []
    for arg in cmd:
        if isinstance(arg, str):
            cleaned_arg = arg.replace('\u00a0', ' ').strip()
            if cleaned_arg:
                cleaned_cmd.append(cleaned_arg)
        else:
            cleaned_cmd.append(arg)

    try:
        subprocess.run(cleaned_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""
        raise RuntimeError(f"Comando falhou: {' '.join(cleaned_cmd)}\nSTDERR: {stderr}")

def get_audio_duration_seconds(audio_path: str) -> Optional[float]:
    """Obtém a duração de um áudio a partir do caminho do arquivo."""
    if not shutil_which("ffprobe"):
        st.warning("⚠️ ffprobe não encontrado! A duração do áudio pode ser imprecisa.")
        return 5.0

    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", audio_path]
    try:
        p = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out = p.stdout.decode().strip()
        return float(out) if out else None
    except Exception:
        # Nota: O erro "could not find codec parameters" faz o ffprobe falhar, retornando 5.0 como fallback
        st.error(f"Erro ao obter duração do áudio com ffprobe para {os.path.basename(audio_path)}.")
        return 5.0 
    finally:
        pass


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
    # CORREÇÃO: Usar dupla barra invertida (\\) para escapar o caractere no comando FFmpeg
    t = text.replace(":", "\\:").replace("'", "")
    return t

# NOVO: Função para gerar legendas com Whisper
def gerar_legendas_whisper(audio_path: str):
    """
    Gera legendas SRT usando a API Whisper da OpenAI para um arquivo de áudio.
    Requer a chave OPENAI_API_KEY no Streamlit Secrets.
    """
    openai_key = st.secrets.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not openai_key:
        st.error("❌ Chave OPENAI_API_KEY não configurada no Streamlit Secrets.")
        return None
    
    try:
        client = OpenAI(api_key=openai_key)
        
        st.write(f"Enviando áudio ({os.path.basename(audio_path)}) para a API Whisper...")

        with open(audio_path, "rb") as audio_file:
            # O Whisper gera automaticamente o SRT (ou VTT)
            # response_format="srt" é crucial para obter o formato desejado
            # language="pt" ajuda na precisão
            transcript = client.audio.transcriptions.create(
                model="whisper-1", 
                file=audio_file, 
                response_format="srt",
                language="pt"
            )
        
        # O resultado é uma string SRT
        return transcript
        
    except Exception as e:
        st.error(f"❌ Erro ao gerar legendas com Whisper: {e}")
        st.error("Verifique se o arquivo de áudio não está vazio e se sua chave OpenAI está válida.")
        return None

# =========================
# Interface principal
# =========================
st.title("🏭 Fábrica de Vídeos Litúrgicos")
st.caption("Recepção de Jobs do Drive & Montagem Final")
st.markdown("---")

# ---- SIDEBAR CONFIG ----
st.sidebar.title("⚙️ Configurações")

# Resolução agora é mais visual para o usuário
resolucao_escolhida = st.sidebar.selectbox("📏 Resolução de Saída", ["9:16 (Vertical/Stories)", "16:9 (Horizontal/YouTube)", "1:1 (Quadrado/Feed)"], index=0)

st.sidebar.markdown("---")
st.sidebar.markdown("### 🅰️ Upload de Fonte (Global)")
uploaded_font_file = st.sidebar.file_uploader("Arquivo .ttf (para opção 'Upload Personalizada')", type=["ttf"])

st.sidebar.info(f"Formato Saída: {resolucao_escolhida}")

# session state
if "roteiro_gerado" not in st.session_state:
    st.session_state["roteiro_gerado"] = None
if "generated_images_blocks" not in st.session_state:
    st.session_state["generated_images_blocks"] = {}
if "generated_audios_blocks" not in st.session_state:
    st.session_state["generated_audios_blocks"] = {}
if "generated_srt_content" not in st.session_state:
    st.session_state["generated_srt_content"] = ""
if "video_final_bytes" not in st.session_state:
    st.session_state["video_final_bytes"] = None
if "meta_dados" not in st.session_state:
    st.session_state["meta_dados"] = {"data": "", "ref": ""}
# Novos campos para edição manual dos metadados
if "data_display" not in st.session_state:
    st.session_state["data_display"] = ""
if "ref_display" not in st.session_state:
    st.session_state["ref_display"] = ""
if "lista_jobs" not in st.session_state:
    st.session_state["lista_jobs"] = []

if "job_loaded_from_drive" not in st.session_state:
    st.session_state["job_loaded_from_drive"] = False
if "temp_assets_dir" not in st.session_state:
    st.session_state["temp_assets_dir"] = None

# Carregar Settings persistentes
if "overlay_settings" not in st.session_state:
    st.session_state["overlay_settings"] = load_config()

# Abas Simplificadas (Removendo a aba iFrame)
tab1, tab2, tab3 = st.tabs(
    ["📥 Receber Job (Drive)", "🎚️ Overlay & Ajustes", "🎥 Renderizar Vídeo"]
)

# --------- TAB 1: RECEBER JOB ----------
with tab1:
    st.header("📥 Central de Recepção de Jobs")
    
    # NOVO: Adiciona o link direto para o Frontend do AI Studio
    st.markdown(f"""
        **Crie seu Job:** [Clique aqui para ir para o Frontend AI Studio]({FRONTEND_AI_STUDIO_URL})
    """)
    
    col_list, col_input = st.columns([1.5, 1])
    
    with col_list:
        st.subheader("Jobs Pendentes no Drive")
        if st.button("🔄 Atualizar Lista de Jobs"):
            with st.spinner("Buscando jobs recentes no Drive..."):
                jobs = list_recent_jobs(15) # Busca os 15 mais recentes
                st.session_state['lista_jobs'] = jobs
        
        if 'lista_jobs' in st.session_state and st.session_state['lista_jobs']:
            # Cria um seletor amigável
            job_options = {job['display']: job['job_id'] for job in st.session_state['lista_jobs']}
            selected_display = st.selectbox(
                "Selecione um Job para carregar:", 
                options=list(job_options.keys())
            )
            
            if st.button("📂 Carregar Job Selecionado"):
                selected_id = job_options[selected_display]
                # Preenche o input e dispara o carregamento
                st.session_state['drive_job_id_input'] = selected_id
                st.rerun() # Recarrega para processar no bloco abaixo
        else:
            st.info("Clique em atualizar para ver os jobs disponíveis.")

    with col_input:
        st.subheader("Carregar por ID")
        job_id_input = st.text_input("Job ID:", key="drive_job_id_input", placeholder="Ex: JOB-51f35776...")
        
        if st.button("Buscar e Carregar", type="primary", disabled=not job_id_input):
            if job_id_input:
                with st.status(f"Buscando job '{job_id_input}'...", expanded=True) as status_box:
                    # Clean up previous temp dir if exists
                    if st.session_state.get("temp_assets_dir") and os.path.exists(st.session_state["temp_assets_dir"]):
                        _shutil.rmtree(st.session_state["temp_assets_dir"])
                        st.write(f"Cache limpo.")

                    temp_assets_dir = tempfile.mkdtemp()
                    st.write(f"Área temporária criada.")

                    payload = load_job_from_drive(job_id_input)
                    if payload:
                        st.write("Baixando assets...")
                        if process_job_payload_and_update_state(payload, temp_assets_dir):
                            st.session_state["job_loaded_from_drive"] = True
                            st.session_state["temp_assets_dir"] = temp_assets_dir
                            status_box.update(label=f"✅ Job '{job_id_input}' carregado com sucesso!", state="complete")
                            time.sleep(1)
                            st.rerun()
                        else:
                            status_box.update(label="❌ Erro ao processar os arquivos do job.", state="error")
                            _shutil.rmtree(temp_assets_dir)
                            st.session_state["temp_assets_dir"] = None
                    else:
                        status_box.update(label="❌ Falha ao encontrar/baixar o job.", state="error")
                        _shutil.rmtree(temp_assets_dir)
                        st.session_state["temp_assets_dir"] = None
    
    st.divider()
    if st.session_state["job_loaded_from_drive"]:
        st.success("JOB ATIVO")
        col_meta1, col_meta2 = st.columns(2)
        with col_meta1:
            st.markdown(f"**Data Original:** {st.session_state['meta_dados'].get('data')}")
        with col_meta2:
            st.markdown(f"**Ref Original:** {st.session_state['meta_dados'].get('ref')}")
        
        st.subheader("📝 Editar Informações do Overlay")
        st.caption("Caso os dados vindos do Drive estejam incorretos, corrija aqui antes de renderizar.")
        
        c1, c2 = st.columns(2)
        with c1:
            new_date = st.text_input("Data (Ex: 01.12.2025)", value=st.session_state.get("data_display", ""), key="input_data_display")
            if new_date != st.session_state.get("data_display"):
                st.session_state["data_display"] = new_date
                st.session_state["meta_dados"]["data"] = new_date # Atualiza a fonte também
                
        with c2:
            new_ref = st.text_input("Referência (Ex: Mateus 8, 5-11)", value=st.session_state.get("ref_display", ""), key="input_ref_display")
            if new_ref != st.session_state.get("data_display"):
                st.session_state["ref_display"] = new_ref
                st.session_state["meta_dados"]["ref"] = new_ref # Atualiza a fonte também


# --------- TAB 2: OVERLAY & EFEITOS ----------
with tab2:
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

        # NOVO: Configurações de Legendas
        with st.expander("📝 Ajustes de Legendas", expanded=True):
            ov_sets["sub_size"] = st.slider("Tamanho da Fonte", 20, 100, ov_sets.get("sub_size", 50), key="sub_s")
            # CORREÇÃO: Usando valores HEX para o color picker
            ov_sets["sub_color"] = st.color_picker("Cor da Legenda", ov_sets.get("sub_color", "#FFFF00"), key="sub_c") 
            ov_sets["sub_outline_color"] = st.color_picker("Cor da Sombra/Borda", ov_sets.get("sub_outline_color", "#000000"), key="sub_o")
            # NOVO: Posição Y da Legenda
            ov_sets["sub_y_pos"] = st.slider("Posição Vertical Y", 600, 1200, ov_sets.get("sub_y_pos", 900), help="Posição em pixels na tela (1280 é o limite inferior para 9:16)")


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

        # Usa os valores de display (editáveis)
        txt_l1 = "EVANGELHO" 
        txt_l2 = st.session_state.get("data_display", "01.01.2025")
        txt_l3 = st.session_state.get("ref_display", "Mateus 1, 1-1")

        preview_texts = [ 
            {"text": txt_l1, "size": int(ov_sets["line1_size"] * text_scale), "y": int(ov_sets["line1_y"] * text_scale), "font_style": ov_sets["line1_font"], "color": "white"},
            {"text": txt_l2, "size": int(ov_sets["line2_size"] * text_scale), "y": int(ov_sets["line2_y"] * text_scale), "font_style": ov_sets["line2_font"], "color": "white"},
            {"text": txt_l3, "size": int(ov_sets["line3_size"] * text_scale), "y": int(ov_sets["line3_y"] * text_scale), "font_style": ov_sets["line3_font"], "color": "white"},
        ]

        prev_img = criar_preview_overlay(preview_w, preview_h, preview_texts, uploaded_font_file) 
        st.image(prev_img, caption=f"Preview Overlay em {resolucao_escolhida}", use_column_width=False)


# --------- TAB 3: RENDERIZAR VÍDEO ----------
with tab3:
    st.header("🎥 Fábrica de Vídeo")

    if not st.session_state.get("roteiro_gerado"):
        st.warning("⚠️ Nenhum job carregado. Por favor, carregue um Job ID na aba 1.")
        st.stop()

    roteiro = st.session_state["roteiro_gerado"]

    blocos_config = [
        {"id": "hook", "label": "🎣 HOOK", "text_path": "hook", "prompt_path": "hook"},
        {"id": "leitura", "label": "📖 LEITURA", "text_path": "leitura", "prompt_path": "leitura"},
        {"id": "reflexao", "label": "💭 REFLEXÃO", "text_path": "reflexao", "prompt_path": "reflexao"},
        {"id": "aplicacao", "label": "🌟 APLICAÇÃO", "text_path": "aplicacao", "prompt_path": "aplicacao"},
        {"id": "oracao", "label": "🙏 ORAÇÃO", "text_path": "oracao", "prompt_path": "oracao"},
    ]

    st.subheader("🛠️ Revisão e Substituição de Arquivos")
    st.caption("Verifique os assets recebidos. Se algum estiver ruim, faça upload de um substituto.")

    for bloco in blocos_config:
        block_id = bloco["id"]
        with st.container(border=True):
            st.subheader(bloco["label"])
            col_text, col_media = st.columns([1, 1.2])
            with col_text:
                txt_content = roteiro.get(bloco["text_path"], {}).get("text", "")
                st.caption("📜 Texto para Narração:")
                st.markdown(f"_{txt_content[:250]}..._" if txt_content else "_Sem texto_")

                # Exibe Audio Atual
                audio_path_display = st.session_state["generated_audios_blocks"].get(block_id)
                if audio_path_display and os.path.exists(audio_path_display):
                    st.audio(audio_path_display, format="audio/wav")
                else:
                    st.warning("Áudio não encontrado.")

                # Upload substituição Audio
                new_audio = st.file_uploader(f"Substituir Áudio ({block_id})", type=["mp3", "wav"], key=f"up_aud_{block_id}")
                if new_audio:
                    if st.session_state.get("temp_assets_dir"):
                        # Salva como .wav para consistência
                        save_path = os.path.join(st.session_state["temp_assets_dir"], f"{block_id}_manual.wav")
                        with open(save_path, "wb") as f:
                            f.write(new_audio.read())
                        st.session_state["generated_audios_blocks"][block_id] = save_path
                        st.success("Áudio substituído!")
                        st.rerun()

            with col_media:
                st.caption("🖼️ Imagem da Cena:")
                img_path_display = st.session_state["generated_images_blocks"].get(block_id)
                if img_path_display and os.path.exists(img_path_display):
                    try:
                        st.image(img_path_display, use_column_width=True)
                    except Exception:
                        st.error("Erro ao exibir imagem.")
                else:
                    st.info("Nenhuma imagem definida.")

                # Upload substituição Imagem
                new_img = st.file_uploader(f"Substituir Imagem ({block_id})", type=["png", "jpg", "jpeg"], key=f"up_img_{block_id}")
                if new_img:
                    if st.session_state.get("temp_assets_dir"):
                        save_path = os.path.join(st.session_state["temp_assets_dir"], f"{block_id}_manual.png")
                        with open(save_path, "wb") as f:
                            f.write(new_img.read())
                        st.session_state["generated_images_blocks"][block_id] = save_path
                        st.success("Imagem substituída!")
                        st.rerun()

    st.divider()
    st.header("🎬 Finalização")
    usar_overlay = st.checkbox("Adicionar Cabeçalho (Overlay Personalizado)", value=True)
    
    # Checkbox para Legendas (NOVO)
    usar_legendas = st.checkbox("Adicionar Legendas (SRT)", value=False, disabled=(not st.session_state.get("generated_srt_content")))


    st.subheader("🎵 Música de Fundo (Opcional)")

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

    if st.session_state.get("generated_srt_content"):
        st.subheader("📄 Legendas (SRT)")
        st.code(st.session_state["generated_srt_content"], language="srt")
        if st.download_button("⬇️ Baixar SRT", st.session_state["generated_srt_content"], "legendas.srt", "text/plain"):
            pass
            
    # NOVO: Botão para gerar legendas via Whisper
    col_whisper, col_info = st.columns([1, 2])
    with col_whisper:
        if st.button("🎤 Gerar Legendas (Whisper API)", disabled=not st.session_state.get("job_loaded_from_drive")):
            
            # Requisito: Precisamos do áudio final concatenado (temp_video.mp4) para o Whisper
            if st.session_state.get("temp_assets_dir"):
                
                # 1. Concatena os áudios individuais em um WAV mestre para o Whisper (mais estável)
                with st.status("Combinando áudios para o Whisper...", expanded=True) as status_whisper: # Cria um novo bloco de status
                    
                    audio_paths = [path for path in st.session_state["generated_audios_blocks"].values() if os.path.exists(path)]
                    
                    if not audio_paths:
                        status_whisper.update(label="❌ Nenhum arquivo de áudio válido encontrado para transcrever.", state="error")
                        st.stop()
                        
                    # Cria um arquivo de lista para concatenação dos WAVs
                    concat_list_audio = os.path.join(st.session_state["temp_assets_dir"], "list_audio.txt")
                    with open(concat_list_audio, "w") as f:
                        for p in audio_paths:
                            f.write(f"file '{p}'\n")

                    master_audio_path = os.path.join(st.session_state["temp_assets_dir"], "master_audio.wav")
                    
                    # Concatena os streams de áudio em um único arquivo WAV de referência
                    cmd_concat_audio = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list_audio, "-c:a", "pcm_s16le", master_audio_path]
                    
                    try:
                        run_cmd(cmd_concat_audio)
                        status_whisper.update(label="Áudio mestre concatenado com sucesso.", expanded=False)
                        
                        # 2. Chama a API Whisper
                        status_whisper.update(label="Transcrevendo áudio com Whisper API (pode levar tempo)...", expanded=True)
                        new_srt_content = gerar_legendas_whisper(master_audio_path)
                        
                        if new_srt_content:
                            st.session_state["generated_srt_content"] = new_srt_content
                            status_whisper.update(label="✅ Legendas geradas com sucesso via Whisper!", state="complete")
                            st.rerun()
                        else:
                            status_whisper.update(label="❌ Falha na transcrição do Whisper.", state="error")
                        
                    except Exception as e:
                        status_whisper.update(label="❌ Erro na Concatenação de Áudio para Whisper.", state="error")
                        st.error(f"Detalhes: {e}")
                    
            else:
                st.warning("Carregue um Job ID primeiro para ter os áudios disponíveis.")
    with col_info:
        if st.session_state.get("generated_srt_content"):
            st.info("SRT carregado. O Whisper API é recomendado para máxima precisão de sincronismo, superando o cálculo de duração por bloco.")

    st.markdown("---")
    if st.button("Renderizar Vídeo Completo (Unir tudo)", type="primary"):
        with st.status("Renderizando vídeo com efeitos...", expanded=True) as status:
            temp_dir_render = None
            try:
                if not shutil_which("ffmpeg"):
                    status.update(label="FFmpeg não encontrado!", state="error")
                    st.stop()

                temp_dir_render = tempfile.mkdtemp()
                clip_files = []
                srt_path_final = None # Inicializa o caminho do SRT

                font_path = resolve_font_path(st.session_state["overlay_settings"]["line1_font"], uploaded_font_file)
                if usar_overlay and not font_path:
                    st.warning("⚠️ Fonte não encontrada. O overlay pode falhar.")
                
                # Prepara o arquivo SRT se a opção for marcada
                if usar_legendas and st.session_state.get("generated_srt_content"):
                    srt_path_final = os.path.join(temp_dir_render, "legendas.srt")
                    # Usando 'utf-8' para garantir que caracteres especiais funcionem no FFmpeg (assumes font support)
                    with open(srt_path_final, "w", encoding="utf-8") as f: 
                        f.write(st.session_state["generated_srt_content"])
                    st.write("✅ Arquivo SRT criado para renderização.")

                # Usa os dados de display que podem ter sido editados
                txt_dt = st.session_state.get("data_display", "")
                txt_ref = st.session_state.get("ref_display", "")

                map_titulos = {"hook": "EVANGELHO", "leitura": "EVANGELHO", "reflexao": "REFLEXÃO", "aplicacao": "APLICAÇÃO", "oracao": "ORAÇÃO"}

                res_params = get_resolution_params(resolucao_escolhida)
                s_out = f"{res_params['w']}x{res_params['h']}"

                sets = st.session_state["overlay_settings"]
                speed_val = sets["effect_speed"] * 0.0005

                zoom_expr = None

                # Expressões de movimento Ken Burns e Panorâmica
                if sets["effect_type"] == "Zoom In (Ken Burns)":
                    # Expressão FFmpeg: z='min(1 + speed*on, 1.5)':x='...':y='...':d=frames:s=size:fps=25
                    zoom_expr_content = f"min(zoom+{speed_val},1.5):x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                elif sets["effect_type"] == "Zoom Out":
                    zoom_expr_content = f"max(1,1.5-{speed_val}*on):x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                elif sets["effect_type"] == "Panorâmica Esquerda":
                    zoom_expr_content = f"1.2:x='min(x+{speed_val}*100,iw-iw/zoom)':y='(ih-ih/zoom)/2'"
                elif sets["effect_type"] == "Panorâmica Direita":
                    zoom_expr_content = f"1.2:x='max(0,x-{speed_val}*100)':y='(ih-ih/zoom)/2'"
                else:
                    zoom_expr_content = "1:x=0:y=0" # Estático

                for b in blocos_config:
                    bid = b["id"]
                    img_path = st.session_state["generated_images_blocks"].get(bid)
                    audio_path = st.session_state["generated_audios_blocks"].get(bid)

                    if not img_path or not audio_path or not os.path.exists(img_path) or not os.path.exists(audio_path):
                        st.warning(f"⚠️ Ignorando bloco '{bid}' na renderização devido a imagem ou áudio ausente/inválido.")
                        continue

                    st.write(f"Processando clipe: {bid}...")
                    clip_path = os.path.join(temp_dir_render, f"{bid}_clip.mp4")

                    dur = get_audio_duration_seconds(audio_path) or 5.0
                    frames = int(dur * 25)

                    vf_filters = []
                    
                    # Aplica zoompan com FPS forçado para suavizar o movimento
                    if sets["effect_type"] != "Estático (Sem movimento)":
                        # Injeta zoom_expr_content e garante o FPS e Size para saída suave
                        # Usando a sintaxe limpa do zoom_expr_content, sem aspas extras na injeção.
                        zoom_pan_params = f"z={zoom_expr_content},d={frames},s={s_out},fps=25" 
                        vf_filters.append(f"zoompan={zoom_pan_params}")
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

                    cmd = ["ffmpeg", "-y", "-loop", "1", "-i", img_path, "-i", audio_path, "-vf", filter_complex, "-c:v", "libx264", "-t", f"{dur}", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", clip_path]
                    run_cmd(cmd)
                    clip_files.append(clip_path)

                if clip_files:
                    concat_list = os.path.join(temp_dir_render, "list.txt")
                    with open(concat_list, "w") as f:
                        for p in clip_files: f.write(f"file '{p}'\n")

                    temp_video = os.path.join(temp_dir_render, "temp_video.mp4")
                    
                    # 1. Concatena clipes
                    run_cmd(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list, "-c", "copy", temp_video])

                    final_path = os.path.join(temp_dir_render, "final.mp4")
                    
                    # 2. Lógica de Mixagem e Legendas
                    
                    input_mix = ["-i", temp_video]
                    filter_complex_parts = []
                    
                    # Adiciona música de fundo
                    music_source_path = None
                    if music_upload:
                        music_source_path = os.path.join(temp_dir_render, "bg.mp3")
                        with open(music_source_path, "wb") as f: f.write(music_upload.getvalue())
                    elif saved_music_exists:
                        music_source_path = SAVED_MUSIC_FILE
                    
                    if music_source_path:
                        # Input da música é sempre o próximo índice livre, que é 1
                        input_mix.extend(["-stream_loop", "-1", "-i", music_source_path]) 
                        # A música tem o volume ajustado, depois é mixada com o áudio original [0:a].
                        filter_audio_mix = f"[1:a]volume={music_vol}[bg];[0:a][bg]amix=inputs=2:duration=first:dropout_transition=2[a_out]"
                        filter_complex_parts.append(filter_audio_mix)
                    else:
                        # Se não há música, o stream de áudio final [a_out] é apenas o stream de áudio original [0:a]
                        filter_audio_mix = "[0:a]copy[a_out]"
                        filter_complex_parts.append(filter_audio_mix) # Garantir que [a_out] é definido
                        
                    # Adiciona legendas (subtitles)
                    if usar_legendas and srt_path_final and os.path.exists(srt_path_final):
                        
                        # --- CONFIGURAÇÃO DE ESTILO ASS/SRT NO FFmpeg ---
                        # Converte cores Hex para BGR (formato libass/FFmpeg)
                        def hex_to_bgr(hex_color):
                            # Remove #, garante 6 caracteres e converte para BGR
                            hex_color = hex_color.lstrip('#')
                            r = int(hex_color[0:2], 16)
                            g = int(hex_color[2:4], 16)
                            b = int(hex_color[4:6], 16)
                            return f"&H{b:02X}{g:02X}{r:02X}"

                        primary_color = hex_to_bgr(sets.get("sub_color", "#FFFF00")) # Cor principal (Amarelo)
                        outline_color = hex_to_bgr(sets.get("sub_outline_color", "#000000")) # Cor da borda/sombra (Preto)
                        
                        # Define os estilos de legenda para o filtro subtitles/libass
                        ass_style_params = (
                            f"FontName=Arial,"
                            f"FontSize={sets['sub_size']},"
                            f"PrimaryColour={primary_color},"  # Cor da legenda
                            f"OutlineColour={outline_color}," # Cor da borda
                            f"Outline=2.5,"                    
                            f"Shadow=0,"                       
                            f"Alignment=2,"                    
                            f"MarginV={res_params['h'] - sets['sub_y_pos']}" 
                        )

                        # Aplica o filtro de legenda no stream de vídeo original [0:v] e nomeia [v_out]
                        filter_video_mix = f"[0:v]subtitles='{srt_path_final}':force_style='{ass_style_params}'[v_out]"
                        filter_complex_parts.append(filter_video_mix)
                    else:
                        # Se não há legendas, o stream de vídeo final [v_out] é apenas uma cópia nomeada do [0:v]
                        filter_video_mix = "[0:v]copy[v_out]"
                        filter_complex_parts.append(filter_video_mix) # Garantir que [v_out] é definido
                    
                    # --- Execução ---
                    cmd_final = ["ffmpeg", "-y"]
                    cmd_final.extend(input_mix)
                    
                    # Conecta todos os filtros usando ponto e vírgula
                    cmd_final.extend(["-filter_complex", ";".join(filter_complex_parts)])
                    
                    # Mapeia os streams de saída nomeados: [v_out] (vídeo com/sem legenda) e [a_out] (áudio com/sem música)
                    cmd_final.extend(["-map", "[v_out]", "-map", "[a_out]"])

                    # Encoders finais (a limpeza em run_cmd remove o espaço invisível)
                    cmd_final.extend(["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", final_path])
                    
                    # Executa o comando complexo
                    run_cmd(cmd_final)


                    with open(final_path, "rb") as f:
                        st.session_state["video_final_bytes"] = BytesIO(f.read())
                    status.update(label="Vídeo Renderizado com Sucesso!", state="complete")
                else:
                    status.update(label="Nenhum clipe válido gerado.", state="error")
            except Exception as e:
                status.update(label="Erro na renderização", state="error")
                st.error(f"Detalhes: {e}")
                st.error(traceback.format_exc())
            finally:
                # Clean up all temporary directories
                if st.session_state.get("temp_assets_dir") and os.path.exists(st.session_state["temp_assets_dir"]):
                    _shutil.rmtree(st.session_state["temp_assets_dir"])
                    del st.session_state["temp_assets_dir"] 
                    st.info("📦 Arquivos temporários de assets do job removidos.")
                if temp_dir_render and os.path.exists(temp_dir_render):
                    _shutil.rmtree(temp_dir_render)
                    st.info("📦 Arquivos temporários de renderização removidos.")

    if st.session_state.get("video_final_bytes"):
        st.success("Vídeo pronto!")
        st.video(st.session_state["video_final_bytes"])
        st.download_button("⬇️ Baixar MP4", st.session_state["video_final_bytes"], "video_jhonata.mp4", "video/mp4")

st.markdown("---")
st.caption("Studio Jhonata v22.7 - Suavização de Ken Burns")