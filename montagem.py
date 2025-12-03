# montagem.py — Fábrica de Vídeos (Renderizador) - Versão Restaurada e Limpa (Sem Legendas, Com Música)
import os
import re
import json
import time
import tempfile
import traceback
import subprocess
from io import BytesIO
from datetime import datetime
from typing import List, Optional, Dict, Any
import base64
import shutil as _shutil

import requests
from PIL import Image, ImageDraw, ImageFont
import streamlit as st

# --- API Imports ---
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# --- CONFIGURAÇÃO ---
FRONTEND_AI_STUDIO_URL = "https://ai.studio/apps/drive/1gfrdHffzH67cCcZBJWPe6JfE1ZEttn6u"
os.environ.setdefault("IMAGEIO_FFMPEG_EXE", "/usr/bin/ffmpeg")
CONFIG_FILE = "overlay_config.json"
SAVED_MUSIC_FILE = "saved_bg_music.mp3"
SAVED_FONT_FILE = "saved_custom_font.ttf" # Arquivo de fonte persistente
MONETIZA_DRIVE_FOLDER_NAME = "Monetiza_Studio_Jobs"

# =========================
# Page Config
# =========================
st.set_page_config(
    page_title="Fábrica de Vídeo - Montagem",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =========================
# Persistência
# =========================
def load_config():
    default = {
        "line1_y": 150, "line1_size": 70, "line1_font": "Alegreya Sans Black", "line1_anim": "Estático",
        "line2_y": 250, "line2_size": 50, "line2_font": "Alegreya Sans Black", "line2_anim": "Estático",
        "line3_y": 350, "line3_size": 50, "line3_font": "Alegreya Sans Black", "line3_anim": "Estático",
        "effect_type": "Estático", "effect_speed": 3,
        "trans_type": "Fade (Escurecer)", "trans_dur": 0.5,
        "music_vol": 0.15
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                saved = json.load(f)
                default.update(saved)
        except: pass
    return default

def save_config(settings):
    try:
        with open(CONFIG_FILE, "w") as f: json.dump(settings, f)
        return True
    except: return False

def save_music_file(file_bytes):
    try:
        with open(SAVED_MUSIC_FILE, "wb") as f: f.write(file_bytes)
        return True
    except: return False

def save_font_file(file_bytes):
    try:
        with open(SAVED_FONT_FILE, "wb") as f: f.write(file_bytes)
        return True
    except: return False

def delete_music_file():
    if os.path.exists(SAVED_MUSIC_FILE): os.remove(SAVED_MUSIC_FILE); return True
    return False

def delete_font_file():
    if os.path.exists(SAVED_FONT_FILE): os.remove(SAVED_FONT_FILE); return True
    return False

# =========================
# Google Drive API
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
                if val is None: st.error(f"Falta a chave: {prefix + key}"); st.stop()
                creds_info[key] = val

            creds = service_account.Credentials.from_service_account_info(
                creds_info, scopes=['https://www.googleapis.com/auth/drive.readonly']
            )
            _drive_service = build('drive', 'v3', credentials=creds)
        except Exception as e:
            st.error(f"Erro Drive API: {e}"); st.stop()
    return _drive_service

def get_resolution_params(choice: str) -> dict:
    if "9:16" in choice: return {"w": 720, "h": 1280, "ratio": "9:16"}
    elif "16:9" in choice: return {"w": 1280, "h": 720, "ratio": "16:9"}
    else: return {"w": 1024, "h": 1024, "ratio": "1:1"}

# =========================
# Drive Operations
# =========================
def find_file_in_drive_folder(service, file_name: str, folder_name: str) -> Optional[str]:
    try:
        q_f = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        folders = service.files().list(q=q_f, fields="files(id)").execute().get('files', [])
        if not folders: return None
        folder_id = folders[0]['id']
        
        q_file = f"name = '{file_name}' and mimeType = 'application/json' and '{folder_id}' in parents and trashed = false"
        files = service.files().list(q=q_file, fields="files(id, name)").execute().get('files', [])
        return files[0]['id'] if files else None
    except: return None

def download_file_content(service, file_id: str) -> Optional[str]:
    try:
        request = service.files().get_media(fileId=file_id)
        return request.execute().decode('utf-8')
    except: return None

def list_recent_jobs(limit: int = 15) -> List[Dict]:
    service = get_drive_service()
    if not service: return []
    jobs_list = []
    
    try:
        q_f = f"name = '{MONETIZA_DRIVE_FOLDER_NAME}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        folders = service.files().list(q=q_f, fields="files(id)").execute().get('files', [])
        if not folders: return []
        folder_id = folders[0]['id']

        query_file = (
            f"mimeType = 'application/json' and "
            f"'{folder_id}' in parents and "
            f"trashed = false"
        )
        
        results = service.files().list(
            q=query_file, 
            orderBy="createdTime desc", 
            pageSize=50, 
            fields="files(id, name, createdTime, description)"
        ).execute()
        
        files = results.get('files', [])

        for f in files:
            if f.get('description') != 'COMPLETE': continue

            content = download_file_content(service, f['id'])
            if content:
                try:
                    data = json.loads(content)
                    meta = data.get("meta_dados", {})
                    jid = f['name'].replace("job_data_", "").replace(".json", "")
                    jobs_list.append({
                        "display": f"✅ {meta.get('data','?')} | {meta.get('ref','?')}",
                        "job_id": jid,
                        "file_id": f['id']
                    })
                except: continue
            
            if len(jobs_list) >= limit: break
                
    except Exception as e:
        st.error(f"Erro ao listar: {e}")
        return []
    return jobs_list

def load_job_from_drive(job_id: str) -> Optional[Dict[str, Any]]:
    service = get_drive_service()
    if not service: return None
    fid = find_file_in_drive_folder(service, f"job_data_{job_id}.json", MONETIZA_DRIVE_FOLDER_NAME)
    if fid:
        c = download_file_content(service, fid)
        if c: return json.loads(c)
    return None

def process_job_payload(payload: Dict, temp_dir: str):
    try:
        st.session_state["roteiro_gerado"] = payload.get("roteiro", {})
        meta = payload.get("meta_dados", {})
        
        # DATA
        d_raw = meta.get("data", "")
        if re.match(r"\d{4}-\d{2}-\d{2}", d_raw):
            try:
                d_obj = datetime.strptime(d_raw, '%Y-%m-%d')
                st.session_state["data_display"] = d_obj.strftime('%d.%m.%Y')
            except:
                st.session_state["data_display"] = d_raw.replace('/', '.')
        else:
            st.session_state["data_display"] = d_raw.replace('/', '.')
            
        # TÍTULO E REFERÊNCIA
        raw_ref = meta.get("ref", "")
        title = "EVANGELHO"
        clean_ref = raw_ref

        if " - " in raw_ref:
            parts = raw_ref.split(" - ", 1)
            tipo_raw = parts[0]
            clean_ref = parts[1]
            if "1ª" in tipo_raw or "Primeira" in tipo_raw: title = "1ª LEITURA"
            elif "2ª" in tipo_raw or "Segunda" in tipo_raw: title = "2ª LEITURA"
            elif "Salmo" in tipo_raw: title = "SALMO"
        else:
            if "Salmo" in raw_ref: title = "SALMO"
            elif "Leitura" in raw_ref: title = "1ª LEITURA"
        
        patterns_to_remove = [
            r"^(Primeira|Segunda|1ª|2ª)\s*Leitura\s*:\s*",
            r"^Leitura\s*(do|da)\s*.*:\s*",
            r"^Salmo\s*Responsorial\s*:\s*",
            r"^Salmo\s*:\s*",
            r"^Evangelho\s*:\s*",
            r"^Proclamação\s*do\s*Evangelho.*:\s*"
        ]
        for pat in patterns_to_remove:
            clean_ref = re.sub(pat, "", clean_ref, flags=re.IGNORECASE).strip()

        st.session_state["title_display"] = title
        st.session_state["ref_display"] = clean_ref

        # ASSETS
        st.session_state["generated_images_blocks"] = {}
        st.session_state["generated_audios_blocks"] = {}

        assets = payload.get("assets", [])
        if not assets:
            st.warning("⚠️ Job sem assets. Use upload manual.")

        for asset in assets:
            bid, atype, b64 = asset.get("block_id"), asset.get("type"), asset.get("data_b64")
            if not bid or not atype or not b64: continue
            try:
                raw = base64.b64decode(b64)
                if atype == "image":
                    path = os.path.join(temp_dir, f"{bid}.png")
                    with open(path, "wb") as f: f.write(raw)
                    st.session_state["generated_images_blocks"][bid] = path
                elif atype == "audio":
                    path = os.path.join(temp_dir, f"{bid}.wav")
                    with open(path, "wb") as f: f.write(raw)
                    st.session_state["generated_audios_blocks"][bid] = path
            except Exception as ex: continue
                
        return True
    except Exception as e:
        st.error(f"Erro processando payload: {e}")
        return False

# =========================
# Utils & FFmpeg
# =========================
def shutil_which(name): return _shutil.which(name)

def run_cmd(cmd, cwd=None):
    clean = [arg.replace('\u00a0', ' ').strip() if isinstance(arg, str) else arg for arg in cmd if arg]
    print(f"Executando: {' '.join(clean)}") 
    try:
        subprocess.run(clean, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"CMD Falhou: {e.stderr.decode()}")

def get_audio_duration(path):
    if not shutil_which("ffprobe"): return 5.0
    try:
        cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path]
        out = subprocess.check_output(cmd).decode().strip()
        return float(out)
    except: return 5.0

def resolve_font(choice, upload):
    if choice == "Upload Personalizada" and upload:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ttf") as tmp:
            tmp.write(upload.getvalue())
            return tmp.name
    if choice == "Upload Personalizada" and os.path.exists(SAVED_FONT_FILE):
        return SAVED_FONT_FILE
    if choice == "Alegreya Sans Black" and os.path.exists(SAVED_FONT_FILE):
         return SAVED_FONT_FILE

    sys_fonts = {
        "Padrão (Sans)": ["arial.ttf", "DejaVuSans.ttf"], 
        "Serif": ["times.ttf"], 
        "Monospace": ["courier.ttf"],
    }
    font_list = sys_fonts.get(choice, [])
    for f in font_list: return f
    return None

def criar_preview(w, h, texts, upload):
    img = Image.new("RGB", (w, h), "black")
    draw = ImageDraw.Draw(img)
    for t in texts:
        if not t["text"]: continue
        try: font = ImageFont.truetype(resolve_font(t["font_style"], upload), t["size"])
        except: font = ImageFont.load_default()
        try: length = draw.textlength(t["text"], font=font)
        except: length = len(t["text"]) * t["size"] * 0.5
        x = (w - length) / 2
        draw.text((x, t["y"]), t["text"], fill=t["color"], font=font, stroke_width=2, stroke_fill="black")
    bio = BytesIO(); img.save(bio, "PNG"); bio.seek(0)
    return bio

def san(txt): return txt.replace(":", "\\:").replace("'", "") if txt else ""

def auto_load_and_process_job(job_id: str):
    if not job_id: return
    st.session_state['drive_job_id_input'] = job_id
    with st.status(f"Carregando automaticamente job '{job_id}'...", expanded=True) as status_box:
        if st.session_state.get("temp_assets_dir") and os.path.exists(st.session_state["temp_assets_dir"]):
            try: _shutil.rmtree(st.session_state["temp_assets_dir"])
            except: pass
        
        temp_assets_dir = tempfile.mkdtemp()
        payload = load_job_from_drive(job_id)
        
        if payload and process_job_payload(payload, temp_assets_dir):
            st.session_state.update({"job_loaded_from_drive": True, "temp_assets_dir": temp_assets_dir})
            status_box.update(label=f"✅ Job carregado com sucesso!", state="complete")
            time.sleep(0.5)
            st.rerun()
        else:
            status_box.update(label="❌ Erro ao carregar job.", state="error")
            if os.path.exists(temp_assets_dir):
                try: _shutil.rmtree(temp_assets_dir)
                except: pass
            st.session_state["temp_assets_dir"] = None

# =========================
# APP MAIN
# =========================
if "roteiro_gerado" not in st.session_state: st.session_state.update({"roteiro_gerado": None, "generated_images_blocks": {}, "generated_audios_blocks": {}, "video_final_bytes": None, "meta_dados": {}, "data_display": "", "ref_display": "", "title_display": "EVANGELHO", "lista_jobs": [], "job_loaded_from_drive": False, "temp_assets_dir": None})
if "overlay_settings" not in st.session_state: st.session_state["overlay_settings"] = load_config()

res_choice = st.sidebar.selectbox("Resolução", ["9:16 (Stories)", "16:9 (YouTube)", "1:1 (Feed)"])

# Upload de Fonte Persistente
st.sidebar.markdown("---")
st.sidebar.markdown("### 🅰️ Fonte Personalizada")

font_up = st.sidebar.file_uploader("Upload de Fonte (.ttf)", type=["ttf"])
if font_up:
    if save_font_file(font_up.getvalue()):
        st.sidebar.success("Fonte salva! Selecione 'Upload Personalizada' ou 'Alegreya Sans Black' no menu.")
        
# Verifica se existe fonte salva
font_status = "✅ Fonte Salva Encontrada" if os.path.exists(SAVED_FONT_FILE) else "⚠️ Nenhuma fonte salva"
st.sidebar.caption(font_status)

if st.sidebar.button("Apagar Fonte Salva"):
    if delete_font_file():
        st.sidebar.info("Fonte removida.")
        st.rerun()

tab1, tab2, tab3 = st.tabs(["📥 Receber Job", "🎚️ Overlay", "🎥 Renderizar"])

with tab1:
    st.header("📥 Central de Recepção")
    st.markdown(f"[Ir para AI Studio (Produção)]({FRONTEND_AI_STUDIO_URL})")
    
    c1, c2 = st.columns([1.5, 1])
    with c1:
        if st.button("🔄 Buscar Jobs Prontos no Drive"):
            with st.spinner("Filtrando jobs 'COMPLETE'..."):
                st.session_state['lista_jobs'] = list_recent_jobs(15)
        
        if st.session_state['lista_jobs']:
            opts = {j['display']: j['job_id'] for j in st.session_state['lista_jobs']}
            
            # Callback para auto-load quando mudar a seleção
            selected_display = st.selectbox(
                "Selecione um Job:", 
                options=list(opts.keys()),
                index=None, 
                placeholder="Escolha um job para carregar..."
            )
            
            if selected_display:
                selected_id = opts[selected_display]
                if selected_id != st.session_state.get('drive_job_id_input'):
                     auto_load_and_process_job(selected_id)
        else: st.info("Nenhum job pronto encontrado.")

    with c2:
        # Mantém opção manual caso o usuário queira colar um ID direto
        jid_in = st.text_input("ID Manual:", key="drive_job_id_input_manual") 
        if st.button("Baixar ID Manual", disabled=not jid_in):
             auto_load_and_process_job(jid_in)

    if st.session_state["job_loaded_from_drive"]:
        st.success(f"Job Ativo")
        c1, c2, c3 = st.columns(3)
        with c1: 
            val = st.text_input("Título (Linha 1)", st.session_state["title_display"])
            if val != st.session_state["title_display"]: st.session_state["title_display"] = val
        with c2: 
            val = st.text_input("Data (Linha 2)", st.session_state["data_display"])
            if val != st.session_state["data_display"]: st.session_state["data_display"] = val
        with c3:
            val = st.text_input("Referência (Linha 3)", st.session_state["ref_display"])
            if val != st.session_state["ref_display"]: st.session_state["ref_display"] = val

with tab2:
    st.header("Editor Visual")
    c1, c2 = st.columns(2)
    sets = st.session_state["overlay_settings"]
    
    with c1:
        with st.expander("Movimento"):
            sets["effect_type"] = st.selectbox("Efeito", ["Zoom In (Ken Burns)", "Zoom Out", "Pan Esq", "Pan Dir", "Estático"], index=4)
            sets["effect_speed"] = st.slider("Velocidade", 1, 10, 3)
        with st.expander("Texto"):
            sets["line1_font"] = st.selectbox("Fonte L1", ["Padrão (Sans)", "Alegreya Sans Black", "Serif", "Upload Personalizada"], index=1)
            sets["line1_size"] = st.slider("Tam L1", 10, 150, sets.get("line1_size", 70))
            sets["line1_y"] = st.slider("Y L1", 0, 800, sets.get("line1_y", 150))
            sets["line2_size"] = st.slider("Tam L2", 10, 100, sets.get("line2_size", 50))
            sets["line2_y"] = st.slider("Y L2", 0, 800, sets.get("line2_y", 250))
            sets["line3_size"] = st.slider("Tam L3", 10, 100, sets.get("line3_size", 50))
            sets["line3_y"] = st.slider("Y L3", 0, 800, sets.get("line3_y", 350))
            
            if sets["line1_font"] == "Alegreya Sans Black":
                sets["line2_font"] = "Alegreya Sans Black"
                sets["line3_font"] = "Alegreya Sans Black"

        if st.button("Salvar Config"): save_config(sets); st.success("Salvo!")

    with c2:
        res = get_resolution_params(res_choice)
        prev = criar_preview(int(res["w"]*0.4), int(res["h"]*0.4), [
            {"text": st.session_state.get("title_display","EVANGELHO"), "size": int(sets["line1_size"]*0.4), "y": int(sets["line1_y"]*0.4), "color": "white", "font_style": sets["line1_font"]},
            {"text": st.session_state.get("data_display","01.01.2025"), "size": int(sets["line2_size"]*0.4), "y": int(sets["line2_y"]*0.4), "color": "white", "font_style": sets["line1_font"]},
            {"text": st.session_state.get("ref_display","Mt 1,1"), "size": int(sets["line3_size"]*0.4), "y": int(sets["line3_y"]*0.4), "color": "white", "font_style": sets["line1_font"]},
        ], font_up)
        st.image(prev, caption="Preview")

with tab3:
    st.header("Renderização")
    if not st.session_state["job_loaded_from_drive"]: st.warning("Carregue um job primeiro."); st.stop()
    
    blocos_config = [
        {"id": "hook", "label": "🎣 HOOK", "text_path": "hook", "prompt_path": "hook"},
        {"id": "leitura", "label": "📖 LEITURA", "text_path": "leitura", "prompt_path": "leitura"},
        {"id": "reflexao", "label": "💭 REFLEXÃO", "text_path": "reflexao", "prompt_path": "reflexao"},
        {"id": "aplicacao", "label": "🌟 APLICAÇÃO", "text_path": "aplicacao", "prompt_path": "aplicacao"},
        {"id": "oracao", "label": "🙏 ORAÇÃO", "text_path": "oracao", "prompt_path": "oracao"},
    ]
    
    roteiro = st.session_state.get("roteiro_gerado", {})

    for bid_item in blocos_config:
        bid = bid_item["id"]
        with st.expander(bid.upper()):
            c1, c2 = st.columns([2, 1])
            aud = st.session_state["generated_audios_blocks"].get(bid)
            img = st.session_state["generated_images_blocks"].get(bid)
            with c1: 
                if aud: st.audio(aud)
                else: st.info("Sem áudio")
                aud_file = st.file_uploader(f"🎤 Enviar Áudio para {bid.upper()}", type=["mp3", "wav"], key=f"up_aud_{bid}")
                if aud_file:
                    if st.session_state.get("temp_assets_dir"):
                        path = os.path.join(st.session_state["temp_assets_dir"], f"{bid}.wav")
                        with open(path, "wb") as f: f.write(aud_file.read())
                        st.session_state["generated_audios_blocks"][bid] = path
                        st.success("Áudio atualizado!")
                        st.rerun()

            with c2: 
                if img: st.image(img, width=150)
                else: st.info("Sem imagem")
                img_file = st.file_uploader(f"🖼️ Enviar Imagem para {bid.upper()}", type=["png", "jpg", "jpeg"], key=f"up_img_{bid}")
                if img_file:
                    if st.session_state.get("temp_assets_dir"):
                        path = os.path.join(st.session_state["temp_assets_dir"], f"{bid}.png")
                        with open(path, "wb") as f: f.write(img_file.read())
                        st.session_state["generated_images_blocks"][bid] = path
                        st.success("Imagem atualizada!")
                        st.rerun()

    st.divider()
    use_over = st.checkbox("Overlay Texto", value=True)

    st.subheader("🎵 Música de Fundo")
    col_mus_1, col_mus_2 = st.columns(2)

    with col_mus_1:
        if os.path.exists(SAVED_MUSIC_FILE):
            st.success("💾 Música Padrão Ativa")
            st.audio(SAVED_MUSIC_FILE)
            if st.button("❌ Remover Música"):
                if delete_music_file():
                    st.rerun()
        else: st.info("Nenhuma música definida.")

    with col_mus_2:
        new_music = st.file_uploader("Substituir Música (MP3)", type=["mp3"])
        if new_music and save_music_file(new_music.getvalue()):
            st.success("Música salva!"); time.sleep(1); st.rerun()

    include_music = st.checkbox("Incluir música de fundo", value=os.path.exists(SAVED_MUSIC_FILE))
    music_vol = st.slider("Volume Música", 0.0, 1.0, load_config().get("music_vol", 0.15))

    if st.button("RENDERIZAR VÍDEO FINAL", type="primary"):
        render_prog = st.progress(0, text="Iniciando Renderização...")
        eta_placeholder = st.empty()
        start_time = time.time()
        
        with st.status("Renderizando...", expanded=True) as s:
            try:
                tmp = tempfile.mkdtemp()
                clips = []
                res = get_resolution_params(res_choice)
                w, h = res["w"], res["h"]
                f1 = resolve_font(sets["line1_font"], font_up)
                
                total_steps = len(blocos_config) + 3
                current_step = 0

                for bid in ["hook", "leitura", "reflexao", "aplicacao", "oracao"]:
                    current_step += 1
                    progress_pct = int((current_step / total_steps) * 100)
                    elapsed = time.time() - start_time
                    if progress_pct > 0:
                        eta = (elapsed / progress_pct) * (100 - progress_pct)
                        eta_placeholder.text(f"ETA: ~{int(eta)} segundos restantes")
                    render_prog.progress(progress_pct, text=f"Renderizando clipe: {bid.upper()}...")
                    
                    aud = st.session_state["generated_audios_blocks"].get(bid)
                    img = st.session_state["generated_images_blocks"].get(bid)
                    if not aud or not img: continue
                    
                    dur = get_audio_duration(aud)
                    out = os.path.join(tmp, f"{bid}.mp4")
                    
                    vf = f"scale={w}x{h}" 
                    if sets["effect_type"] == "Zoom In (Ken Burns)":
                        vf = f"zoompan=z='min(zoom+0.0015,1.5)':d={int(dur*25)}:s={w}x{h}:fps=25"
                    elif sets["effect_type"] == "Zoom Out":
                        vf = f"zoompan=z='max(1.5-0.0015*on,1)':d={int(dur*25)}:s={w}x{h}:fps=25"
                    elif sets["effect_type"] == "Pan Esq":
                        vf = f"zoompan=z=1.2:x='min(x+1,iw-iw/1.2)':y='(ih-ih/1.2)/2':d={int(dur*25)}:s={w}x{h}:fps=25"
                    
                    filters = [vf, f"fade=t=in:st=0:d=0.5,fade=t=out:st={dur-0.5}:d=0.5"]
                    
                    if use_over and f1:
                        t1 = san(st.session_state.get("title_display", ""))
                        filters.append(f"drawtext=fontfile='{f1}':text='{t1}':fontcolor=white:borderw=3:bordercolor=black:fontsize={sets['line1_size']}:x=(w-text_w)/2:y={sets['line1_y']}")
                        t2 = san(st.session_state.get("data_display", ""))
                        filters.append(f"drawtext=fontfile='{f1}':text='{t2}':fontcolor=white:borderw=3:bordercolor=black:fontsize={sets['line2_size']}:x=(w-text_w)/2:y={sets['line2_y']}")
                        t3 = san(st.session_state.get("ref_display", ""))
                        filters.append(f"drawtext=fontfile='{f1}':text='{t3}':fontcolor=white:borderw=3:bordercolor=black:fontsize={sets['line3_size']}:x=(w-text_w)/2:y={sets['line3_y']}")

                    run_cmd(["ffmpeg", "-y", "-loop", "1", "-i", img, "-i", aud, "-vf", ",".join(filters), "-c:v", "libx264", "-t", str(dur), "-pix_fmt", "yuv420p", "-crf", "28", "-preset", "fast", "-shortest", out])
                    clips.append(out)

                current_step += 1
                render_prog.progress(int((current_step / total_steps) * 100), text="Concatenando clipes...")
                
                lst = os.path.join(tmp, "list.txt")
                with open(lst, "w") as f:
                    for c in clips: f.write(f"file '{c}'\n")
                
                conc = os.path.join(tmp, "concat.mp4")
                run_cmd(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", conc])
                
                current_step += 1
                render_prog.progress(int((current_step / total_steps) * 100), text="Mixando Áudio...")

                final = os.path.join(tmp, "final.mp4")
                mix_cmd = ["ffmpeg", "-y", "-i", conc]
                filter_complex = []
                
                if include_music and os.path.exists(SAVED_MUSIC_FILE):
                    try:
                        music_copy = os.path.join(tmp, "saved_bg_music.mp3")
                        _shutil.copyfile(SAVED_MUSIC_FILE, music_copy)
                        mix_cmd.extend(["-stream_loop", "-1", "-i", music_copy])
                        filter_complex.append(f"[1:a]volume={music_vol}[bg];[0:a][bg]amix=inputs=2:duration=first[a_out]")
                        map_a = "[a_out]"
                    except Exception as e:
                        print("Falha musica:", e)
                        map_a = "0:a"
                else:
                    map_a = "0:a"

                if filter_complex:
                    mix_cmd.extend(["-filter_complex", ",".join(filter_complex)])
                    if "amix" in "".join(filter_complex):
                        mix_cmd.extend(["-map", "0:v", "-map", map_a])
                
                mix_cmd.extend(["-crf", "28", "-preset", "fast"])
                mix_cmd.append("final.mp4")
                
                run_cmd(mix_cmd, cwd=tmp)
                
                final_absolute_path = os.path.join(tmp, "final.mp4")
                
                with open(final_absolute_path, "rb") as f:
                    st.session_state["video_final_bytes"] = BytesIO(f.read())
                
                render_prog.progress(100, text="Finalizado!")
                eta_placeholder.empty()
                s.update(label="Pronto!", state="complete")
                
            except Exception as e:
                st.error(f"Erro render: {e}")
                st.error(traceback.format_exc())
                s.update(label="Erro", state="error")

    if st.session_state["video_final_bytes"]:
        st.video(st.session_state["video_final_bytes"])
        st.download_button("⬇️ Baixar Vídeo", st.session_state["video_final_bytes"], "video.mp4", "video/mp4")
