# app.py — Studio Jhonata (COMPLETO)
# Base original + Groq + gTTS + Gemini optional + ImageFX fallback (Pollinations) + montagem de vídeo com ffmpeg (sem moviepy)
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
from typing import List, Optional
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
# Groq - lazy init (preserved)
# =========================
_client = None


def inicializar_groq():
    global _client
    if _client is None:
        try:
            # Groq may not be installed; show helpful message
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
# Extrair referência bíblica (heurística)
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
# Análise de personagens via Groq (preservado)
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
# APIs Liturgia (preservadas)
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
# Roteiro + Prompts (preservado)
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
# NOVAS FUNÇÕES: ÁUDIO, IMAGENS, VÍDEO via ffmpeg
# =========================

# ---- gTTS (preservada) ----
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


# ---- Gemini TTS (opcional) ----
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


# ---- ImageFX (prioridade) com fallback para Pollinations.ai ----
def gerar_imagem_imagefx(prompt: str, size: str = "1024x1024") -> BytesIO:
    imagefx_url = st.secrets.get("IMAGEFX_API_URL") or os.getenv("IMAGEFX_API_URL")
    imagefx_key = st.secrets.get("IMAGEFX_API_KEY") or os.getenv("IMAGEFX_API_KEY")
    
    # Tentativa 1: ImageFX
    if imagefx_url and imagefx_key:
        try:
            headers = {"Authorization": f"Bearer {imagefx_key}"}
            payload = {"prompt": prompt, "size": size}
            r = requests.post(imagefx_url, json=payload, headers=headers, timeout=120)
            r.raise_for_status()
            data = r.json()
            b64 = None
            if isinstance(data, dict):
                if "image" in data and isinstance(data["image"], str):
                    b64 = data["image"]
                elif "images" in data and isinstance(data["images"], list) and data["images"]:
                    first = data["images"][0]
                    if isinstance(first, dict) and "b64" in first:
                        b64 = first["b64"]
                    elif isinstance(first, str):
                        b64 = first
            if not b64:
                raise RuntimeError(f"Resposta inesperada do ImageFX: {data}")
            img_bytes = base64.b64decode(b64)
            bio = BytesIO(img_bytes)
            bio.seek(0)
            return bio
        except Exception as e:
            st.warning(f"⚠️ ImageFX falhou, tentando fallback: {e}")
            # Se falhar, cai para o bloco else/fallback
    
    # Tentativa 2: Fallback (Pollinations.ai)
    # Gemini 1.5 Flash NÃO gera imagens (gera erro 400), então usamos Pollinations
    # que é gratuito, não precisa de chave e funciona bem para fallback.
    try:
        # Limpar o prompt e codificar para URL
        prompt_clean = prompt.replace("\n", " ").strip()
        prompt_encoded = urllib.parse.quote(prompt_clean)
        seed = random.randint(0, 999999)
        
        # Montar URL do Pollinations
        url = f"https://image.pollinations.ai/prompt/{prompt_encoded}?width=1024&height=1024&seed={seed}&nologo=true&model=flux"
        
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        
        bio = BytesIO(r.content)
        bio.seek(0)
        return bio
    except Exception as e:
        raise RuntimeError(f"Erro no fallback de imagem (Pollinations): {e}")


# ---- gerar imagens para roteiro (mapping) ----
def gerar_imagens_para_roteiro(roteiro: dict, size: str = "1024x1024") -> dict:
    imagens = {}
    mapping = {
        "prompt_hook": "hook",
        "prompt_reflexão": "reflexão",
        "prompt_aplicacao": "aplicação",
        "prompt_oração": "oração",
        "prompt_leitura": "leitura",
        "prompt_geral": "thumbnail",
    }
    for chave_prompt, bloco in mapping.items():
        # try variants (keeping compatibility with naming differences)
        prompt_text = roteiro.get(chave_prompt) or roteiro.get(chave_prompt.lower()) or roteiro.get(chave_prompt.replace("ç", "c")) or ""
        if prompt_text:
            img = gerar_imagem_imagefx(prompt_text, size=size)
            imagens[bloco] = img
    return imagens


