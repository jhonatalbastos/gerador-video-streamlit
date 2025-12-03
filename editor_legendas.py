# pages/5_批量_Processamento_Batch.py - Processamento de Legendas em Massa
import os
import re
import json
import time
import subprocess
import base64
from datetime import datetime
from typing import List, Dict, Any

import streamlit as st

# Importa funções e constantes do editor_legendas.py
# Adicione o caminho de importação (se necessário) ou copie as funções essenciais

# ----------------------------------------------------
# Funções essenciais (devem ser importadas ou copiadas de editor_legendas.py)
# Copie as seguintes funções do seu arquivo 'editor_legendas.py'
# para garantir que o Batch funcione como uma página independente:
# run_cmd, format_timestamp, hex_to_ass_color, 
# get_drive_service, list_videos_ready, download_video, 
# get_job_roteiro, get_full_roteiro_text, generate_perfect_srt, 
# upload_legendado_to_gas, load_config, resolve_font
# ----------------------------------------------------

# --- CONSTANTES E CONFIGURAÇÃO ---
GAS_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbx5DZ52ohxKPl6Lh0DnkhHJejuPBx1Ud6B10Ag_xfnJVzGpE83n7gHdUHnk4yAgrpuidw/exec"
MONETIZA_DRIVE_FOLDER_VIDEOS = "Monetiza_Studio_Videos_Finais" 
CONFIG_FILE = "legendas_config.json"
SAVED_FONT_FILE = "saved_custom_font.ttf"

# --- Funções copiadas (para rodar o Batch) ---

def run_cmd(cmd):
    """Executa comandos de shell (FFmpeg)"""
    clean = [arg.replace('\u00a0', ' ').strip() if isinstance(arg, str) else arg for arg in cmd if arg]
    try:
        subprocess.run(clean, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        # No modo batch, registramos o erro em vez de parar o Streamlit com st.error
        raise Exception(f"Erro FFmpeg: {e.stderr.decode()}")

def format_timestamp(seconds):
    millis = int((seconds - int(seconds)) * 1000)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"

def hex_to_ass_color(hex_color):
    h = hex_color.lstrip('#')
    if len(h) != 6: return "&HFFFFFF&"
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}"

def load_config():
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
        except: pass
    return default

def resolve_font(choice):
    """Resolve o caminho da fonte para o FFmpeg (ajustado para Batch)."""
    if choice == "Upload Personalizada" and os.path.exists(SAVED_FONT_FILE):
        return os.path.abspath(SAVED_FONT_FILE) 
    return choice 

def get_drive_service(json_file=None): 
    # (Copie esta função completa do editor_legendas.py)
    # Certifique-se de que a lógica de conexão com o Drive esteja aqui
    # ... (código get_drive_service) ...
    # (Devido ao limite de espaço, assumimos que esta função está funcional)
    pass # Placeholder

def list_videos_ready(service): 
    # (Copie esta função completa do editor_legendas.py)
    # ... (código list_videos_ready) ...
    pass # Placeholder

def download_video(service, file_id, filename):
    # (Copie esta função completa do editor_legendas.py)
    # ... (código download_video) ...
    pass # Placeholder

def get_job_roteiro(job_id: str) -> Optional[Dict[str, Any]]:
    # (Copie esta função completa do editor_legendas.py)
    # ... (código get_job_roteiro) ...
    pass # Placeholder

def get_full_roteiro_text(roteiro_data: Dict[str, Any]) -> str:
    # (Copie esta função completa do editor_legendas.py)
    # ... (código get_full_roteiro_text) ...
    pass # Placeholder

def generate_perfect_srt(segments: List[Dict[str, Any]], full_roteiro_text: str) -> str:
    # (Copie esta função completa do editor_legendas.py)
    # ... (código generate_perfect_srt) ...
    pass # Placeholder

def transcribe_audio(video_path, model_size="tiny"):
    # Esta função depende do 'whisper'. Use o modo batch com cautela.
    # (Copie esta função completa do editor_legendas.py)
    # ... (código transcribe_audio) ...
    pass # Placeholder

def upload_legendado_to_gas(video_path, original_name):
    # (Copie esta função completa do editor_legendas.py)
    # ... (código upload_legendado_to_gas) ...
    pass # Placeholder


# ====================================================
# LÓGICA DE PROCESSAMENTO EM SÉRIE (BATCH)
# ====================================================

