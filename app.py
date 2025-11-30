# app.py — Studio Jhonata (COMPLETO v21.0 - Disparo de Job no GAS)
# Features: Nova função para disparar geração de Job no Google Apps Script.
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

# Imports de Tipagem (Standard Library)
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
    page_title="Studio Jhonata",
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
    }
    
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                saved = json.load(f)
                
                # Mescla as configurações e remove campos antigos de rastreamento
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
# Funções de Liturgia, Roteiro e Análise
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
        "mateus": "Mateus", "mt": "Mateus",
        "marcos": "Marcos", "mc": "Marcos",
        "lucas": "Lucas", "lc": "Lucas",
        "joão": "João", "joao": "João", "jo": "João"
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
            if len(nome_cand) > 2:
                evangelista_encontrado = nome_cand
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

def analisar_personagens_groq(texto_evangelho: str, banco_personagens: dict):
    client = inicializar_groq()
    personagens_str = json.dumps(banco_personagens, ensure_ascii=False)
    system_prompt = (
        "Você é especialista em análise bíblica.\n"
        "Analise o texto e identifique TODOS os personagens bíblicos mencionados.\n\n"
        "Formato EXATO da resposta:\n\n"
        "PERSONAGENS: nome1; nome2; nome3\n\n"
        "NOVOS: NomeNovo|descrição_detalhada_aparência_física_roupas_idade_estilo (apenas se não existir no banco)\n\n"
        f"BANCO EXISTENTE: {'; '.join(banco_personagens.keys())}\n\n"
    )
    try:
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"TEXTO: {texto_evangelho[:1500]}"},
            ],
            temperature=0.3,
            max_tokens=400,
        )
        resultado = resp.choices[0].message.content
        personagens_detectados = {}
        m = re.search(r"PERSONAGENS:\s*(.+)", resultado)
        if m:
            nomes = [n.strip() for n in m.group(1).split(";") if n.strip()]
            for nome in nomes:
                if nome in banco_personagens:
                    personagens_detectados[nome] = banco_personagens[nome]
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

def buscar_liturgia_api1(data_str: str):
    url = f"https://api-liturgia-diaria.vercel.app/?date={data_str}"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        dados = resp.json()
        today = dados.get("today", {})
        readings = today.get("readings", {})
        gospel = readings.get("gospel")
        if not gospel: return None
        referencia_liturgica = today.get("entry_title", "").strip() or "Evangelho do dia"
        titulo = (
            gospel.get("head_title", "")
            or gospel.get("title", "")
            or "Evangelho de Jesus Cristo"
        ).strip()
        texto = gospel.get("text", "").strip()
        if not texto: return None
        texto_limpo = limpar_texto_evangelho(texto)
        ref_biblica = extrair_referencia_biblica(titulo)
        return {
            "fonte": "api-liturgia-diaria.vercel.app",
            "titulo": titulo,
            "referencia_liturgica": referencia_liturgica,
            "texto": texto_limpo,
            "ref_biblica": ref_biblica,
        }
    except Exception: return None

def buscar_liturgia_api2(data_str: str):
    url = f"https://liturgia.up.railway.app/v2/{data_str}"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        dados = resp.json()
        lit = dados.get("liturgia", {})
        ev = lit.get("evangelho") or lit.get("evangelho_do_dia") or {}
        if not ev: return None
        texto = ev.get("texto", "") or ev.get("conteudo", "")
        if not texto: return None
        texto_limpo = limpar_texto_evangelho(texto)
        return {
            "fonte": "liturgia.up.railway.app",
            "titulo": "Evangelho do dia",
            "referencia_liturgica": "Evangelho do dia",
            "texto": texto_limpo,
            "ref_biblica": None,
        }
    except Exception: return None

def obter_evangelho_com_fallback(data_str: str):
    ev = buscar_liturgia_api1(data_str)
    if ev: st.info("📡 Usando api-liturgia-diaria.vercel.app"); return ev
    ev = buscar_liturgia_api2(data_str)
    if ev: st.info("📡 Usando liturgia.up.railway.app"); return ev
    st.error("❌ Não foi possível obter o Evangelho"); return None