# ---- gerar narrações para roteiro (gTTS / Gemini) ----
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


# ---- montar vídeo com ffmpeg (sem moviepy) ----
def montar_video_por_roteiro_ffmpeg(imagens_map: dict, audios_map: dict, musica_fundo: Optional[BytesIO] = None) -> BytesIO:
    """
    Cria pequenos clipes mp4 por bloco (imagem+áudio) usando ffmpeg e depois concatena.
    Retorna BytesIO com MP4 final.
    """
    # checagens
    if not shutil_which("ffmpeg"):
        raise RuntimeError("ffmpeg não encontrado no ambiente. Verifique packages.txt")

    ordem = ["hook", "reflexão", "leitura", "aplicação", "oração", "thumbnail"]
    temp_dir = tempfile.mkdtemp()
    clip_files = []

    try:
        for bloco in ordem:
            img_bio = imagens_map.get(bloco)
            audio_bio = audios_map.get(bloco)
            if not img_bio or not audio_bio:
                continue

            img_path = os.path.join(temp_dir, f"{bloco}.png")
            audio_path = os.path.join(temp_dir, f"{bloco}.mp3")
            clip_path = os.path.join(temp_dir, f"{bloco}.mp4")

            # salvar arquivos
            img_bio.seek(0)
            with open(img_path, "wb") as f:
                f.write(img_bio.read())

            audio_bio.seek(0)
            with open(audio_path, "wb") as f:
                f.write(audio_bio.read())

            # obter duração do áudio via ffprobe
            dur = get_audio_duration_seconds(audio_path)
            if dur is None:
                dur = 5.0

            # criar vídeo a partir da imagem + áudio (loop imagem por dur)
            # -loop 1 -t {dur} -i img -i audio -c:v libx264 -c:a aac -pix_fmt yuv420p -vf scale=1280:-2 {clip}
            cmd = [
                "ffmpeg",
                "-y",
                "-loop",
                "1",
                "-i",
                img_path,
                "-i",
                audio_path,
                "-c:v",
                "libx264",
                "-t",
                f"{dur}",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-shortest",
                clip_path,
            ]
            run_cmd(cmd)
            clip_files.append(clip_path)

        if not clip_files:
            raise RuntimeError("Nenhum clip gerado — verifique imagens e áudios.")

        # criar arquivo de concat
        concat_list_path = os.path.join(temp_dir, "concat_list.txt")
        with open(concat_list_path, "w", encoding="utf-8") as f:
            for p in clip_files:
                f.write(f"file '{p}'\n")

        final_path = os.path.join(temp_dir, "final_video.mp4")
        cmd_concat = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            concat_list_path,
            "-c",
            "copy",
            final_path,
        ]
        run_cmd(cmd_concat)

        # opcional: mixar música de fundo (complexo). Se fornecida, pede processamento extra — omitido por simplicidade

        with open(final_path, "rb") as f:
            data = f.read()
        out = BytesIO(data)
        out.seek(0)
        return out
    finally:
        # not deleting temp_dir to aid debugging; could remove in production
        pass


# -------------------------
# Helpers: comando e utilitários
# -------------------------
import os as _os
import shutil as _shutil


def shutil_which(bin_name: str) -> Optional[str]:
    return _shutil.which(bin_name)


def run_cmd(cmd: List[str]):
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""
        stdout = e.stdout.decode("utf-8", errors="replace") if e.stdout else ""
        raise RuntimeError(f"Comando falhou: {' '.join(cmd)}\nSTDOUT: {stdout}\nSTDERR: {stderr}")


def get_audio_duration_seconds(path: str) -> Optional[float]:
    # usa ffprobe para obter duração
    if not shutil_which("ffprobe"):
        # tentar ffmpeg -i parse (menos confiável) -> retorna None
        return None
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path]
    try:
        p = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out = p.stdout.decode().strip()
        return float(out) if out else None
    except Exception:
        return None


# =========================
# Interface principal (preservada + integrações)
# =========================
st.title("✨ Studio Jhonata - Automação Litúrgica")
st.markdown("---")

