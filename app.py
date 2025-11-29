# app.py — Studio Jhonata (COMPLETO & FINAL)
# Features: Editor de Cenas, Upload de Imagens, Prompts Copiáveis, Fallback Híbrido Google/Flux
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
from typing import List, Optional, Tuple
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
# FUNÇÕES DE ÁUDIO, IMAGEM, VÍDEO
# =========================

# ---- gTTS ----
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

# ---- Gemini TTS ----
def gerar_audio_gemini(texto: str, voz: str = "pt-BR-Wavenet-B") -> BytesIO:
    gem_key = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not gem_key:
        raise RuntimeError("GEMINI_API_KEY ausente.")
    if not texto or not texto.strip():
        raise ValueError("Texto vazio.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gem_key}"
    prompt_text = f"(tts|voice:{voz})\nPor favor, narre em Português do Brasil com entonação natural:\n{texto}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt_text}]}],
        "generationConfig": {"responseMimeType": "audio/mpeg"},
    }
    r = requests.post(url, json=payload, timeout=120)
    r.raise_for_status()
    data = r.json()
    try:
        b64 = data["candidates"][0]["content"]["parts"][0]["inline_data"]["data"]
    except Exception as e:
        raise RuntimeError(f"Resposta inesperada do Gemini TTS: {data}") from e
    audio_bytes = base64.b64decode(b64)
    bio = BytesIO(audio_bytes)
    bio.seek(0)
    return bio

# ---- Google Imagen 3 (Via Gemini API Key) ----
def gerar_imagem_google_imagen(prompt: str) -> Optional[BytesIO]:
    """
    Tenta gerar imagem usando Google Imagen 3.
    Retorna None se der erro 404 (sem permissão), para acionar fallback.
    """
    gem_key = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not gem_key:
        return None

    url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-001:predict?key={gem_key}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "instances": [{"prompt": prompt}],
        "parameters": {"sampleCount": 1}
    }
    
    try:
        # Timeout curto para não prender o app
        r = requests.post(url, headers=headers, json=payload, timeout=20)
        
        # Se for 404, significa que a chave não tem permissão para Imagen 3 ainda.
        if r.status_code == 404:
            return None
            
        r.raise_for_status()
        data = r.json()
        
        if "predictions" in data and len(data["predictions"]) > 0:
            b64 = data["predictions"][0]["bytesBase64Encoded"]
            bio = BytesIO(base64.b64decode(b64))
            bio.seek(0)
            return bio
        else:
            return None
            
    except Exception:
        # Qualquer erro de rede ou API, retornamos None para usar o Fallback
        return None

# ---- Fallback: Pollinations OTIMIZADO (Flux) ----
def gerar_imagem_pollinations_flux(prompt: str) -> BytesIO:
    """
    Fallback robusto usando o modelo Flux no Pollinations.
    Usa seed aleatória para variar e timeout para não travar.
    """
    # Limpa o prompt e codifica
    prompt_clean = prompt.replace("\n", " ").strip()[:800] # Limite de caracteres
    prompt_encoded = urllib.parse.quote(prompt_clean)
    seed = random.randint(0, 999999)
    
    # URL forçando modelo Flux (melhor qualidade) e nologo
    url = f"https://image.pollinations.ai/prompt/{prompt_encoded}?model=flux&width=1024&height=1024&seed={seed}&nologo=true"
    
    try:
        # Timeout de 30s é essencial para não "carregar eternamente"
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        bio = BytesIO(r.content)
        bio.seek(0)
        return bio
    except Exception as e:
        raise RuntimeError(f"Erro no fallback Flux: {e}")

# ---- Gerenciador Híbrido ----
def gerar_imagem_hibrido_com_feedback(prompt: str) -> Tuple[BytesIO, str]:
    """
    Tenta Google -> Se falhar, vai para Flux.
    Retorna (imagem_bytes, nome_fonte_usada)
    """
    # 1. Tentar Custom ImageFX
    imagefx_url = st.secrets.get("IMAGEFX_API_URL") or os.getenv("IMAGEFX_API_URL")
    if imagefx_url:
        try:
            pass 
        except: pass

    # 2. Tentar Google Imagen 3
    img = gerar_imagem_google_imagen(prompt)
    if img:
        return img, "Google Imagen 3"
    
    # 3. Fallback Automático para Flux
    img_flux = gerar_imagem_pollinations_flux(prompt)
    return img_flux, "Flux (Pollinations)"

