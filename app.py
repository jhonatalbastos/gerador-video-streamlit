# app.py — Studio Jhonata (VERSÃO COMPLETA E ATUALIZADA)
import os
import tempfile
from io import BytesIO
import base64
import requests

from gtts import gTTS
from PIL import Image

import streamlit as st

# MoviePy (certifique-se que está no requirements.txt)
from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips

# =====================================================
# CONFIGURAÇÃO STREAMLIT
# =====================================================
st.set_page_config(
    page_title="Studio Jhonata - Narração, Imagens e Vídeo",
    layout="centered",
)
st.title("🎬 Studio Jhonata — Narração + Imagens + Vídeo Automático")
st.markdown("Gera **áudio**, **imagens** e **vídeo completo** usando gTTS + Gemini + MoviePy.")

# =====================================================
# API KEY
# =====================================================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or st.secrets.get("GEMINI_API_KEY", None)

if not GEMINI_API_KEY:
    st.warning("⚠️ Nenhuma GEMINI_API_KEY configurada no ambiente.")


# =====================================================
# FUNÇÃO DE NARRAÇÃO (gTTS)
# =====================================================
def gerar_audio_gtts(texto: str) -> BytesIO | None:
    if not texto.strip():
        return None
    mp3_fp = BytesIO()
    tts = gTTS(text=texto, lang="pt", slow=False)
    tts.write_to_fp(mp3_fp)
    mp3_fp.seek(0)
    return mp3_fp


# =====================================================
# FUNÇÃO DE GERAR IMAGEM (GEMINI)
# =====================================================
def gerar_imagem_gemini(prompt: str, size="1024x1024") -> BytesIO:
    """
    Usa o endpoint atualizado de geração de imagem do Gemini.
    Obs: estrutura do retorno 2025 → { "candidates": [ { "content": { "parts": [ { "inline_data": { "mime_type": "...", "data": base64 } } ] } } ] }
    """
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY ausente.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": f"Generate a {size} cinematic liturgical image: {prompt}"}
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "image/png"
        }
    }

    r = requests.post(url, json=payload, timeout=60)
    r.raise_for_status()
    data = r.json()

    try:
        b64 = data["candidates"][0]["content"]["parts"][0]["inline_data"]["data"]
    except:
        raise RuntimeError("A API não retornou imagem válida. Conteúdo: " + str(data))

    img_bytes = base64.b64decode(b64)
    bio = BytesIO(img_bytes)
    bio.seek(0)
    return bio


# =====================================================
# FUNÇÃO DE MONTAR VÍDEO
# =====================================================
def montar_video(lista_imagens: list[BytesIO], audio_mp3: BytesIO) -> BytesIO:
    if not lista_imagens or not audio_mp3:
        raise ValueError("Imagens e áudio são obrigatórios.")

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

    audio_clip = AudioFileClip(audio_path)
    dur_audio = audio_clip.duration

    dur_por_img = dur_audio / len(image_paths)

    clips = []
    for p in image_paths:
        clip = ImageClip(p).set_duration(dur_por_img)
        clips.append(clip)

    final_clip = concatenate_videoclips(clips, method="compose")
    final_clip = final_clip.set_audio(audio_clip)

    output_path = os.path.join(temp_dir, "final.mp4")

    final_clip.write_videofile(
        output_path,
        fps=24,
        codec="libx264",
        audio_codec="aac",
        verbose=False,
        logger=None
    )

    # Retornar BytesIO
    bio_out = BytesIO()
    with open(output_path, "rb") as f:
        bio_out.write(f.read())
    bio_out.seek(0)

    return bio_out


# =====================================================
# SESSION STATE
# =====================================================
if "audio" not in st.session_state:
    st.session_state["audio"] = None

if "imgs" not in st.session_state:
    st.session_state["imgs"] = []

if "video" not in st.session_state:
    st.session_state["video"] = None


# =====================================================
# UI — TEXT AREA
# =====================================================
st.header("1️⃣ Texto para narração")
texto = st.text_area("Cole aqui o texto", height=180)

if st.button("🎧 Gerar Narração"):
    if not texto.strip():
        st.error("Digite algum texto.")
    else:
        with st.spinner("Gerando áudio..."):
            st.session_state["audio"] = gerar_audio_gtts(texto)
            st.success("Áudio gerado!")

if st.session_state["audio"]:
    st.audio(st.session_state["audio"], format="audio/mp3")


# =====================================================
# UI — IMAGENS
# =====================================================
st.header("2️⃣ Gerar Imagens (Gemini)")
prompt_img = st.text_input("Prompt das imagens:", value="Cena cinematográfica do Evangelho do dia")
qtd = st.slider("Quantidade", 1, 8, 4)

if st.button("🎨 Gerar Imagens"):
    st.session_state["imgs"] = []
    if not prompt_img.strip():
        st.error("Insira um prompt válido.")
    else:
        with st.spinner("Gerando imagens..."):
            for i in range(qtd):
                try:
                    img = gerar_imagem_gemini(prompt_img)
                    st.session_state["imgs"].append(img)
                except Exception as e:
                    st.error(f"Erro na imagem {i+1}: {e}")
                    break
        st.success(f"{len(st.session_state['imgs'])} imagens geradas.")

# Mostrar
if st.session_state["imgs"]:
    st.subheader("Imagens geradas")
    cols = st.columns(4)
    for i, im in enumerate(st.session_state["imgs"]):
        cols[i % 4].image(im, caption=f"Imagem {i+1}")


# =====================================================
# UI — VÍDEO
# =====================================================
st.header("3️⃣ Montar Vídeo Final")

if st.button("🎬 Montar Vídeo"):
    if not st.session_state["audio"]:
        st.error("Gere o áudio primeiro.")
    elif not st.session_state["imgs"]:
        st.error("Gere as imagens primeiro.")
    else:
        with st.spinner("Renderizando vídeo..."):
            st.session_state["video"] = montar_video(
                st.session_state["imgs"], st.session_state["audio"]
            )
            st.success("Vídeo criado!")

if st.session_state["video"]:
    st.video(st.session_state["video"])
    st.download_button(
        "⬇️ Baixar vídeo_final.mp4",
        data=st.session_state["video"],
        file_name="video_final.mp4",
        mime="video/mp4"
    )


st.markdown("---")
st.caption("Studio Jhonata — Sistema completo de roteiro → narração → imagens → vídeo.")
