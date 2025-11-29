# app.py — Studio Jhonata (COMPLETO v7.0)
# Features: Ordem Ajustada (Hook->Leitura->Reflexão), Editor Full, Upload, Resoluções, Overlay
import os
import re
import json
import time
import tempfile
import traceback
import subprocess
import urllib.parse
import random
from io import BytesIO
from datetime import date
from typing import List, Optional, Tuple, Dict
import base64

import requests
from PIL import Image
import streamlit as st

# Force ffmpeg path for imageio if needed (Streamlit Cloud)
os.environ.setdefault("IMAGEIO_FFMPEG_EXE", "/usr/bin/ffmpeg")

# =========================
# Page config
# =========================
st.set_page_config(
    page_title="Studio Jhonata",
    layout="wide",
    initial_sidebar_state="expanded",
)

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
# Limpeza do texto bíblico
# =========================
def limpar_texto_evangelho(texto: str) -> str:
    if not texto:
        return ""
    texto_limpo = texto.replace("\n", " ").strip()
    texto_limpo = re.sub(r"\b(\d{1,3})(?=[A-Za-zÁ-Úá-ú])", "", texto_limpo)
    texto_limpo = re.sub(r"\s{2,}", " ", texto_limpo)
    return texto_limpo.strip()

# =========================
# Extrair referência bíblica
# =========================
def extrair_referencia_biblica(titulo: str):
    if not titulo:
        return None
    m = re.search(r"(?:São|S\.|Sao|San|St\.?)\s*([A-Za-zÁ-Úá-ú]+)[^\d]*(\d+)[^\d]*(\d+(?:[-–]\d+)?)", titulo, flags=re.IGNORECASE)
    if not m:
        return None
    evangelista = m.group(1).strip()
    capitulo = m.group(2).strip()
    versiculos_raw = m.group(3).strip()
    versiculos = versiculos_raw.replace("-", " a ").replace("–", " a ")
    return {"evangelista": evangelista, "capitulo": capitulo, "versiculos": versiculos}

def formatar_referencia_curta(ref_biblica):
    if not ref_biblica:
        return ""
    return f"{ref_biblica['evangelista']}, Cap. {ref_biblica['capitulo']}, {ref_biblica['versiculos']}"