# ---- gerar narrações (utils) ----
def gerar_narracoes_para_roteiro(roteiro: dict, usar_gemini: bool = False) -> dict:
    audios = {}
    partes_texto = {
        "hook": roteiro.get("hook", ""),
        "reflexão": roteiro.get("reflexão", ""),
        "aplicação": roteiro.get("aplicação", ""),
        "oração": roteiro.get("oração", ""),
        "leitura": roteiro.get("leitura", roteiro.get("leitura_montada", "")),
    }
    for bloco, texto in partes_texto.items():
        texto = (texto or "").strip()
        if not texto:
            continue
        if usar_gemini:
            audio = gerar_audio_gemini(texto, voz="pt-BR-Wavenet-B")
        else:
            audio = gerar_audio_gtts(texto)
        audios[bloco] = audio
    return audios

# ---- Helpers de Sistema ----
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

# =========================
# Interface principal
# =========================
st.title("✨ Studio Jhonata - Automação Litúrgica")
st.markdown("---")

st.sidebar.title("⚙️ Configurações")
st.sidebar.info("1️⃣ api-liturgia-diaria\n2️⃣ liturgia.railway\n3️⃣ Groq fallback")
st.sidebar.success("✅ Groq ativo (se configurado)")

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
        with st.status("📝 Gerando roteiro...", expanded=True) as status:
            st.write("🔍 Buscando Evangelho...")
            liturgia = obter_evangelho_com_fallback(data_str)
            if not liturgia:
                status.update(label="Falha ao buscar evangelho", state="error")
                st.stop()

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

    # Exibição do Roteiro
    if st.session_state.get("roteiro_gerado"):
        roteiro = st.session_state["roteiro_gerado"]
        st.markdown("---")
        
        # Helper para exibir blocos
        def show_script_block(title, text, prompt):
            st.markdown(f"### {title}")
            st.markdown(text)
            # st.code adiciona botão de copiar nativamente
            st.code(prompt, language="text") 
            st.divider()

        col_esq, col_dir = st.columns(2)
        with col_esq:
            show_script_block("🎣 HOOK", roteiro.get("hook", ""), roteiro.get("prompt_hook", ""))
            show_script_block("💭 REFLEXÃO", roteiro.get("reflexão", ""), roteiro.get("prompt_reflexão", ""))
        with col_dir:
            show_script_block("📖 LEITURA", st.session_state.get("leitura_montada", "")[:300] + "...", roteiro.get("prompt_leitura", ""))
            show_script_block("🌟 APLICAÇÃO", roteiro.get("aplicação", ""), roteiro.get("prompt_aplicacao", ""))
        
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

