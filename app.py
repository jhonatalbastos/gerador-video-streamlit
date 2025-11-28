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
    st.session_state["video"] =_
