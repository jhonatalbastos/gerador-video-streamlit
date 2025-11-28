import streamlit as st
from io import BytesIO
from gtts import gTTS
import asyncio
import edge_tts

# =========================
# Config da página
# =========================
st.set_page_config(
    page_title="Teste TTS - Studio Jhonata",
    layout="centered",
)

st.title("🗣️ Teste de Narração (gTTS + Edge-TTS)")
st.markdown(
    "Use este app apenas para testar as vozes. "
    "Depois que estiver tudo ok, integramos no Studio Jhonata."
)

# =========================
# Funções utilitárias
# =========================
def gerar_tts_gtts(texto: str) -> BytesIO:
    """Gera áudio com gTTS (Google padrão, pt-BR)."""
    tts = gTTS(text=texto, lang="pt", slow=False)  # pt-BR [web:282][web:290]
    buf = BytesIO()
    tts.write_to_fp(buf)
    buf.seek(0)
    return buf


async def _gerar_tts_edge_async(texto: str, voice: str) -> BytesIO:
    """Gera áudio com Edge-TTS de forma assíncrona."""
    communicate = edge_tts.Communicate(texto, voice)  # [web:300][web:301]
    mp3_bytes = BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            mp3_bytes.write(chunk["data"])
    mp3_bytes.seek(0)
    return mp3_bytes


def gerar_tts_edge(texto: str, voice: str) -> BytesIO:
    """Wrapper síncrono para Streamlit chamar Edge-TTS."""
    return asyncio.run(_gerar_tts_edge_async(texto, voice))


def gerar_audio(texto: str, engine: str) -> BytesIO | None:
    """Seleciona engine e gera áudio."""
    if not texto.strip():
        st.warning("Digite um texto para gerar o áudio.")
        return None

    try:
        if engine == "gTTS (Google padrão)":
            return gerar_tts_gtts(texto)
        elif engine == "Edge TTS (Antônio)":
            # nome da voz pode variar; estes são exemplos comuns pt-BR [web:301][web:302]
            return gerar_tts_edge(texto, "pt-BR-AntonioNeural")
        elif engine == "Edge TTS (Francisca)":
            return gerar_tts_edge(texto, "pt-BR-FranciscaNeural")
        else:
            st.error("Engine TTS desconhecida.")
            return None
    except Exception as e:
        st.error(f"❌ Erro ao gerar áudio: {e}")
        return None


# =========================
# Interface
# =========================
st.markdown("### 1. Escolha a voz")

engine = st.selectbox(
    "Engine de narração",
    ["gTTS (Google padrão)", "Edge TTS (Antônio)", "Edge TTS (Francisca)"],
)

st.markdown("### 2. Texto para narração")
texto = st.text_area(
    "Cole aqui um trecho de roteiro (HOOK, Leitura, Reflexão, Aplicação ou Oração).",
    height=180,
)

if "audio_teste" not in st.session_state:
    st.session_state["audio_teste"] = None

col1, col2 = st.columns(2)
with col1:
    gerar = st.button("🎙️ Gerar áudio de teste", type="primary")
with col2:
    limpar = st.button("🧹 Limpar áudio")

if gerar:
    with st.spinner("Gerando áudio..."):
        audio_buf = gerar_audio(texto, engine)
        if audio_buf:
            st.session_state["audio_teste"] = audio_buf
            st.success("✅ Áudio gerado.")

if limpar:
    st.session_state["audio_teste"] = None

st.markdown("---")
st.markdown("### 3. Player / Download")

if st.session_state["audio_teste"]:
    st.audio(st.session_state["audio_teste"], format="audio/mp3")  # [web:285]
    st.download_button(
        "⬇️ Download narração.mp3",
        data=st.session_state["audio_teste"],
        file_name="narracao_teste.mp3",
        mime="audio/mp3",
    )
else:
    st.info("Nenhum áudio gerado ainda. Gere um áudio para ver o player aqui.")

st.markdown("---")
st.caption("App de teste de voz para depois integrar ao Studio Jhonata.")