st.sidebar.title("⚙️ Configurações")
st.sidebar.info("1️⃣ api-liturgia-diaria\n2️⃣ liturgia.railway\n3️⃣ Groq fallback")
st.sidebar.success("✅ Groq ativo (se configurado)")

if "personagens_biblicos" not in st.session_state:
    st.session_state.personagens_biblicos = inicializar_personagens()

# session state adicionais
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
    ["📖 Gerar Roteiro", "🎨 Personagens", "🎥 Fábrica Vídeo", "📊 Histórico"]
)

# --------- TAB 1: ROTEIRO ----------
with tab1:
    st.header("🚀 Gerador de Roteiro + Imagens + Áudio")
    col1, col2 = st.columns([2, 1])
    with col1:
        data_selecionada = st.date_input(
            "📅 Data da liturgia:", value=date.today(), min_value=date(2023, 1, 1)
        )
    with col2:
        st.info("Status: ✅ pronto para gerar")

    if st.button("🚀 Gerar Roteiro Completo", type="primary"):
        data_str = data_selecionada.strftime("%Y-%m-%d")
        with st.spinner("🔍 Buscando Evangelho..."):
            liturgia = obter_evangelho_com_fallback(data_str)
        if not liturgia:
            st.stop()

        st.success(
            f"✅ Evangelho: {liturgia['referencia_liturgica']} ({liturgia['fonte']})"
        )

        with st.spinner("🤖 Analisando personagens..."):
            personagens_detectados = analisar_personagens_groq(
                liturgia["texto"], st.session_state.personagens_biblicos
            )

        with st.spinner("✨ Gerando roteiro e prompts visuais..."):
            roteiro = gerar_roteiro_com_prompts_groq(
                liturgia["texto"],
                liturgia["referencia_liturgica"],
                {**st.session_state.personagens_biblicos, **personagens_detectados},
            )

        if not roteiro:
            st.stop()

        leitura_montada = montar_leitura_com_formula(
            liturgia["texto"], liturgia.get("ref_biblica")
        )
        ref_curta = formatar_referencia_curta(liturgia.get("ref_biblica"))

        st.session_state["roteiro_gerado"] = roteiro
        st.session_state["leitura_montada"] = leitura_montada

        st.markdown("## 📖 Roteiro pronto para gravar")
        if ref_curta:
            st.markdown(f"**Leitura:** {ref_curta}")
        st.markdown("---")

        if personagens_detectados:
            st.markdown("### 👥 Personagens nesta leitura")
            for nome, desc in personagens_detectados.items():
                st.markdown(f"**{nome}:** {desc}")
            st.markdown("---")

        col_esq, col_dir = st.columns(2)

        with col_esq:
            st.markdown("### 🎣 HOOK")
            st.markdown(roteiro.get("hook", ""))
            st.markdown("**📸 Prompt:**")
            st.code(roteiro.get("prompt_hook", ""))

            st.markdown("### 💭 REFLEXÃO")
            st.markdown(roteiro.get("reflexão", ""))
            st.markdown("**📸 Prompt:**")
            st.code(roteiro.get("prompt_reflexão", ""))

        with col_dir:
            st.markdown("### 📖 LEITURA")
            st.markdown(leitura_montada)
            st.markdown("**📸 Prompt:**")
            st.code(roteiro.get("prompt_leitura", ""))

            st.markdown("### 🌟 APLICAÇÃO")
            st.markdown(roteiro.get("aplicação", ""))
            st.markdown("**📸 Prompt:**")
            st.code(roteiro.get("prompt_aplicacao", ""))

        st.markdown("### 🙏 ORAÇÃO")
        st.markdown(roteiro.get("oração", ""))
        st.markdown("**📸 Prompt:**")
        st.code(roteiro.get("prompt_oração", ""))

        st.markdown("### 🖼️ THUMBNAIL")
        st.code(roteiro.get("prompt_geral", ""))
        st.markdown("---")

    # ações automáticas
    if st.session_state.get("roteiro_gerado"):
        st.markdown("### Próximos passos automáticos")
        colA, colB, colC = st.columns(3)
        with colA:
            if st.button("🔊 Gerar narração para o roteiro (gTTS)"):
                try:
                    roteiro = st.session_state["roteiro_gerado"]
                    roteiro["leitura"] = st.session_state.get("leitura_montada", "")
                    audios = gerar_narracoes_para_roteiro(roteiro, usar_gemini=False)
                    st.session_state["generated_audios_blocks"] = audios
                    st.success("Áudios gerados (gTTS).")
                except Exception as e:
                    st.error(f"Erro gerando narrações: {e}")
                    st.error(traceback.format_exc())
        with colB:
            if st.button("🖼️ Gerar imagens para os prompts (ImageFX/Fallback)"):
                try:
                    roteiro = st.session_state["roteiro_gerado"]
                    imagens = gerar_imagens_para_roteiro(roteiro, size="1024x1024")
                    st.session_state["generated_images_blocks"] = imagens
                    st.success("Imagens geradas.")
                except Exception as e:
                    st.error(f"Erro gerando imagens: {e}")
                    st.error(traceback.format_exc())
        with colC:
            if st.button("🎬 Montar vídeo final (com as imagens e áudios gerados)"):
                try:
                    imgs = st.session_state.get("generated_images_blocks", {})
                    audios = st.session_state.get("generated_audios_blocks", {})
                    video_bio = montar_video_por_roteiro_ffmpeg(imgs, audios)
                    st.session_state["video_final_bytes"] = video_bio
                    st.success("Vídeo criado.")
                except Exception as e:
                    st.error(f"Erro montando vídeo: {e}")
                    st.error(traceback.format_exc())

    # previews
    if st.session_state.get("generated_audios_blocks"):
        st.markdown("**Pré-visualizar áudios gerados:**")
        for k, b in st.session_state["generated_audios_blocks"].items():
            try:
                st.markdown(f"- {k}")
                st.audio(b, format="audio/mp3")
            except Exception:
                pass

    if st.session_state.get("generated_images_blocks"):
        st.markdown("**Pré-visualizar imagens geradas:**")
        cols = st.columns(min(4, len(st.session_state["generated_images_blocks"])))
        for i, (k, bio) in enumerate(st.session_state["generated_images_blocks"].items()):
            try:
                bio.seek(0)
                cols[i % len(cols)].image(bio, caption=k)
            except Exception:
                pass

    if st.session_state.get("video_final_bytes"):
        st.markdown("**Vídeo final pronto:**")
        try:
            st.video(st.session_state["video_final_bytes"])
            st.download_button("⬇️ Baixar vídeo final", st.session_state["video_final_bytes"], file_name="video_final.mp4", mime="video/mp4")
        except Exception:
            pass