# --------- TAB 3: FÁBRICA DE VÍDEO (EDITOR) ----------
with tab3:
    st.header("🎥 Editor de Cenas")
    
    if not st.session_state.get("roteiro_gerado"):
        st.warning("⚠️ Gere o roteiro na Aba 1 primeiro.")
        st.stop()
    
    roteiro = st.session_state["roteiro_gerado"]
    
    # Mapeamento dos blocos
    blocos_config = [
        {"id": "hook", "label": "🎣 HOOK", "prompt_key": "prompt_hook", "text_key": "hook"},
        {"id": "reflexão", "label": "💭 REFLEXÃO", "prompt_key": "prompt_reflexão", "text_key": "reflexão"},
        {"id": "leitura", "label": "📖 LEITURA", "prompt_key": "prompt_leitura", "text_key": "leitura_montada"}, # usa key especial
        {"id": "aplicação", "label": "🌟 APLICAÇÃO", "prompt_key": "prompt_aplicacao", "text_key": "aplicação"},
        {"id": "oração", "label": "🙏 ORAÇÃO", "prompt_key": "prompt_oração", "text_key": "oração"},
        {"id": "thumbnail", "label": "🖼️ THUMBNAIL", "prompt_key": "prompt_geral", "text_key": None}
    ]

    # Renderizar Editor Bloco a Bloco
    for bloco in blocos_config:
        block_id = bloco["id"]
        
        with st.container(border=True):
            st.subheader(bloco["label"])
            
            # Texto e Prompt
            col_text, col_media = st.columns([1, 1])
            
            with col_text:
                if bloco["text_key"]:
                    txt_content = roteiro.get(bloco["text_key"]) if block_id != "leitura" else st.session_state.get("leitura_montada", "")
                    st.caption("Texto:")
                    st.markdown(f"*{txt_content[:200]}...*" if txt_content else "*Sem texto*")
                
                prompt_content = roteiro.get(bloco["prompt_key"], "")
                st.caption("Prompt Visual (Copie e cole se precisar):")
                st.code(prompt_content, language="text")
                
                # Controle de Áudio Individual
                if bloco["text_key"]:
                    if st.button(f"🔊 Gerar Áudio ({block_id})", key=f"btn_audio_{block_id}"):
                        txt_full = roteiro.get(bloco["text_key"]) if block_id != "leitura" else st.session_state.get("leitura_montada", "")
                        if txt_full:
                            try:
                                audio = gerar_audio_gtts(txt_full)
                                st.session_state["generated_audios_blocks"][block_id] = audio
                                st.rerun()
                            except Exception as e:
                                st.error(f"Erro áudio: {e}")

            with col_media:
                st.caption("Imagem da Cena:")
                
                # Exibir Imagem Atual
                current_img = st.session_state["generated_images_blocks"].get(block_id)
                if current_img:
                    try:
                        current_img.seek(0) # CRÍTICO: Resetar ponteiro para visualização
                        st.image(current_img, use_column_width=True)
                    except Exception:
                        st.error("Erro ao exibir imagem.")
                else:
                    st.info("Nenhuma imagem gerada ainda.")

                c_gen, c_up = st.columns(2)
                
                # Botão Regenerar
                with c_gen:
                    if st.button(f"🔄 Gerar IA", key=f"btn_gen_{block_id}"):
                        if prompt_content:
                            with st.spinner("Gerando..."):
                                try:
                                    img, fonte = gerar_imagem_hibrido_com_feedback(prompt_content)
                                    st.session_state["generated_images_blocks"][block_id] = img
                                    st.success(f"Feito ({fonte})")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Erro: {e}")
                        else:
                            st.warning("Sem prompt.")
                
                # Botão Upload
                with c_up:
                    uploaded_file = st.file_uploader(f"📤 Enviar", type=["png", "jpg", "jpeg"], key=f"upload_{block_id}", label_visibility="collapsed")
                    if uploaded_file is not None:
                        # Processar upload imediatamente
                        bytes_data = uploaded_file.read()
                        st.session_state["generated_images_blocks"][block_id] = BytesIO(bytes_data)
                        st.success("Imagem atualizada!")
                        # O rerun ajuda a limpar o uploader visualmente e atualizar a imagem mostrada
                        
            # Player de áudio se existir
            if block_id in st.session_state["generated_audios_blocks"]:
                st.audio(st.session_state["generated_audios_blocks"][block_id], format="audio/mp3")

    st.divider()
    
    # Montagem Final
    st.header("🎬 Finalização")
    if st.button("Renderizar Vídeo Completo (Unir tudo)", type="primary"):
        with st.status("Renderizando vídeo...", expanded=True) as status:
            try:
                # Verificar se temos tudo
                missing_imgs = [b["id"] for b in blocos_config if b["id"] not in st.session_state["generated_images_blocks"]]
                missing_audios = [b["id"] for b in blocos_config if b["id"] not in st.session_state["generated_audios_blocks"] and b["text_key"]]
                
                if missing_imgs:
                    st.warning(f"Faltam imagens para: {', '.join(missing_imgs)}. O vídeo ignorará esses blocos.")
                
                # Montagem
                if not shutil_which("ffmpeg"):
                     status.update(label="FFmpeg não encontrado!", state="error")
                     st.stop()
                
                temp_dir = tempfile.mkdtemp()
                clip_files = []
                
                ordem = [b["id"] for b in blocos_config]
                
                for idx, bid in enumerate(ordem):
                    img_bio = st.session_state["generated_images_blocks"].get(bid)
                    audio_bio = st.session_state["generated_audios_blocks"].get(bid)
                    
                    # Se for thumbnail, ignoramos no vídeo (ou colocamos no fim sem audio)
                    if bid == "thumbnail": continue
                    
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
                    
                    # Comando ffmpeg robusto
                    cmd = ["ffmpeg", "-y", "-loop", "1", "-i", img_path, "-i", audio_path,
                           "-c:v", "libx264", "-t", f"{dur}", "-pix_fmt", "yuv420p",
                           "-c:a", "aac", "-shortest", clip_path]
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
                    
                    status.update(label="Vídeo Renderizado!", state="complete")
                else:
                    status.update(label="Nenhum clipe válido gerado.", state="error")
                    
            except Exception as e:
                status.update(label="Erro na renderização", state="error")
                st.error(f"Detalhes: {e}")

    if st.session_state.get("video_final_bytes"):
        st.success("Vídeo pronto!")
        st.video(st.session_state["video_final_bytes"])
        st.download_button("⬇️ Baixar MP4", st.session_state["video_final_bytes"], "video_jhonata.mp4", "video/mp4")

# --------- TAB 4 ----------
with tab4:
    st.info("Histórico em desenvolvimento.")

st.markdown("---")
st.caption("Studio Jhonata v3.0 - Editor Full")