# =========================
# Análise de personagens via Groq
# =========================
def analisar_personagens_groq(texto_evangelho: str, banco_personagens: dict):
    client = inicializar_groq()
    system_prompt = (
        "Você é especialista em análise bíblica.\n"
        "Analise o texto e identifique TODOS os personagens bíblicos mencionados.\n\n"
        "Formato EXATO da resposta:\n\n"
        "PERSONAGENS: nome1; nome2; nome3\n\n"
        "NOVOS: NomeNovo|descrição_detalhada_aparência_física_roupas_idade_estilo (apenas se não existir no banco)\n\n"
        f"BANCO EXISTENTE: {'; '.join(banco_personagens.keys())}\n\n"
        "Exemplo:\n"
        "PERSONAGENS: Jesus; Pedro; fariseus\n"
        "NOVOS: Mulher Samaritana|mulher de 35 anos, pele morena, véu colorido, jarro d'água, expressão curiosa, túnica tradicional\n"
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
                    if not nome:
                        continue
                    personagens_detectados[nome] = desc
                    banco_personagens[nome] = desc
        return personagens_detectados
    except Exception:
        return {}

# =========================
# APIs Liturgia
# =========================
def buscar_liturgia_api1(data_str: str):
    url = f"https://api-liturgia-diaria.vercel.app/?date={data_str}"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        dados = resp.json()
        today = dados.get("today", {})
        readings = today.get("readings", {})
        gospel = readings.get("gospel")
        if not gospel:
            return None
        referencia_liturgica = today.get("entry_title", "").strip() or "Evangelho do dia"
        titulo = (
            gospel.get("head_title", "")
            or gospel.get("title", "")
            or "Evangelho de Jesus Cristo"
        ).strip()
        texto = gospel.get("text", "").strip()
        if not texto:
            return None
        texto_limpo = limpar_texto_evangelho(texto)
        ref_biblica = extrair_referencia_biblica(titulo)
        return {
            "fonte": "api-liturgia-diaria.vercel.app",
            "titulo": titulo,
            "referencia_liturgica": referencia_liturgica,
            "texto": texto_limpo,
            "ref_biblica": ref_biblica,
        }
    except Exception:
        return None

def buscar_liturgia_api2(data_str: str):
    url = f"https://liturgia.up.railway.app/v2/{data_str}"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        dados = resp.json()
        lit = dados.get("liturgia", {})
        ev = lit.get("evangelho") or lit.get("evangelho_do_dia") or {}
        if not ev:
            return None
        texto = ev.get("texto", "") or ev.get("conteudo", "")
        if not texto:
            return None
        texto_limpo = limpar_texto_evangelho(texto)
        return {
            "fonte": "liturgia.up.railway.app",
            "titulo": "Evangelho do dia",
            "referencia_liturgica": "Evangelho do dia",
            "texto": texto_limpo,
            "ref_biblica": None,
        }
    except Exception:
        return None

def obter_evangelho_com_fallback(data_str: str):
    ev = buscar_liturgia_api1(data_str)
    if ev:
        st.info("📡 Usando api-liturgia-diaria.vercel.app")
        return ev
    ev = buscar_liturgia_api2(data_str)
    if ev:
        st.info("📡 Usando liturgia.up.railway.app")
        return ev
    st.error("❌ Não foi possível obter o Evangelho")
    return None

# =========================
# Roteiro + Prompts
# =========================
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
        st.error(f"❌ Erro Groq: {e}")
        return None

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
# FUNÇÕES DE ÁUDIO & VÍDEO
# =========================

def gerar_audio_gtts(texto: str) -> Optional[BytesIO]:
    if not texto or not texto.strip():
        return None
    mp3_fp = BytesIO()
    try:
        from gtts import gTTS  # type: ignore
        tts = gTTS(text=texto, lang="pt", slow=False)
        tts.write_to_fp(mp3_fp)
        mp3_fp.seek(0)
        return mp3_fp
    except Exception as e:
        raise RuntimeError(f"Erro gTTS: {e}")

# =========================
# FUNÇÕES DE IMAGEM (MOTORES COM SUPORTE A RESOLUÇÃO)
# =========================

def get_resolution_params(choice: str) -> dict:
    """Retorna largura, altura e aspect ratio string baseado na escolha"""
    if "9:16" in choice:
        return {"w": 720, "h": 1280, "ratio": "9:16"}
    elif "16:9" in choice:
        return {"w": 1280, "h": 720, "ratio": "16:9"}
    else: # 1:1
        return {"w": 1024, "h": 1024, "ratio": "1:1"}

def gerar_imagem_pollinations_flux(prompt: str, width: int, height: int) -> BytesIO:
    """Modelo Flux via Pollinations com dimensão customizável"""
    prompt_clean = prompt.replace("\n", " ").strip()[:800]
    prompt_encoded = urllib.parse.quote(prompt_clean)
    seed = random.randint(0, 999999)
    url = f"https://image.pollinations.ai/prompt/{prompt_encoded}?model=flux&width={width}&height={height}&seed={seed}&nologo=true"
    
    r = requests.get(url, timeout=40)
    r.raise_for_status()
    bio = BytesIO(r.content)
    bio.seek(0)
    return bio

def gerar_imagem_pollinations_turbo(prompt: str, width: int, height: int) -> BytesIO:
    """Modelo Turbo via Pollinations com dimensão customizável"""
    prompt_clean = prompt.replace("\n", " ").strip()[:800]
    prompt_encoded = urllib.parse.quote(prompt_clean)
    seed = random.randint(0, 999999)
    url = f"https://image.pollinations.ai/prompt/{prompt_encoded}?width={width}&height={height}&seed={seed}&nologo=true"
    
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    bio = BytesIO(r.content)
    bio.seek(0)
    return bio

def gerar_imagem_google_imagen(prompt: str, ratio: str) -> BytesIO:
    """Google Imagen 3 via API com aspect ratio"""
    gem_key = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not gem_key:
        raise RuntimeError("GEMINI_API_KEY não encontrada.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-001:predict?key={gem_key}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "instances": [{"prompt": prompt}],
        "parameters": {
            "sampleCount": 1,
            "aspectRatio": ratio
        }
    }
    
    r = requests.post(url, headers=headers, json=payload, timeout=45)
    r.raise_for_status()
    data = r.json()
    
    if "predictions" in data and len(data["predictions"]) > 0:
        b64 = data["predictions"][0]["bytesBase64Encoded"]
        bio = BytesIO(base64.b64decode(b64))
        bio.seek(0)
        return bio
    else:
        raise RuntimeError("Resposta inválida do Google Imagen.")

def despachar_geracao_imagem(prompt: str, motor: str, res_choice: str) -> BytesIO:
    """Redireciona para a função correta com a resolução correta"""
    params = get_resolution_params(res_choice)
    
    if motor == "Pollinations Flux (Padrão)":
        return gerar_imagem_pollinations_flux(prompt, params["w"], params["h"])
    elif motor == "Pollinations Turbo":
        return gerar_imagem_pollinations_turbo(prompt, params["w"], params["h"])
    elif motor == "Google Imagen":
        return gerar_imagem_google_imagen(prompt, params["ratio"])
    else:
        return gerar_imagem_pollinations_flux(prompt, params["w"], params["h"])

# =========================
# Helpers
# =========================
import shutil as _shutil

def shutil_which(bin_name: str) -> Optional[str]:
    return _shutil.which(bin_name)

def run_cmd(cmd: List[str]):
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""
        raise RuntimeError(f"Comando falhou: {' '.join(cmd)}\nSTDERR: {stderr}")

def get_audio_duration_seconds(path: str) -> Optional[float]:
    if not shutil_which("ffprobe"):
        return None
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path]
    try:
        p = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out = p.stdout.decode().strip()
        return float(out) if out else None
    except Exception:
        return None