# --------- TAB 2: PERSONAGENS ----------
with tab2:
    st.header("🎨 Banco de Personagens Bíblicos")

    banco = st.session_state.personagens_biblicos.copy()

    col1, col2 = st.columns([1, 1])

    with col1:
        st.markdown("### 📋 Todos os personagens")
        for i, (nome, desc) in enumerate(banco.items()):
            with st.expander(f"✏️ {nome}"):
                novo_nome = st.text_input(f"Nome {i}", value=nome, key=f"nome_{i}")
                nova_desc = st.text_area(
                    f"Descrição {i}", value=desc, height=100, key=f"desc_{i}"
                )
                col_a, col_b = st.columns(2)
                with col_a:
                    if st.button("💾 Salvar", key=f"salvar_{i}"):
                        if novo_nome and nova_desc:
                            if (
                                novo_nome != nome
                                and novo_nome
                                in st.session_state.personagens_biblicos
                            ):
                                del st.session_state.personagens_biblicos[novo_nome]
                            del st.session_state.personagens_biblicos[nome]
                            st.session_state.personagens_biblicos[novo_nome] = nova_desc
                            st.rerun()
                with col_b:
                    if st.button("🗑️ Apagar", key=f"apagar_{i}"):
                        del st.session_state.personagens_biblicos[nome]
                        st.rerun()

    with col2:
        st.markdown("### ➕ Novo Personagem")
        novo_nome = st.text_input("Nome do personagem", key="novo_nome")
        nova_desc = st.text_area(
            "Descrição detalhada (aparência, roupas, idade, estilo)",
            height=120,
            key="nova_desc",
        )
        if st.button("➕ Adicionar") and novo_nome and nova_desc:
            st.session_state.personagens_biblicos[novo_nome] = nova_desc
            st.rerun()

