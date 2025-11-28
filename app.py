# app.py — Studio Jhonata (PRONTO, usando Gemini TTS voz pt-BR-Wavenet-B)
import os
import tempfile
from io import BytesIO
import base64
import requests
import time

import streamlit as st
from PIL import Image

# MoviePy (ver requirements)
from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips

# =========================
# Configuração Streamlit
# =========================
st.set_page_config(
    page_title="Studio Jhonata - Narração, Imagens e Vídeo",
    layout="centered",
)
st.title("🎬 Studio Jhonata — Narração + Imagens + Vídeo")
st.markdown("Gera **áudio (Gemini TTS)**, **imagens (Gemini)** e **vídeo** com MoviePy.")

# =========================
# Chave Gemini (via Secrets)
# =========================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or st.secrets.get("GEMINI_API_KEY", None)
if not GEMINI_API_KEY:
    st.warning("⚠️ GEMINI_API_KEY não encontrada nas secrets. Configure em Settings → Secrets.")

# =========================
# Funções (Gemini TTS / Imagem / Video)
# =========================

def gerar_audio_gemini(texto: str, voz: str = "pt-BR-Wavenet-B") -> BytesIO:
    """
    Gera áudio MP3 via endpoint generateContent do Generative Language (Gemini).
    Usa responseMimeType = "audio/mpeg".
    Retorna BytesIO com MP3.
    """
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY ausente.")
    if not texto or not texto.strip():
        raise ValueError("Texto vazio.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"

    # Prompt com instruções para TTS e seleção de voz (voz controlada no prompt)
    prompt_text = f"(tts|voice:{voz})\nNarrate the following text in Brazilian Portuguese:\n{texto}"

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

    r = requests.post(url, json=payload, timeout=120)
    r.raise_for_status()
    data = r.json()

    # Extrair base64 do retorno
    try:
        b64 = data["candidates"][0]["content"]["parts"][0]["inline_data"]["data"]
    except Exception as e:
        raise RuntimeError("Resposta inesperada do Gemini TTS: " + str(data)) from e

    audio_bytes = base64.b64decode(b64)
    bio = BytesIO(audio_bytes)
    bio.seek(0)
    return bio


def gerar_imagem_gemini(prompt: str, size: str = "1024x1024") -> BytesIO:
    """
    Gera imagem PNG via Gemini (generateContent).
    Retorna BytesIO com PNG.
    """
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY ausente.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"

    # Pedir explicitamente PNG
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": f"Generate a {size} cinematic liturgical image in the style of a tasteful religious illustration: {prompt}"}
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "image/png"
        }
    }

    r = requests.post(url, json=payload, timeout=120)
    r.raise_for_status()
    data = r.json()

    try:
        b64 = data["candidates"][0]["content"]["parts"][0]["inline_data"]["data"]
    except Exception as e:
        raise RuntimeError("Resposta inesperada do Gemini Image: " + str(data)) from e

    img_bytes = base64.b64decode(b64)
    bio = BytesIO(img_bytes)
    bio.seek(0)
    return bio


def montar_video(lista_imagens: list[BytesIO], audio_mp3: BytesIO, fps: int = 24) -> BytesIO:
    """
    Monta vídeo MP4 concatenando imagens (duração proporcional ao áudio).
    Retorna BytesIO com MP4.
    """
    if not lista_imagens or not audio_mp3:
        raise ValueError("Imagens e áudio são necessários.")

    temp_dir = tempfile.mkdtemp()
    audio_path = os.path.join(temp_dir, "audio.mp3")
    with open(audio_path, "wb") as f:
        audio_mp3.seek(0)
        f.write(audio_mp3.read())

    image_paths = []
    for i, b in enumerate(lista_imagens):
        img_path = os.path.join(temp_dir, f"img_{i}.png")
        b.seek(0)
        with open(img_path, "wb") as f:
            f.write(b.read())
        image_paths.append(img_path)

    audio_clip = AudioFileClip(audio_path)
    duracao = audio_clip.duration or max(1.0, len(image_paths))
    dur_por_img = duracao / len(image_paths)

    clips = []
    for p in image_paths:
        clip = ImageClip(p).set_duration(dur_por_img)
        clips.append(clip)

    final = concatenate_videoclips(clips, method="compose")
    final = final.set_audio(audio_clip)

    out_path = os.path.join(temp_dir, "final.mp4")
    final.write_videofile(out_path, fps=fps, codec="libx264", audio_codec="aac", verbose=False, logger=None)

    bio_out = BytesIO()
    with open(out_path, "rb") as f:
        bio_out.write(f.read())
    bio_out.seek(0)
    return bio_out

# =========================
# Session state inicial
# =========================
if "audio" not in st.session_state:
    st.session_state["audio"] = None
if "imgs" not in st.session_state:
    st.session_state["imgs"] = []