def resolve_font_path(font_choice: str, uploaded_font: Optional[BytesIO]) -> Optional[str]:
    """Resolve o caminho da fonte baseado na escolha do usuário"""
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

# =========================
# Interface principal
# =========================
st.title("✨ Studio Jhonata - Automação Litúrgica")
st.markdown("---")

# ---- SIDEBAR CONFIG ----
st.sidebar.title("⚙️ Configurações")

# Seletor de Motor
motor_escolhido = st.sidebar.selectbox(
    "🎨 Motor de Imagem",
    ["Pollinations Flux (Padrão)", "Pollinations Turbo", "Google Imagen"],
    index=0
)

# Seletor de Resolução (Novo)
resolucao_escolhida = st.sidebar.selectbox(
    "📏 Resolução do Vídeo",
    ["9:16 (Vertical/Stories)", "16:9 (Horizontal/YouTube)", "1:1 (Quadrado/Feed)"],
    index=0
)

st.sidebar.markdown("---")
st.sidebar.markdown("### 🅰️ Fonte do Vídeo")
font_choice = st.sidebar.selectbox("Estilo da Fonte", ["Padrão (Sans)", "Serif", "Monospace", "Upload Personalizada"], index=0)
uploaded_font_file = None
if font_choice == "Upload Personalizada":
    uploaded_font_file = st.sidebar.file_uploader("Arquivo .ttf", type=["ttf"])

# Info de status
st.sidebar.info(f"Modo: {motor_escolhido}\nFormato: {resolucao_escolhida}")

if "personagens_biblicos" not in st.session_state:
    st.session_state.personagens_biblicos = inicializar_personagens()

