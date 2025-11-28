import streamlit as st
from io import BytesIO
import google.genai as genai
from google.genai import types

st.set_page_config(page_title="Gemini TTS Teste", layout="centered")

st.title("Gemini TTS Teste")

if "GOOGLE_AI_API_KEY" not in st.secrets:
    st.error("Configure GOOGLE_AI_API_KEY em Secrets.")
    st.stop()

client = genai.Client(api_key=st.secrets["GOOGLE_AI_API_KEY"])

def gerar_audio_gemini(texto: str) -> BytesIO | None:
    if not texto.strip():
        return None
    resp = client.models.generate_content(
        model="gemini-2.5-flash-preview-tts",
        contents=texto,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(language_code="pt-BR")
            ),
        ),
    )
    part = resp.candidates[0].content.parts[0]
    audio_bytes = part.inline_data.data
    buf = BytesIO(audio_bytes)
    buf.seek(0)
    return buf

texto = st.text_area("Texto para narração:", height=150)

if st.button("Gerar áudio"):
    audio = gerar_audio_gemini(texto)
    if audio:
        st.audio(audio, format="audio/mp3")