if "video" not in st.session_state:
    st.session_state["video"] = None

# =========================
# UI: Texto / Narração
# =========================
st.header("1 — Texto / Narração (Gemini TTS)")
texto = st.text_area("Cole o texto para narração:", height=200)

col1, col2 = st.columns(2)
with col1:
    gerar_audio_btn = st.button("🔊 Gerar narração (Gemini TTS)")
with col2:
    limpar_audio_btn = st.button("🧹 Limpar áudio")

if gerar_audio_btn:
    if not texto.strip():
        st.error("Digite o texto antes de gerar.")
    else:
        try:
            with st.spinner("Gerando áudio via Gemini TTS..."):
                # voz já escolhida: pt-BR-Wavenet-B
                st.session_state["audio"] = gerar_audio_gemini(texto, voz="pt-BR-Wavenet-B")
                st.success("Áudio gerado.")
        except Exception as e:
            st.error(f"Erro ao gerar áudio: {e}")

if limpar_audio_btn:
    st.session_state["audio"] = None
    st.success("Áudio limpo.")

if st.session_state["audio"]:
    try:
        st.audio(st.session_state["audio"], format="audio/mp3")
        try:
            st.session_state["audio"].seek(0)
        except Exception:
            pass
        st.download_button("⬇️ Baixar narração.mp3", st.session_state["audio"], file_name="narracao.mp3", mime="audio/mp3")
    except Exception as e:
        st.error(f"Erro no player de áudio: {e}")

st.markdown("---")

# =========================
# UI: Imagens
# =========================
st.header("2 — Gerar imagens (Gemini)")
prompt_img = st.text_input("Prompt para imagens:", value="Cena do Evangelho do dia, composição cinematográfica, tons cálidos, estilo litúrgico")
qtd = st.slider("Quantidade de imagens", 1, 8, 4)

col3, col4 = st.columns(2)
with col3:
    gerar_imgs_btn = st.button("🖼️ Gerar imagens")
with col4:
    limpar_imgs_btn = st.button("🧹 Limpar imagens")

if gerar_imgs_btn:
    if not prompt_img.strip():
        st.error("Insira um prompt válido.")
    else:
        try:
            st.session_state["imgs"] = []
            with st.spinner("Gerando imagens — isso pode demorar alguns segundos por imagem..."):
                for i in range(qtd):
                    img = gerar_imagem_gemini(prompt_img, size="1024x1024")
                    st.session_state["imgs"].append(img)
                st.success(f"{len(st.session_state['imgs'])} imagens geradas.")
        except Exception as e:
            st.error(f"Erro ao gerar imagens: {e}")

if limpar_imgs_btn:
    st.session_state["imgs"] = []
    st.success("Imagens limpas.")

if st.session_state["imgs"]:
    st.subheader("Imagens geradas")
    cols = st.columns(min(4, len(st.session_state["imgs"])))
    for i, im in enumerate(st.session_state["imgs"]):
        try:
            im.seek(0)
            cols[i % 4].image(im, caption=f"Imagem {i+1}")
        except Exception as e:
            st.write(f"Erro exibindo imagem {i+1}: {e}")

st.markdown("---")

# =========================
# UI: Montar vídeo
# =========================
st.header("3 — Montar vídeo final")
col5, col6 = st.columns(2)
with col5:
    montar_btn = st.button("🎬 Montar vídeo")
with col6:
    limpar_vid_btn = st.button("🧹 Limpar vídeo")

if montar_btn:
    if not st.session_state["audio"]:
        st.error("Gere a narração antes de montar o vídeo.")
    elif not st.session_state["imgs"]:
        st.error("Gere as imagens antes de montar o vídeo.")
    else:
        try:
            with st.spinner("Montando vídeo (MoviePy)..."):
                # garantir seek
                try:
                    st.session_state["audio"].seek(0)
                except Exception:
                    pass
                for b in st.session_state["imgs"]:
                    try:
                        b.seek(0)
                    except Exception:
                        pass
                st.session_state["video"] = montar_video(st.session_state["imgs"], st.session_state["audio"])
                st.success("Vídeo criado.")
        except Exception as e:
            st.error(f"Erro ao montar vídeo: {e}")

if limpar_vid_btn:
    st.session_state["video"] = None
    st.success("Vídeo limpo.")

if st.session_state["video"]:
    try:
        st.video(st.session_state["video"])
        try:
            st.session_state["video"].seek(0)
        except Exception:
            pass
        st.download_button("⬇️ Baixar vídeo_final.mp4", st.session_state["video"], file_name="video_final.mp4", mime="video/mp4")
    except Exception as e:
        st.error(f"Erro exibindo/baixando vídeo: {e}")

st.markdown("---")
st.caption("Observação: geração de imagens e TTS requer GEMINI_API_KEY nas secrets. Renderização do vídeo usa ffmpeg (packages.txt).")
