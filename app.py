# app.py — Studio Jhonata (ARQUIVO COMPLETO, UNIFICADO)
# Integra: roteiro -> Gemini TTS (pt-BR-Wavenet-B) -> Gemini images -> MoviePy video
import os
import tempfile
from io import BytesIO
import base64
import requests
import time
import traceback

from typing import List

import streamlit as st
from PIL import Image
from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips

# ------------------------
# Configuração da página
# ------------------------
st.set_page_config(page_title="Studio Jhonata - Roteiro → Áudio → Imagens → Vídeo", layout="centered")
st.title("🎬 Studio Jhonata — Roteiro • Narração • Imagens • Vídeo")
st.markdown("Gerador automático: **Gemini TTS** (pt-BR-Wavenet-B) + **Gemini imagens** + **MoviePy**")

# ------------------------
# Chave Gemini (Secrets)
# ------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or st.secrets.get("GEMINI_API_KEY", None)
if not GEMINI_API_KEY:
    st.warning("⚠️ GEMINI_API_KEY não encontrada. Vá em Settings → Secrets e adicione GEMINI_API_KEY.")

# ------------------------
# Helpers / Utilitários
# ------------------------
def post_json_with_retries(url: str, payload: dict, timeout: int = 120, retries: int = 2, backoff: float = 1.0):
    """POST JSON com re-tentativas básicas."""
    last_exc = None
    for attempt in range(retries + 1):
        try:
            r = requests.post(url, json=payload, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_exc = e
            if attempt < retries:
                time.sleep(backoff * (attempt + 1))
            else:
                raise last_exc

# ------------------------
# Gemini TTS (generateContent)
# ------------------------
def gerar_audio_gemini(texto: str, voz: str = "pt-BR-Wavenet-B") -> BytesIO:
    """
    Gera áudio MP3 via Gemini generateContent.
    Retorna BytesIO com audio/mpeg.
    """
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY ausente.")
    if not texto or not texto.strip():
        raise ValueError("Texto vazio.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"

    # Construção do prompt: marcamos instrução de TTS com voz
    prompt_text = f"(tts|voice:{voz})\nPor favor, narre o texto abaixo em português do Brasil com entonação natural:\n{texto}"

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt_text}
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "audio/mpeg"
        }
    }

    data = post_json_with_retries(url, payload, timeout=120, retries=2, backoff=1.5)

    # Extrair base64 do retorno (estrutura esperada 2025)
    try:
        b64 = data["candidates"][0]["content"]["parts"][0]["inline_data"]["data"]
    except Exception as e:
        raise RuntimeError(f"Resposta inesperada do Gemini TTS: {data}") from e

    audio_bytes = base64.b64decode(b64)
    bio = BytesIO(audio_bytes)
    bio.seek(0)
    return bio

# ------------------------
# Gemini Imagens (generateContent → image/png)
# ------------------------
def gerar_imagem_gemini(prompt: str, size: str = "1024x1024") -> BytesIO:
    """
    Gera imagem PNG via Gemini generateContent.
    Retorna BytesIO com PNG.
    """
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY ausente.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    # Pedir explícito PNG e estilo litúrgico/ cinematográfico
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": f"Create a {size} cinematic liturgical illustration with tasteful composition and soft lighting: {prompt}"}
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "image/png"
        }
    }

    data = post_json_with_retries(url, payload, timeout=120, retries=2, backoff=1.2)

    try:
        b64 = data["candidates"][0]["content"]["parts"][0]["inline_data"]["data"]
    except Exception as e:
        raise RuntimeError(f"Resposta inesperada do Gemini Image: {data}") from e

    img_bytes = base64.b64decode(b64)
    bio = BytesIO(img_bytes)
    bio.seek(0)
    return bio