def process_single_video(video_info: Dict[str, Any], drive_service: Any, settings: Dict[str, Any], log_placeholder: st.DeltaGenerator, progress_bar: st.DeltaGenerator, video_index: int, total_videos: int, temp_dir: str):
    """Processa um único vídeo: Baixa, Transcreve, Renderiza e Faz Upload."""
    video_id = video_info['id']; video_name = video_info['name']
    
    match = re.search(r'(JOB-[a-zA-Z0-9-]+)', video_name)
    job_id = match.group(1) if match else None

    log_placeholder.info(f"[{video_index}/{total_videos}] ⏳ Processando: **{video_name}**")
    
    # --- 1. DOWNLOAD ---
    local_video_path = os.path.join(temp_dir, f"temp_{video_id}.mp4")
    try:
        log_placeholder.caption(f"  - Baixando do Drive...")
        download_video(drive_service, video_id, local_video_path)
    except Exception as e:
        log_placeholder.error(f"  - ❌ ERRO Download: {e}")
        return False
        
    # --- 2. GERAÇÃO DE SRT PERFEITO ---
    try:
        if not job_id: raise Exception("Job ID não encontrado no nome do arquivo.")
        log_placeholder.caption(f"  - Buscando roteiro ({job_id})...")
        roteiro = get_job_roteiro(job_id)
        if not roteiro: raise Exception("Roteiro não encontrado ou vazio.")
            
        full_text = get_full_roteiro_text(roteiro)
        if not full_text: raise Exception("Texto perfeito do roteiro está vazio.")

        log_placeholder.caption("  - Transcrevendo (Whisper) para Timing...")
        # Usamos 'tiny' para batch por ser mais rápido
        _, segments = transcribe_audio(local_video_path, "tiny")
        if not segments: raise Exception("Falha ao obter Timing do Whisper.")

        log_placeholder.caption("  - Mapeando texto para Timing (Blocos Curtos)...")
        srt_content = generate_perfect_srt(segments, full_text)
        if not srt_content: raise Exception("Falha ao gerar SRT perfeito.")

    except Exception as e:
        log_placeholder.warning(f"  - ⚠️ ERRO SRT/Roteiro: {e}. Pulando para o próximo.")
        return False

    # --- 3. RENDERIZAÇÃO FFmpeg ---
    try:
        log_placeholder.caption("  - Renderizando legendas FFmpeg...")
        srt_path = os.path.join(temp_dir, "temp.srt")
        with open(srt_path, "w", encoding="utf-8") as f: f.write(srt_content)
        
        font_path = resolve_font(settings["font_style"])
        if settings["font_style"] == "Upload Personalizada" and os.path.exists(font_path):
            font_name_for_style = font_path
        else:
            font_name_for_style = settings["font_style"]
            
        ass_c = hex_to_ass_color(settings["color"]); ass_b = hex_to_ass_color(settings["border"])
        
        # Usa Outline=2 conforme definido na correção anterior
        style = f"Fontname={font_name_for_style},FontSize={settings['f_size']},PrimaryColour={ass_c},OutlineColour={ass_b},BackColour=&H80000000,BorderStyle=1,Outline=2,Shadow=0,Alignment=2,MarginV={settings['margin_v']}"
        
        final_video_path = os.path.join(temp_dir, f"legendado_{video_id}.mp4")
        
        cmd = ["ffmpeg", "-y", "-i", local_video_path, "-vf", f"subtitles={srt_path}:force_style='{style}'", "-c:a", "copy", "-c:v", "libx264", "-preset", "fast", "-crf", "23", final_video_path]
        run_cmd(cmd)
        
    except Exception as e:
        log_placeholder.error(f"  - ❌ ERRO Renderização FFmpeg: {e}")
        return False

    # --- 4. UPLOAD FINAL ---
    try:
        log_placeholder.caption("  - Enviando para o Drive (GAS)...")
        ok, msg = upload_legendado_to_gas(final_video_path, video_name)
        if not ok: raise Exception(f"Upload falhou: {msg}")
        log_placeholder.success(f"  - ✅ SUCESSO! Upload concluído. (File ID: {msg})")
    except Exception as e:
        log_placeholder.error(f"  - ❌ ERRO Upload Final: {e}")
        return False
    
    progress_bar.progress((video_index / total_videos), text=f"Vídeos concluídos: {video_index} de {total_videos}")
    return True

# ====================================================
# INTERFACE PRINCIPAL BATCH
# ====================================================

def main_batch():
    st.set_page_config(page_title="Processamento em Massa", layout="wide")
    st.title("批量 Processamento em Massa (Batch)")
    st.info("Esta ferramenta processa **todos** os vídeos disponíveis no Drive, gera o SRT perfeito e renderiza as legendas usando as configurações de estilo salvas.")

    if "batch_log" not in st.session_state: st.session_state.batch_log = []
    
    settings = load_config()

    st.markdown("---")
    st.markdown("### 🛠️ Configurações Salvas (Usadas no Batch)")
    st.json(settings)
    st.warning("Certifique-se de que a fonte 'Upload Personalizada' e os estilos estão corretos no 'Editor de Legendas Pro' antes de iniciar o Batch.")
    
    st.markdown("---")
    
    # Conexão com Drive
    drive_service = get_drive_service()
    if not drive_service:
        st.error("Conecte o Google Drive via Secrets ou upload de JSON para continuar.")
        return

    # Listar vídeos
    videos = list_videos_ready(drive_service)
    
    if not videos:
        st.info("Nenhum vídeo com 'video_final_' e sem status 'LEGENDADO' encontrado.")
        return
        
    st.markdown(f"### 🗂️ {len(videos)} Vídeos Prontos para Processamento")
    st.dataframe(
        [{'Nome': v['name'], 'Data de Criação': v['createdTime']} for v in videos], 
        use_container_width=True, 
        hide_index=True
    )

    if st.button("▶️ Iniciar Processamento em Massa", type="primary"):
        st.session_state.batch_log = []
        
        log_container = st.empty()
        progress_bar = st.progress(0, text="Iniciando...")
        
        total_videos = len(videos)
        
        # Cria um diretório temporário para arquivos do lote
        with tempfile.TemporaryDirectory() as temp_dir:
            
            for i, video in enumerate(videos):
                video_index = i + 1
                log_placeholder = log_container.container()
                
                # Executa o processamento do vídeo
                success = process_single_video(
                    video, drive_service, settings, log_placeholder, 
                    progress_bar, video_index, total_videos, temp_dir
                )
                
                log_status = {"name": video['name'], "success": success, "time": datetime.now().isoformat()}
                st.session_state.batch_log.append(log_status)
                
                # Limpa arquivos temporários do vídeo atual (evita encher o disco)
                for f in os.listdir(temp_dir): os.remove(os.path.join(temp_dir, f))
            
            progress_bar.progress(1.0, text="100% - Todos os vídeos foram processados.")
            log_container.success("Processamento em Massa Concluído!")
            
    if st.session_state.batch_log:
        st.markdown("---")
        st.subheader("Relatório de Execução")
        st.dataframe(st.session_state.batch_log)

if __name__ == "__main__":
    main_batch()