# session state
if "roteiro_gerado" not in st.session_state:
    st.session_state["roteiro_gerado"] = None
if "leitura_montada" not in st.session_state:
    st.session_state["leitura_montada"] = ""
if "generated_images_blocks" not in st.session_state:
    st.session_state["generated_images_blocks"] = {}
if "generated_audios_blocks" not in st.session_state:
    st.session_state["generated_audios_blocks"] = {}
if "video_final_bytes" not in st.session_state:
    st.session_state["video_final_bytes"] = None
if "meta_dados" not in st.session_state:
    st.session_state["meta_dados"] = {"data": "", "ref": ""}

tab1, tab2, tab3, tab4 = st.tabs(
    ["📖 Gerar Roteiro", "🎨 Personagens", "🎥 Fábrica Vídeo (Editor)", "📊 Histórico"]
)

# --------- TAB 1: ROTEIRO ----------
with tab1:
    st.header("🚀 Gerador de Roteiro")
    col1, col2 = st.columns([2, 1])
    with col1:
        data_selecionada = st.date_input(
            "📅 Data da liturgia:", value=date.today(), min_value=date(2023, 1, 1)
        )
    with col2:
        st.info("Status: ✅ pronto para gerar")

    if st.button("🚀 Gerar Roteiro Completo", type="primary"):
        data_str = data_selecionada.strftime("%Y-%m-%d")
        data_formatada_display = data_selecionada.strftime("%d.%m.%Y") 

        with st.status("📝 Gerando roteiro...", expanded=True) as status:
            st.write("🔍 Buscando Evangelho...")
            liturgia = obter_evangelho_com_fallback(data_str)
            if not liturgia:
                status.update(label="Falha ao buscar evangelho", state="error")
                st.stop()

            ref_curta = formatar_referencia_curta(liturgia.get("ref_biblica"))
            st.session_state["meta_dados"] = {
                "data": data_formatada_display,
                "ref": ref_curta or "Evangelho do Dia"
            }

            st.write("🤖 Analisando personagens com IA...")
            personagens_detectados = analisar_personagens_groq(
                liturgia["texto"], st.session_state.personagens_biblicos
            )

            st.write("✨ Criando roteiro e prompts...")
            roteiro = gerar_roteiro_com_prompts_groq(
                liturgia["texto"],
                liturgia["referencia_liturgica"],
                {**st.session_state.personagens_biblicos, **personagens_detectados},
            )

            if roteiro:
                status.update(label="Roteiro gerado com sucesso!", state="complete", expanded=False)
            else:
                status.update(label="Erro ao gerar roteiro", state="error")
                st.stop()

        leitura_montada = montar_leitura_com_formula(
            liturgia["texto"], liturgia.get("ref_biblica")
        )
        st.session_state["roteiro_gerado"] = roteiro
        st.session_state["leitura_montada"] = leitura_montada
        st.rerun()

    if st.session_state.get("roteiro_gerado"):
        roteiro = st.session_state["roteiro_gerado"]
        st.markdown("---")
        
        # AJUSTE DE ORDEM VISUAL (Hook -> Leitura -> Reflexão -> Aplicação)
        col_esq, col_dir = st.columns(2)
        with col_esq:
            st.markdown("### 🎣 HOOK")
            st.markdown(roteiro.get("hook", ""))
            st.caption("Prompt:")
            st.code(roteiro.get("prompt_hook", ""), language="text")

            st.markdown("### 📖 LEITURA")
            st.markdown(st.session_state.get("leitura_montada", "")[:300] + "...")
            st.code(roteiro.get("prompt_leitura", ""), language="text")

        with col_dir:
            st.markdown("### 💭 REFLEXÃO")
            st.markdown(roteiro.get("reflexão", ""))
            st.code(roteiro.get("prompt_reflexão", ""), language="text")
            
            st.markdown("### 🌟 APLICAÇÃO")
            st.markdown(roteiro.get("aplicação", ""))
            st.code(roteiro.get("prompt_aplicacao", ""), language="text")
        
        st.markdown("### 🙏 ORAÇÃO")
        st.markdown(roteiro.get("oração", ""))
        st.code(roteiro.get("prompt_oração", ""), language="text")
        
        st.markdown("### 🖼️ THUMBNAIL")
        st.code(roteiro.get("prompt_geral", ""), language="text")
        
        st.success("Roteiro gerado! Vá para a aba 'Fábrica Vídeo' para produzir o conteúdo cena a cena.")

