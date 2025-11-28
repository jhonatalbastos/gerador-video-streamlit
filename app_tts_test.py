import streamlit as st
from io import BytesIO
import google.genai as genai
from google.genai import types

# =========================
# Config da página
# =========================
st.set_page_config(page_title="Gemini TTS Teste", layout="centered")
st.title("Gemini TTS Teste")

# =========================
# Cliente Gemini
# =========================
if "GOOGLE_AI_API_KEY" not in st.secrets:
    st.error("Configure GOOGLE_AI_API_KEY em Settings → Secrets.")
    st.stop()

client = genai.Client(api_key=st.secrets["GOOGLE_AI_API_KEY"])

# =========================
# Função de TTS (Gemini)
# =========================
def gerar_audio_gemini(texto: str) -> BytesIO | None:
    if not texto.strip():
        return None

    resp = client.models.generate_content(
        model="gemini-2.5-flash-preview-tts",
        contents=texto,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
        ),
    )

    part = resp.candidates[0].content.parts[0]
    audio_bytes = part.inline_data.data
    buf = BytesIO(audio_bytes)
    buf.seek(0)
    return buf

# =========================
# Interface
# =========================
texto = st.text_area("Texto para narração:", height=150)

if st.button("Gerar áudio"):
    with st.spinner("Gerando narração com Gemini..."):
        audio = gerar_audio_gemini(texto)
        if audio:
            st.audio(audio, format="audio/mp3")