# --------- TAB 3: FÁBRICA DE VÍDEO ----------
with tab3:
    st.header("🎥 Fábrica de Vídeo")
    st.info("Use esta aba para gerar narrações, imagens e montar vídeos a partir de roteiros já gerados.")
    st.markdown("### Ferramentas manuais")
    col_a, col_b, col_c = st.columns(3)

    with col_a:
        if st.button("Gerar Áudios (gTTS) para o roteiro atual"):
            if not st.session_state.get("roteiro_gerado"):
                st.error("Gere o roteiro primeiro na aba 'Gerar Roteiro'.")
            else:
                try:
                    roteiro = st.session_state["roteiro_gerado"]
                    roteiro["leitura"] = st.session_state.get("leitura_montada", "")
                    audios = gerar_narracoes_para_roteiro(roteiro, usar_gemini=False)
                    st.session_state["generated_audios_blocks"] = audios
                    st.success("Áudios gerados com gTTS.")
                except Exception as e:
                    st.error(f"Erro ao gerar áudios: {e}")
                    st.error(traceback.format_exc())

    with col_b:
        if st.button("Gerar Imagens (ImageFX / Fallback) para o roteiro atual"):
            if not st.session_state.get("roteiro_gerado"):
                st.error("Gere o roteiro primeiro na aba 'Gerar Roteiro'.")
            else:
                try:
                    roteiro = st.session_state["roteiro_gerado"]
                    imagens = gerar_imagens_para_roteiro(roteiro, size="1024x1024")
                    st.session_state["generated_images_blocks"] = imagens
                    st.success("Imagens geradas.")
                except Exception as e:
                    st.error(f"Erro ao gerar imagens: {e}")
                    st.error(traceback.format_exc())

    with col_c:
        if st.button("Montar Vídeo Final (usando imagens + áudios selecionados)"):
            try:
                imgs = st.session_state.get("generated_images_blocks", {})
                audios = st.session_state.get("generated_audios_blocks", {})
                if not imgs or not audios:
                    st.error("Gere imagens e áudios antes de montar o vídeo.")
                else:
                    video_bio = montar_video_por_roteiro_ffmpeg(imgs, audios)
                    st.session_state["video_final_bytes"] = video_bio
                    st.success("Vídeo gerado com sucesso.")
            except Exception as e:
                st.error(f"Erro ao montar vídeo: {e}")
                st.error(traceback.format_exc())

    st.markdown("---")
    st.subheader("Pré-visualizações")
    if st.session_state.get("generated_images_blocks"):
        cols = st.columns(min(4, len(st.session_state["generated_images_blocks"])))
        for i, (k, bio) in enumerate(st.session_state["generated_images_blocks"].items()):
            try:
                bio.seek(0)
                cols[i % len(cols)].image(bio, caption=k)
            except Exception:
                pass

    if st.session_state.get("generated_audios_blocks"):
        st.subheader("Áudios gerados")
        for k, b in st.session_state["generated_audios_blocks"].items():
            try:
                st.markdown(f"- {k}")
                st.audio(b, format="audio/mp3")
            except Exception:
                pass

    if st.session_state.get("video_final_bytes"):
        st.subheader("Vídeo Final")
        try:
            st.video(st.session_state["video_final_bytes"])
            st.download_button("⬇️ Baixar vídeo_final.mp4", st.session_state["video_final_bytes"], file_name="video_final.mp4", mime="video/mp4")
        except Exception:
            pass

# --------- TAB 4: HISTÓRICO ----------
with tab4:
    st.header("📊 Histórico")
    st.info("Em breve.")

st.markdown("---")
st.markdown("Feito com ❤️ para evangelização - Studio Jhonata")