def extrair_bloco(rotulo: str, texto: str) -> str:
    padrao = rf"{rotulo}:\s*(.*?)(?=\n[A-ZÁÉÍÓÚÃÕÇ]{{3,}}:\s*|\nPROMPT_|$)"
    m = re.search(padrao, texto, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else ""

def extrair_prompt(rotulo: str, texto: str) -> str:
    padrao = rf"{rotulo}:\s*(.*?)(?=\n[A-ZÁÉÍÓÚÃÕÇ]{{3,}}:\s*|\nPROMPT_|$)"
    m = re.search(padrao, texto, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else ""

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
- USE SEMPRE as descrições exatas dos personagens
- Estilo: artístico renascentista católico, luz suave, cores quentes

Formato EXATO:

HOOK: [texto 5-8s]
PROMPT_HOOK: [prompt visual com personagens fixos]

REFLEXÃO: [texto 20-25s]
PROMPT_REFLEXÃO: [prompt visual com personagens fixos]

APLICAÇÃO: [texto 20-25s]
PROMPT_APLICACAO: [prompt visual com personagens fixos]

ORAÇÃO: [texto 20-25s]
PROMPT_ORACAO: [prompt visual com personagens fixos]

PROMPT_LEITURA: [prompt visual específico para a leitura do Evangelho, mais calmo e reverente]

PROMPT_GERAL: [prompt para thumbnail/capa]"""
    try:
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Evangelho: {referencia_liturgica}\n\n{texto_limpo[:2000]}"},
            ],
            temperature=0.7,
            max_tokens=1200,
        )
        texto_gerado = resp.choices[0].message.content
        partes: dict[str, str] = {}
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
        st.error(f"❌ Erro Groq: {e}"); return None

def montar_leitura_com_formula(texto_evangelho: str, ref_biblica):
    if ref_biblica:
        abertura = (
            f"Proclamação do Evangelho de Jesus Cristo, segundo São "
            f"{ref_biblica['evangelista']}, "
            f"Capítulo {ref_biblica['capitulo']}, "
            f"versículos {ref_biblica['versiculos']}. "
            "Glória a vós, Senhor!"
        )
    else:
        abertura = (
            "Proclamação do Evangelho de Jesus Cristo, segundo São Lucas. "
            "Glória a vós, Senhor!"
        )
    fechamento = "Palavra da Salvação. Glória a vós, Senhor!"
    return f"{abertura} {texto_evangelho} {fechamento}"


# =========================
# FUNÇÕES DE COMUNICAÇÃO COM APPS SCRIPT/DRIVE (NOVAS)
# =========================

def dispatch_new_job_to_gas(date_str: str) -> Optional[Dict]:
    """
    Dispara a criação de um novo Job de roteiro, imagem e áudio no Apps Script.
    """
    st.info(f"🌐 Disparando Job de Geração para {date_str} no Apps Script...")
    
    payload = {"date_str": date_str}
    
    try:
        response = requests.post(
            f"{GAS_API_URL}?action=generate_new_job",
            json=payload,
            timeout=120 # O tempo limite é maior porque o GAS irá executar IA e geração de mídia
        )
        response.raise_for_status()
        data = response.json()
        
        if data.get("status") == "success":
            st.success(f"Job de Geração iniciado com sucesso! ID: {data.get('job_id')}")
            return data
        else:
            st.error(f"Erro ao disparar Job de Geração: {data.get('message', 'Resposta inválida do GAS.')}")
            return None
    except Exception as e:
        st.error(f"Erro de comunicação/timeout com o Apps Script: {e}")
        return None

def fetch_job_metadata(job_id: str) -> Optional[Dict]:
    """
    Solicita ao Apps Script os metadados do Job ID e lista de URLs de arquivos.
    """
    st.info(f"🌐 Solicitando metadados do Job ID: {job_id}...")
    # NOTE: O erro de configuração será tratado pela chamada ao GAS

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

def download_files_from_urls(urls_arquivos: List[Dict]) -> Tuple[Dict, Dict]:
    """Baixa os arquivos de áudio e imagem de URLs temporárias do Drive."""
    images = {}
    audios = {}
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

            if file_type == "image": images[block_id] = bio
            elif file_type == "audio": audios[block_id] = bio
            st.write(f"✅ Baixado: {block_id} ({file_type})")
        except Exception as e:
            st.error(f"❌ Falha ao baixar {block_id} ({file_type}): {e}")
            
    return images, audios

def finalize_job_on_drive(job_id: str, video_bytes: BytesIO, metadata_description: str):
    """
    Envia o vídeo final e os metadados para o Apps Script para upload e limpeza.
    """
    st.info(f"⬆️ Finalizando Job {job_id} e limpando arquivos...")
    
    try:
        # NOTE: requests com 'files' não funcionam bem no Streamlit Cloud.
        # Estamos assumindo que o ambiente do Streamlit Cloud suporta esta chamada.
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
# FUNÇÕES DE ÁUDIO & IMAGEM (gTTS e Pollinations)
# =========================

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
# Helpers e Utilitários
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
st.title("✨ Studio Jhonata - Automação Litúrgica")
st.markdown("---")

# ---- SIDEBAR CONFIG ----
st.sidebar.title("⚙️ Configurações")

# --- Motor IMAGEN: Apenas Pollinations ---
image_motor_options = ["Pollinations Flux (Padrão)", "Pollinations Turbo"]
motor_escolhido = st.sidebar.selectbox("🎨 Motor de Imagem", image_motor_options, index=0)

resolucao_escolhida = st.sidebar.selectbox("📏 Resolução do Vídeo", ["9:16 (Vertical/Stories)", "16:9 (Horizontal/YouTube)", "1:1 (Quadrado/Feed)"], index=0)

st.sidebar.markdown("---")

# --- Motor TTS: Apenas gTTS ---
st.sidebar.markdown("### 🗣️ Motor TTS")
st.sidebar.info("Modo de Voz: gTTS (Padrão - Gratuito)")
tts_motor_escolhido = "gTTS (Padrão)" # Valor fixo

st.sidebar.markdown("---")
st.sidebar.markdown("### 🅰️ Upload de Fonte (Global)")
uploaded_font_file = st.sidebar.file_uploader("Arquivo .ttf (para opção 'Upload Personalizada')", type=["ttf"])

st.sidebar.info(f"Modo: {motor_escolhido}\nFormato: {resolucao_escolhida}\nTTS: {tts_motor_escolhido}")

if "personagens_biblicos" not in st.session_state:
    st.session_state.personagens_biblicos = inicializar_personagens()

# session state
if "roteiro_gerado" not in st.session_state: st.session_state["roteiro_gerado"] = None
if "leitura_montada" not in st.session_state: st.session_state["leitura_montada"] = ""
if "generated_images_blocks" not in st.session_state: st.session_state["generated_images_blocks"] = {}
if "generated_audios_blocks" not in st.session_state: st.session_state["generated_audios_blocks"] = {}
if "video_final_bytes" not in st.session_state: st.session_state["video_final_bytes"] = None
if "meta_dados" not in st.session_state: st.session_state["meta_dados"] = {"data": "", "ref": ""}
if "job_id_ativo" not in st.session_state: st.session_state["job_id_ativo"] = None # Novo estado

# Carregar Settings persistentes
if "overlay_settings" not in st.session_state:
    st.session_state["overlay_settings"] = load_config()

tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["📖 Gerar Roteiro", "🎨 Personagens", "🎚️ Overlay & Efeitos", "🎥 Fábrica Vídeo (Editor)", "📊 Histórico"]
)

# --------- TAB 1: ROTEIRO (Painel de Controle) ----------
with tab1:
    st.header("🚀 Painel de Controle de Geração")
    
    col_date, col_manual, col_auto = st.columns([1, 1, 1])

    with col_date:
        data_selecionada = st.date_input("📅 Data da Liturgia:", value=date.today(), min_value=date(2023, 1, 1), key="data_tab1")
        data_str = data_selecionada.strftime("%Y-%m-%d")

    st.markdown("---")

    # --- Opção 1: Disparo Automático (Apps Script) ---
    with col_auto:
        st.subheader("Disparo Automático (GAS)")
        st.info("O Apps Script gera Roteiro, Imagem e Áudio no Drive.")
        if st.button("✨ Disparar Geração de Job (Cloud)", type="primary", key="btn_dispatch_gas"):
            with st.status("Iniciando Job no Apps Script...", expanded=True):
                gas_response = dispatch_new_job_to_gas(data_str)
                if gas_response and gas_response.get("job_id"):
                    st.session_state["job_id_ativo"] = gas_response["job_id"]
                    st.success(f"Job {gas_response['job_id']} iniciado! Carregue na aba 'Fábrica Vídeo'.")
                else:
                    st.error("Falha ao iniciar Job no Apps Script. Verifique logs do GAS.")
            st.rerun()

    # --- Opção 2: Geração Manual (Fallback) ---
    with col_manual:
        st.subheader("Geração Manual (Fallback)")
        st.info("O Streamlit gera apenas o roteiro (Groq).")
        if st.button("📝 Gerar Roteiro Apenas (Local)", key="btn_generate_local"):
            data_formatada_display = data_selecionada.strftime("%d.%m.%Y") 

            with st.status("📝 Gerando roteiro no Groq...", expanded=True) as status:
                liturgia = obter_evangelho_com_fallback(data_str)
                if not liturgia: status.update(label="Falha ao buscar evangelho", state="error"); st.stop()
                ref_curta = formatar_referencia_curta(liturgia.get("ref_biblica"))
                st.session_state["meta_dados"] = {"data": data_formatada_display, "ref": ref_curta or "Evangelho do Dia"}
                personagens_detectados = analisar_personagens_groq(liturgia["texto"], st.session_state.personagens_biblicos)
                roteiro = gerar_roteiro_com_prompts_groq(liturgia["texto"], liturgia["referencia_liturgica"], {**st.session_state.personagens_biblicos, **personagens_detectados})

                if roteiro:
                    status.update(label="Roteiro gerado com sucesso!", state="complete", expanded=False)
                else:
                    status.update(label="Erro ao gerar roteiro", state="error"); st.stop()

            leitura_montada = montar_leitura_com_formula(liturgia["texto"], liturgia.get("ref_biblica"))
            st.session_state["roteiro_gerado"] = roteiro
            st.session_state["leitura_montada"] = leitura_montada
            st.session_state["job_id_ativo"] = None # Reseta o Job ID ao gerar manual
            st.rerun()

    # Exibição do Roteiro (se houver)
    if st.session_state.get("roteiro_gerado"):
        st.markdown("---")
        st.subheader("Roteiro Gerado (Conteúdo Principal)")
        roteiro = st.session_state["roteiro_gerado"]
        
        # ... (Exibição detalhada do roteiro) ...
        col_esq, col_dir = st.columns(2)
        with col_esq:
            st.markdown("### 🎣 HOOK"); st.markdown(roteiro.get("hook", "")); st.code(roteiro.get("prompt_hook", ""), language="text")
            st.markdown("### 📖 LEITURA"); st.markdown(st.session_state.get("leitura_montada", "")[:300] + "..."); st.code(roteiro.get("prompt_leitura", ""), language="text")
        with col_dir:
            st.markdown("### 💭 REFLEXÃO"); st.markdown(roteiro.get("reflexão", "")); st.code(roteiro.get("prompt_reflexão", ""), language="text")
            st.markdown("### 🌟 APLICAÇÃO"); st.markdown(roteiro.get("aplicação", "")); st.code(roteiro.get("prompt_aplicacao", ""), language="text")
        st.markdown("### 🙏 ORAÇÃO"); st.markdown(roteiro.get("oração", "")); st.code(roteiro.get("prompt_oração", ""), language="text")
        st.markdown("### 🖼️ THUMBNAIL"); st.code(roteiro.get("prompt_geral", ""), language="text")
        
        if st.session_state.get("job_id_ativo"):
            st.success(f"Roteiro carregado do Job Cloud: **{st.session_state['job_id_ativo']}**. Vá para 'Fábrica Vídeo' para carregar a mídia.")
        else:
            st.success("Roteiro gerado localmente. Vá para 'Fábrica Vídeo' para gerar a mídia manualmente.")


# --------- TAB 2, 3 (inalteradas) ...

# --------- TAB 4: FÁBRICA DE VÍDEO ----------
with tab4:
    st.header("🎥 Editor de Cenas")
    
    # === NOVO BLOCO: MONTAGEM REMOTA ===
    st.subheader("🌐 Modo 1: Montagem Automática (Google Drive)")
    
    # Pré-preenche se o Job foi disparado na Tab 1
    default_job_id = st.session_state.get("job_id_ativo") if st.session_state.get("job_id_ativo") and not st.session_state.get("roteiro_gerado") else ""
    
    job_id_input = st.text_input("Insira o JOB ID (Nome da Pasta do Drive):", value=default_job_id, key="job_id_input", help="O ID da pasta criada pelo seu script no Apps Script.")
    
    if st.button("📥 Carregar Job ID do Drive", type="primary"):
        if job_id_input:
            with st.status(f"Carregando Job {job_id_input}...", expanded=True) as status:
                st.session_state["job_id_ativo"] = job_id_input # Ativa o Job ID
                
                # 1. Busca metadados (inclui o roteiro)
                job_data = fetch_job_metadata(job_id_input)
                if job_data:
                    # Carrega o roteiro
                    st.session_state["roteiro_gerado"] = job_data.get("roteiro")
                    st.session_state["leitura_montada"] = job_data.get("leitura_montada", "")
                    st.session_state["meta_dados"] = job_data.get("meta_dados", {})

                    # 2. Baixa arquivos
                    urls_arquivos = job_data.get("urls_arquivos", [])
                    if len(urls_arquivos) == 0:
                        st.warning("Nenhum arquivo de imagem/áudio encontrado no Job ID. Verifique o GAS.")
                    
                    images, audios = download_files_from_urls(urls_arquivos)
                    st.session_state["generated_images_blocks"] = images
                    st.session_state["generated_audios_blocks"] = audios
                    
                    status.update(label=f"Job {job_id_input} carregado com sucesso!", state="complete")
                    st.rerun()
                else:
                    st.session_state["job_id_ativo"] = None # Falha ao carregar
                    status.update(label=f"Falha ao carregar Job {job_id_input}.", state="error")
        else:
            st.warning("Por favor, insira um Job ID.")

    st.markdown("---")
    st.subheader("⚙️ Modo 2: Edição Manual (Fallback)")
    # === FIM DO NOVO BLOCO ===
    
    if not st.session_state.get("roteiro_gerado"):
        st.warning("⚠️ Gere o roteiro na Aba 1 ou Carregue um Job ID acima.")
        st.stop()
    
    # ... (O resto da TAB 4 permanece inalterado) ...
    # Lógica de visualização, geração manual (fallback) e renderização...

    roteiro = st.session_state["roteiro_gerado"]
    blocos_config = [
        {"id": "hook", "label": "🎣 HOOK", "prompt_key": "prompt_hook", "text_key": "hook"},
        {"id": "leitura", "label": "📖 LEITURA", "prompt_key": "prompt_leitura", "text_key": "leitura_montada"}, 
        {"id": "reflexão", "label": "💭 REFLEXÃO", "prompt_key": "prompt_reflexão", "text_key": "reflexão"},
        {"id": "aplicação", "label": "🌟 APLICAÇÃO", "prompt_key": "prompt_aplicacao", "text_key": "aplicação"},
        {"id": "oração", "label": "🙏 ORAÇÃO", "prompt_key": "prompt_oração", "text_key": "oração"},
        {"id": "thumbnail", "label": "🖼️ THUMBNAIL", "prompt_key": "prompt_geral", "text_key": None}
    ]

    st.info(f"⚙️ Config: **{motor_escolhido}** | Resolução: **{resolucao_escolhida}** | TTS: **{tts_motor_escolhido}**")

    # Botões de Geração em Lote (Áudio/Imagem)
    col_batch_1, col_batch_2 = st.columns(2)
    with col_batch_1:
        if st.button("🔊 Gerar Todos os Áudios", use_container_width=True):
            with st.status("Gerando áudios em lote...", expanded=True) as status:
                total = len([b for b in blocos_config if b["text_key"]])
                count = 0
                for b in blocos_config:
                    if not b["text_key"]: continue
                    bid = b["id"]
                    txt = roteiro.get(b["text_key"]) if bid != "leitura" else st.session_state.get("leitura_montada", "")
                    if txt:
                        st.write(f"Gerando áudio: {b['label']}...")
                        try:
                            audio = despachar_geracao_audio(txt)
                            st.session_state["generated_audios_blocks"][bid] = audio
                            count += 1
                        except Exception as e:
                            st.error(f"Erro em {bid}: {e}")
                status.update(label=f"Concluído! {count}/{total} áudios gerados.", state="complete")
                st.rerun()

    with col_batch_2:
        if st.button("✨ Gerar Todas as Imagens", use_container_width=True):
            with st.status("Gerando imagens em lote...", expanded=True) as status:
                total = len(blocos_config)
                count = 0
                for i, b in enumerate(blocos_config):
                    bid = b["id"]
                    prompt = roteiro.get(b["prompt_key"], "")
                    if prompt:
                        st.write(f"Gerando imagem ({i+1}/{total}): {b['label']}...")
                        try:
                            img = despachar_geracao_imagem(prompt, motor_escolhido, resolucao_escolhida)
                            st.session_state["generated_images_blocks"][bid] = img
                            count += 1
                        except Exception as e:
                            st.error(f"Erro: {e}")
                status.update(label=f"Concluído! {count}/{total} imagens geradas.", state="complete")
                st.rerun()

    st.divider()

    for bloco in blocos_config:
        block_id = bloco["id"]
        with st.container(border=True):
            st.subheader(bloco["label"])
            col_text, col_media = st.columns([1, 1.2])
            with col_text:
                if bloco["text_key"]:
                    txt_content = roteiro.get(bloco["text_key"]) if block_id != "leitura" else st.session_state.get("leitura_montada", "")
                    st.caption("📜 Texto para Narração:")
                    st.markdown(f"_{txt_content[:250]}..._" if txt_content else "_Sem texto_")
                    if st.button(f"🔊 Gerar Áudio ({block_id})", key=f"btn_audio_{block_id}"):
                        if txt_content:
                            try:
                                # Chama o dispatcher (agora só gTTS)
                                audio = despachar_geracao_audio(txt_content)
                                st.session_state["generated_audios_blocks"][block_id] = audio
                                st.rerun()
                            except Exception as e:
                                st.error(f"Erro áudio: {e}")
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
                c_gen, c_up = st.columns([1.5, 2])
                with c_gen:
                    if st.button(f"✨ Gerar ({resolucao_escolhida.split()[0]})", key=f"btn_gen_{block_id}"):
                        if prompt_content:
                            with st.spinner(f"Criando no formato {resolucao_escolhida}..."):
                                try:
                                    # Chama o despachante (agora só Pollinations)
                                    img = despachar_geracao_imagem(prompt_content, motor_escolhido, resolucao_escolhida)
                                    st.session_state["generated_images_blocks"][block_id] = img
                                    st.success("Gerada!")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Erro: {e}")
                        else:
                            st.warning("Sem prompt.")
                with c_up:
                    uploaded_file = st.file_uploader("Ou envie a sua:", type=["png", "jpg", "jpeg"], key=f"upload_{block_id}")
                    if uploaded_file is not None:
                        bytes_data = uploaded_file.read()
                        st.session_state["generated_images_blocks"][block_id] = BytesIO(bytes_data)
                        st.success("Enviada!")

    st.divider()
    st.header("🎬 Finalização")
    usar_overlay = st.checkbox("Adicionar Cabeçalho (Overlay Personalizado)", value=True)
    
    st.subheader("🎵 Música de Fundo (Opcional)")
    
    # Check if saved music exists
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

    if st.button("Renderizar Vídeo Completo (Unir tudo)", type="primary"):
        with st.status("Renderizando vídeo com efeitos...", expanded=True) as status:
            try:
                blocos_relevantes = [b for b in blocos_config if b["id"] != "thumbnail"]
                if not shutil_which("ffmpeg"):
                    status.update(label="FFmpeg não encontrado!", state="error")
                    st.stop()
                
                font_path = resolve_font_path(font_choice, uploaded_font_file)
                if usar_overlay and not font_path:
                    st.warning("⚠️ Fonte não encontrada. O overlay pode falhar.")
                
                temp_dir = tempfile.mkdtemp()
                clip_files = []
                
                meta = st.session_state.get("meta_dados", {})
                txt_dt = meta.get("data", "")
                txt_ref = meta.get("ref", "")
                
                map_titulos = {"hook": "EVANGELHO", "leitura": "EVANGELHO", "reflexão": "REFLEXÃO", "aplicação": "APLICAÇÃO", "oração": "ORAÇÃO"}
                
                res_params = get_resolution_params(resolucao_escolhida)
                s_out = f"{res_params['w']}x{res_params['h']}"
                
                sets = st.session_state["overlay_settings"]
                speed_val = sets["effect_speed"] * 0.0005 
                
                if sets["effect_type"] == "Zoom In (Ken Burns)":
                    zoom_expr = f"z='min(zoom+{speed_val},1.5)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                elif sets["effect_type"] == "Zoom Out":
                    zoom_expr = f"z='max(1,1.5-{speed_val}*on)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                elif sets["effect_type"] == "Panorâmica Esquerda":
                    zoom_expr = f"z=1.2:x='min(x+{speed_val}*100,iw-iw/zoom)':y='(ih-ih/zoom)/2'"
                elif sets["effect_type"] == "Panorâmica Direita":
                    zoom_expr = f"z=1.2:x='max(0,x-{speed_val}*100)':y='(ih-ih/zoom)/2'"
                else: 
                    zoom_expr = "z=1:x=0:y=0" 

                for b in blocos_relevantes:
                    bid = b["id"]
                    img_bio = st.session_state["generated_images_blocks"].get(bid)
                    audio_bio = st.session_state["generated_audios_blocks"].get(bid)
                    if not img_bio or not audio_bio: continue
                        
                    st.write(f"Processando clipe: {bid}...")
                    img_path = os.path.join(temp_dir, f"{bid}.png")
                    audio_path = os.path.join(temp_dir, f"{bid}.mp3")
                    clip_path = os.path.join(temp_dir, f"{bid}.mp4")
                    
                    img_bio.seek(0); audio_bio.seek(0)
                    with open(img_path, "wb") as f: f.write(img_bio.read())
                    with open(audio_path, "wb") as f: f.write(audio_bio.read())
                    
                    dur = get_audio_duration_seconds(audio_path) or 5.0
                    frames = int(dur * 25)

                    vf_filters = []
                    if sets["effect_type"] != "Estático (Sem movimento)":
                        vf_filters.append(f"zoompan={zoom_expr}:d={frames}:s={s_out}")
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
                    concat_list = os.path.join(temp_dir, "list.txt")
                    with open(concat_list, "w") as f:
                        for p in clip_files: f.write(f"file '{p}'\n")
                    
                    temp_video = os.path.join(temp_dir, "temp_video.mp4")
                    run_cmd(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list, "-c", "copy", temp_video])
                    
                    final_path = os.path.join(temp_dir, "final.mp4")
                    
                    # Lógica de Música: 1. Uploaded, 2. Saved Default, 3. None
                    music_source_path = None
                    
                    if music_upload:
                        music_source_path = os.path.join(temp_dir, "bg.mp3")
                        with open(music_source_path, "wb") as f: f.write(music_upload.getvalue())
                    elif saved_music_exists:
                        music_source_path = SAVED_MUSIC_FILE
                        
                    if music_source_path:
                        cmd_mix = [
                            "ffmpeg", "-y",
                            "-i", temp_video,
                            "-stream_loop", "-1", "-i", music_source_path,
                            "-filter_complex", f"[1:a]volume={music_vol}[bg];[0:a][bg]amix=inputs=2:duration=first:dropout_transition=2[a]",
                            "-map", "0:v", "-map", "[a]",
                            "-c:v", "copy", "-c:a", "aac", "-shortest",
                            final_path
                        ]
                        run_cmd(cmd_mix)
                    else:
                        os.rename(temp_video, final_path)

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
        
        # Gera o JSON de metadados para redes sociais
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
        # Permite download para jobs manuais
        st.download_button("⬇️ Baixar MP4", st.session_state["video_final_bytes"], "video_jhonata.mp4", "video/mp4")
# --------- TAB 5: HISTÓRICO ----------
with tab5:
    st.info("Histórico em desenvolvimento.")

st.markdown("---")
st.caption("Studio Jhonata v21.0 - Disparo de Job no GAS")
