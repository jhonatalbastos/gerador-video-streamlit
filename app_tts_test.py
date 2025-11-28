import streamlit as st
from io import BytesIO
import google.genai as genai
from google.genai import types

# =========================
# Config da página
# =========================
st.set_page_config(
    page_title="Teste TTS - Gemini",
    layout="centered",
)

st.title("🗣️ Teste de Narração com Gemini TTS")
st.markdown(
    "Este app testa a narração via **Google AI (Gemini Text-to-Speech)**.

"
    "Lembre-se de configurar em *Secrets* a chave:

"
    "`GOOGLE_AI_API_KEY = "sua_chave_aqui"`"
)

# =========================
# Cliente Gemini
# =========================
if "GOOGLE_AI_API_KEY" not in st.secrets:
    st.error("❌ Falta configurar GOOGLE_AI_API_KEY em Settings → Secrets.")
    st.stop()

client = genai.Client(api_key=st.secrets["GOOGLE_AI_API_KEY"])

# =========================
# Função de TTS (Gemini)
# =========================
def gerar_audio_gemini(texto: str) -> BytesIO | None:
    if not texto.strip():
        st.warning("Digite um texto para gerar o áudio.")
        return None

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash-preview-tts",
            contents=texto,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        language_code="pt-BR",
                    )
                ),
            ),
        )

        part = response.candidates[0].content.parts[0]
        audio_bytes = part.inline_data.data
        buf = BytesIO(audio_bytes)
        buf.seek(0)
        return buf

    except Exception as e:
        st.error(f"❌ Erro ao gerar áudio com Gemini TTS: {e}")
        return None


# =========================
# Interface
# =========================
st.markdown("### 1. Texto para narração")

texto = st.text_area(
    "Cole aqui um trecho de roteiro (HOOK, Leitura, Reflexão, Aplicação ou Oração).",
    height=180,
)

if "audio_teste" not in st.session_state:
    st.session_state["audio_teste"] = None

col1, col2 = st.columns(2)
with col1:
    gerar = st.button("🎙️ Gerar áudio (Gemini TTS)", type="primary")
with col2:
    limpar = st.button("🧹 Limpar áudio")

if gerar:
    with st.spinner("Gerando narração com Gemini..."):
        audio_buf = gerar_audio_gemini(texto)
        if audio_buf:
            st.session_state["audio_teste"] = audio_buf
            st.success("✅ Áudio gerado com sucesso.")

if limpar:
    st.session_state["audio_teste"] = None

st.markdown("---")
st.markdown("### 2. Player / Download")

if st.session_state["audio_teste"]:
    st.audio(st.session_state["audio_teste"], format="audio/mp3")
    st.download_button(
        "⬇️ Download narração.mp3",
        data=st.session_state["audio_teste"],
        file_name="narracao_gemini.mp3",
        mime="audio/mp3",
    )
else:
    st.info("Nenhum áudio gerado ainda. Gere um áudio para ver o player aqui.")

st.markdown("---")
st.caption("Teste de voz com Gemini TTS para depois integrar ao Studio Jhonata.")