# ------------------------
# Montar vídeo com MoviePy
# ------------------------
def montar_video(lista_imagens: List[BytesIO], audio_mp3: BytesIO, fps: int = 24) -> BytesIO:
    """
    Monta MP4 concatenando imagens (cada imagem dura duração proporcional do áudio).
    Retorna BytesIO do mp4.
    """
    if not lista_imagens or not audio_mp3:
        raise ValueError("Imagens e áudio são necessários.")

    temp_dir = tempfile.mkdtemp()

    # Salvar áudio
    audio_path = os.path.join(temp_dir, "audio.mp3")
    audio_mp3.seek(0)
    with open(audio_path, "wb") as f:
        f.write(audio_mp3.read())

    # Salvar imagens
    image_paths = []
    for i, bio in enumerate(lista_imagens):
        img_path = os.path.join(temp_dir, f"img_{i}.png")
        bio.seek(0)
        with open(img_path, "wb") as f:
            f.write(bio.read())
        image_paths.append(img_path)

    # Criar clipes
    audio_clip = AudioFileClip(audio_path)
    duracao = audio_clip.duration or max(1.0, len(image_paths))
    dur_por_img = duracao / len(image_paths)

    clips = [ImageClip(p).set_duration(dur_por_img) for p in image_paths]

    video = concatenate_videoclips(clips, method="compose")
    video = video.set_audio(audio_clip)

    out_path = os.path.join(temp_dir, "final.mp4")
    # escrever arquivo (MoviePy usa ffmpeg do sistema — packages.txt deve conter ffmpeg)
    video.write_videofile(out_path, fps=fps, codec="libx264", audio_codec="aac", verbose=False, logger=None)

    out_bio = BytesIO()
    with open(out_path, "rb") as f:
        out_bio.write(f.read())
    out_bio.seek(0)
    return out_bio

# ------------------------
# Session state init
# ------------------------
if "audio_gemini" not in st.session_state:
    st.session_state["audio_gemini"] = None
if "imgs_gemini" not in st.session_state:
    st.session_state["imgs_gemini"] = []
if "video_gemini" not in st.session_state:
    st.session_state["video_gemini"] = None

# ------------------------
# UI: Roteiro (seu bloco de geração de roteiro)
# ------------------------
st.header("✍️ 1. Roteiro / Texto (cole ou gere seu roteiro aqui)")
roteiro_text = st.text_area("Roteiro / leitura / reflexão / oração:", height=200, help="Cole o texto do evangelho, reflexão ou roteiro que deseja narrar.")

col_r1, col_r2 = st.columns([1, 1])
with col_r1:
    # botão para gerar narração via Gemini TTS
    gerar_narração = st.button("🔊 Gerar narração (Gemini TTS)")
with col_r2:
    limpar_narração = st.button("🧹 Limpar narração")

# ------------------------
# Ações: gerar / limpar narração
# ------------------------
if gerar_narração:
    if not roteiro_text or not roteiro_text.strip():
        st.error("Insira o texto do roteiro antes de gerar a narração.")
    elif not GEMINI_API_KEY:
        st.error("GEMINI_API_KEY não configurada. Configure nas Secrets do Streamlit Cloud.")
    else:
        try:
            with st.spinner("Gerando narração via Gemini TTS..."):
                st.session_state["audio_gemini"] = gerar_audio_gemini(roteiro_text, voz="pt-BR-Wavenet-B")
                st.success("Áudio gerado com sucesso.")
        except Exception as e:
            st.error(f"Erro ao gerar áudio: {e}")
            st.error(traceback.format_exc())

if limpar_narração:
    st.session_state["audio_gemini"] = None
    st.success("Narração limpa.")

# Player e download do áudio
st.markdown("---")
st.subheader("🔊 Player / Download (Áudio)")
if st.session_state["audio_gemini"]:
    try:
        st.audio(st.session_state["audio_gemini"], format="audio/mp3")
        try:
            st.session_state["audio_gemini"].seek(0)
        except Exception:
            pass
        st.download_button("⬇️ Baixar narração (mp3)", st.session_state["audio_gemini"], file_name="narracao_gemini.mp3", mime="audio/mp3")
    except Exception as e:
        st.error(f"Erro exibindo áudio: {e}")
else:
    st.info("Nenhum áudio gerado. Gere a narração para ver o player.")

# ------------------------
# UI: Geração de Imagens
# ------------------------
st.markdown("---")
st.header("🖼️ 2. Gerar imagens (Gemini)")
prompt_img = st.text_input("Prompt para imagens (ex.: 'Cena do Evangelho com luz dourada, estilo pintura sacra')", value="Cena do Evangelho do dia, composição cinematográfica, tons quentes, estilo litúrgico")
qtd = st.slider("Quantidade de imagens", 1, 6, 3)
size = st.selectbox("Tamanho da imagem", ["512x512", "768x768", "1024x1024"], index=2)