# --------- TAB 2: PERSONAGENS ----------
with tab2:
    st.header("🎨 Banco de Personagens")
    banco = st.session_state.personagens_biblicos.copy()
    col1, col2 = st.columns(2)
    with col1:
        for i, (nome, desc) in enumerate(banco.items()):
            with st.expander(f"✏️ {nome}"):
                novo_nome = st.text_input(f"Nome", value=nome, key=f"n_{i}")
                nova_desc = st.text_area(f"Desc", value=desc, key=f"d_{i}")
                if st.button("Salvar", key=f"s_{i}"):
                    if novo_nome != nome: del st.session_state.personagens_biblicos[nome]
                    st.session_state.personagens_biblicos[novo_nome] = nova_desc
                    st.rerun()
                if st.button("Apagar", key=f"a_{i}"):
                    del st.session_state.personagens_biblicos[nome]
                    st.rerun()
    with col2:
        st.markdown("### ➕ Novo")
        nn = st.text_input("Nome", key="new_n")
        nd = st.text_area("Descrição", key="new_d")
        if st.button("Adicionar") and nn and nd:
            st.session_state.personagens_biblicos[nn] = nd
            st.rerun()

# --------- TAB 3: FÁBRICA DE VÍDEO ----------
with tab3:
    st.header("🎥 Editor de Cenas")
    
    if not st.session_state.get("roteiro_gerado"):
        st.warning("⚠️ Gere o roteiro na Aba 1 primeiro.")
        st.stop()
    
    roteiro = st.session_state["roteiro_gerado"]
    
    # AJUSTE DE ORDEM DE PROCESSAMENTO (Hook -> Leitura -> Reflexão -> Aplicação -> Oração)
    blocos_config = [
        {"id": "hook", "label": "🎣 HOOK", "prompt_key": "prompt_hook", "text_key": "hook"},
        {"id": "leitura", "label": "📖 LEITURA", "prompt_key": "prompt_leitura", "text_key": "leitura_montada"}, 
        {"id": "reflexão", "label": "💭 REFLEXÃO", "prompt_key": "prompt_reflexão", "text_key": "reflexão"},
        {"id": "aplicação", "label": "🌟 APLICAÇÃO", "prompt_key": "prompt_aplicacao", "text_key": "aplicação"},
        {"id": "oração", "label": "🙏 ORAÇÃO", "prompt_key": "prompt_oração", "text_key": "oração"},
        {"id": "thumbnail", "label": "🖼️ THUMBNAIL", "prompt_key": "prompt_geral", "text_key": None}
    ]

    # Info da config atual
    st.info(f"⚙️ Config: **{motor_escolhido}** | Resolução: **{resolucao_escolhida}**")

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
                                audio = gerar_audio_gtts(txt_content)
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
                                    img = despachar_geracao_imagem(prompt_content, motor_escolhido, resolucao_escolhida)
                                    st.session_state["generated_images_blocks"][block_id] = img
                                    st.success("Gerada!")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Erro: {e}")
                        else:
                            st.warning("Sem prompt.")
                
                with c_up:
                    uploaded_file = st.file_uploader(
                        "Ou envie a sua:", type=["png", "jpg", "jpeg"], key=f"upload_{block_id}"
                    )
                    if uploaded_file is not None:
                        bytes_data = uploaded_file.read()
                        st.session_state["generated_images_blocks"][block_id] = BytesIO(bytes_data)
                        st.success("Enviada!")

    st.divider()
    
    st.header("🎬 Finalização")
    usar_overlay = st.checkbox("Adicionar Cabeçalho (Overlay: Evangelho, Data, Ref)", value=False)

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
                
                map_titulos = {
                    "hook": "EVANGELHO", "leitura": "EVANGELHO",
                    "reflexão": "REFLEXÃO", "aplicação": "APLICAÇÃO", "oração": "ORAÇÃO"
                }

                # Parâmetros baseados na resolução
                res_params = get_resolution_params(resolucao_escolhida)
                w_out = res_params["w"]
                h_out = res_params["h"]
                s_out = f"{w_out}x{h_out}"

                for b in blocos_relevantes:
                    bid = b["id"]
                    img_bio = st.session_state["generated_images_blocks"].get(bid)
                    audio_bio = st.session_state["generated_audios_blocks"].get(bid)
                    
                    if not img_bio or not audio_bio:
                        continue
                        
                    st.write(f"Processando clipe: {bid}...")
                    
                    img_path = os.path.join(temp_dir, f"{bid}.png")
                    audio_path = os.path.join(temp_dir, f"{bid}.mp3")
                    clip_path = os.path.join(temp_dir, f"{bid}.mp4")
                    
                    img_bio.seek(0)
                    with open(img_path, "wb") as f: f.write(img_bio.read())
                    audio_bio.seek(0)
                    with open(audio_path, "wb") as f: f.write(audio_bio.read())
                    
                    dur = get_audio_duration_seconds(audio_path) or 5.0
                    frames = int(dur * 25)

                    # Filtro Zoom Pan Adaptado para a resolução
                    vf_filters = [
                        f"zoompan=z='min(zoom+0.0010,1.5)':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={s_out}",
                        f"fade=t=in:st=0:d=1,fade=t=out:st={dur-0.5}:d=0.5"
                    ]

                    # Overlay Adaptado (Y posicionado relativo a altura)
                    if usar_overlay and font_path:
                        titulo_atual = map_titulos.get(bid, "EVANGELHO")
                        
                        y1 = 40
                        y2 = 90
                        y3 = 130
                        
                        vf_filters.append(f"drawtext=fontfile='{font_path}':text='{titulo_atual}':fontcolor=white:fontsize=40:x=(w-text_w)/2:y={y1}:shadowcolor=black:shadowx=2:shadowy=2")
                        vf_filters.append(f"drawtext=fontfile='{font_path}':text='{txt_dt}':fontcolor=white:fontsize=28:x=(w-text_w)/2:y={y2}:shadowcolor=black:shadowx=2:shadowy=2")
                        vf_filters.append(f"drawtext=fontfile='{font_path}':text='{txt_ref}':fontcolor=white:fontsize=24:x=(w-text_w)/2:y={y3}:shadowcolor=black:shadowx=2:shadowy=2")

                    filter_complex = ",".join(vf_filters)
                    
                    cmd = [
                        "ffmpeg", "-y", 
                        "-loop", "1", "-i", img_path, 
                        "-i", audio_path,
                        "-vf", filter_complex,
                        "-c:v", "libx264", "-t", f"{dur}", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-shortest", 
                        clip_path
                    ]
                    run_cmd(cmd)
                    clip_files.append(clip_path)
                
                if clip_files:
                    concat_list = os.path.join(temp_dir, "list.txt")
                    with open(concat_list, "w") as f:
                        for p in clip_files: f.write(f"file '{p}'\n")
                    
                    final_video = os.path.join(temp_dir, "final.mp4")
                    run_cmd(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list, "-c", "copy", final_video])
                    
                    with open(final_video, "rb") as f:
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
        st.download_button("⬇️ Baixar MP4", st.session_state["video_final_bytes"], "video_jhonata.mp4", "video/mp4")

# --------- TAB 4 ----------
with tab4:
    st.info("Histórico em desenvolvimento.")

st.markdown("---")
st.caption("Studio Jhonata v7.0 - Ordem Reajustada")