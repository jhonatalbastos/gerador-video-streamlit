import streamlit as st
from io import BytesIO
from gtts import gTTS

# =========================
# Config da página
# =========================
st.set_page_config(
    page_title="Studio Jhonata - Teste de Narração",
    layout="centered",
)

st.title("🎙️ Studio Jhonata - Teste de Narração com gTTS")

st.markdown(
    "Este app gera uma narração simples usando **gTTS (Google Text-to-Speech)** "
    "em português do Brasil."
)

# =========================
# Função de áudio com gTTS
# =========================
def gerar_audio_gtts(texto: str) -> BytesIO | None:
    """Gera áudio MP3 em memória usando gTTS (pt-BR)."""
    if not texto.strip():
        return None
    mp3_fp = BytesIO()
    tts = gTTS(text=texto, lang="pt", slow=False)  # pt-BR [web:290][web:381]
    tts.write_to_fp(mp3_fp)
    mp3_fp.seek(0)
    return mp3_fp

# =========================
# Interface principal
# =========================
st.markdown("### 1. Texto para narração")

texto = st.text_area(
    "Cole aqui o trecho do roteiro (HOOK, Leitura, Reflexão, Aplicação ou Oração).",
    height=200,
)

if "audio_gtts" not in st.session_state:
    st.session_state["audio_gtts"] = None

col1, col2 = st.columns(2)
with col1:
    gerar = st.button("🎧 Gerar narração com gTTS", type="primary")
with col2:
    limpar = st.button("🧹 Limpar áudio")

if gerar:
    with st.spinner("Gerando narração..."):
        audio = gerar_audio_gtts(texto)
        if audio:
            st.session_state["audio_gtts"] = audio
            st.success("✅ Áudio gerado com sucesso.")

if limpar:
    st.session_state["audio_gtts"] = None

st.markdown("---")
st.markdown("### 2. Player / Download")

if st.session_state["audio_gtts"]:
    st.audio(st.session_state["audio_gtts"], format="audio/mp3")  # [web:324]
    st.download_button(
        "⬇️ Download narração_gtts.mp3",
        data=st.session_state["audio_gtts"],
        file_name="narracao_gtts.mp3",
        mime="audio/mp3",
    )
else:
    st.info("Nenhum áudio gerado ainda. Gere um áudio para ver o player aqui.")

st.markdown("---")
st.caption("Versão de teste apenas com gTTS. Depois integramos aos blocos do Studio Jhonata.")