col_i1, col_i2 = st.columns([1, 1])
with col_i1:
    gerar_imgs_btn = st.button("🖼️ Gerar imagens")
with col_i2:
    limpar_imgs_btn = st.button("🧹 Limpar imagens")

if gerar_imgs_btn:
    if not prompt_img or not prompt_img.strip():
        st.error("Insira um prompt válido.")
    elif not GEMINI_API_KEY:
        st.error("GEMINI_API_KEY ausente nas Secrets.")
    else:
        st.session_state["imgs_gemini"] = []
        erro_ocorreu = False
        with st.spinner("Gerando imagens (cada imagem pode levar alguns segundos)..."):
            for i in range(qtd):
                try:
                    img = gerar_imagem_gemini(prompt_img, size=size)
                    st.session_state["imgs_gemini"].append(img)
                except Exception as e:
                    st.error(f"Erro ao gerar imagem {i+1}: {e}")
                    erro_ocorreu = True
                    break
        if not erro_ocorreu:
            st.success(f"{len(st.session_state['imgs_gemini'])} imagens geradas.")

if limpar_imgs_btn:
    st.session_state["imgs_gemini"] = []
    st.success("Imagens limpas.")

# Mostrar imagens geradas
if st.session_state["imgs_gemini"]:
    st.markdown("**Imagens geradas:**")
    cols = st.columns(min(4, len(st.session_state["imgs_gemini"])))
    for i, im in enumerate(st.session_state["imgs_gemini"]):
        try:
            im.seek(0)
            cols[i % len(cols)].image(im, caption=f"Imagem {i+1}", use_column_width=True)
        except Exception as e:
            st.write(f"Erro mostrando imagem {i+1}: {e}")

# ------------------------
# UI: Montar Vídeo
# ------------------------
st.markdown("---")
st.header("🎬 3. Montar vídeo com áudio e imagens")
col_v1, col_v2 = st.columns([1, 1])
with col_v1:
    montar_btn = st.button("🎬 Montar vídeo")
with col_v2:
    limpar_vid_btn = st.button("🧹 Limpar vídeo")

if montar_btn:
    if not st.session_state["audio_gemini"]:
        st.error("Gere a narração antes de montar o vídeo.")
    elif not st.session_state["imgs_gemini"]:
        st.error("Gere imagens antes de montar o vídeo.")
    else:
        try:
            with st.spinner("Renderizando vídeo (MoviePy + ffmpeg)... Isso pode demorar alguns segundos"):
                # garantir pointers
                try:
                    st.session_state["audio_gemini"].seek(0)
                except Exception:
                    pass
                for b in st.session_state["imgs_gemini"]:
                    try:
                        b.seek(0)
                    except Exception:
                        pass
                st.session_state["video_gemini"] = montar_video(st.session_state["imgs_gemini"], st.session_state["audio_gemini"])
                st.success("Vídeo montado com sucesso.")
        except Exception as e:
            st.error(f"Erro ao montar vídeo: {e}")
            st.error(traceback.format_exc())

if limpar_vid_btn:
    st.session_state["video_gemini"] = None
    st.success("Vídeo limpo.")

# Mostrar vídeo e botão de download
if st.session_state["video_gemini"]:
    try:
        st.video(st.session_state["video_gemini"])
        try:
            st.session_state["video_gemini"].seek(0)
        except Exception:
            pass
        st.download_button("⬇️ Baixar vídeo_final.mp4", st.session_state["video_gemini"], file_name="video_final.mp4", mime="video/mp4")
    except Exception as e:
        st.error(f"Erro exibindo/baixando vídeo: {e}")

# ------------------------
# Informações finais / dicas
# ------------------------
st.markdown("---")
st.caption(
    "Dicas:\n"
    "- Certifique-se de adicionar GEMINI_API_KEY nas Secrets do Streamlit Cloud.\n"
    "- Se o app der erro por timeout ao gerar várias imagens, reduza a quantidade para 1–2 imagens para teste.\n"
    "- Garanta `packages.txt` com `ffmpeg` e `requirements.txt` atualizado no repositório.\n"
    "- Logs do Streamlit (Manage app → Logs) mostram erros de execução/requests."
)