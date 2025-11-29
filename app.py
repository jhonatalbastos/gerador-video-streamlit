# app.py — Studio Jhonata (COMPLETO: restaura funções originais + mantém adições)
# Observação: este arquivo contém:
#  - o código original que você me enviou (gTTS + UI simples)
#  - as novas funções (Gemini TTS, geração de imagens via Gemini, montagem de vídeo com MoviePy)
#  - ajustes para Streamlit Cloud (ffmpeg path)
# Substitua o app.py atual por este arquivo inteiro.

import os
import tempfile
import time
import traceback
from io import BytesIO
import base64
from typing import List

import requests
from PIL import Image
import streamlit as st

# Forçar moviepy/imageio a usar ffmpeg do sistema (Streamlit Cloud)
os.environ.setdefault("IMAGEIO_FFMPEG_EXE", "/usr/bin/ffmpeg")

# MoviePy import (coloque moviepy no requirements.txt)
try:
    from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips
except Exception:
    # let the UI still load and show proper error if moviepy missing
    ImageClip = None
    AudioFileClip = None
    concatenate_videoclips = None

# ============================================
# Configuração da página
# ============================================
st.set_page_config(
    page_title="Studio Jhonata - Teste de Narração",
    layout="centered",
)
st.title("🎙️ Studio Jhonata - Teste de Narração com gTTS (e extras integrados)")
st.markdown(
    "Este app gera narração usando **gTTS (Google Text-to-Speech)** em português do Brasil. "
    "Também inclui opções adicionais: Gemini TTS, geração de imagens e montagem de vídeo."
)

# ============================================
# GEMINI API KEY (para quando quiser usar)
# ============================================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or st.secrets.get("GEMINI_API_KEY", None)
if not GEMINI_API_KEY:
    st.info("Dica: configure GEMINI_API_KEY nas Secrets para usar Gemini TTS / imagens (opcional).")

# ============================================
# -------------------
# Função original: gerar_audio_gtts
# -------------------
# Mantive a função original idêntica ao que você me enviou no início.
# Ela usa gTTS para produzir MP3 em memória.
# ============================================
def gerar_audio_gtts(texto: str) -> BytesIO | None:
    """Gera áudio MP3 em memória usando gTTS (pt-BR)."""
    if not texto or not texto.strip():
        return None
    mp3_fp = BytesIO()
    try:
        from gtts import gTTS
        tts = gTTS(text=texto, lang="pt", slow=False)  # pt-BR
        tts.write_to_fp(mp3_fp)
        mp3_fp.seek(0)
        return mp3_fp
    except Exception as e:
        # rethrow to be handled by UI
        raise RuntimeError(f"Erro gTTS: {e}")

# ============================================
# -------------------
# Funções novas: Gemini TTS, imagem, vídeo
# -------------------
# Essas funções foram adicionadas para oferecer TTS neural e imagens.
# Use GEMINI_API_KEY configurada nas secrets.
# ============================================

def post_json_with_retries(url: str, payload: dict, timeout: int = 120, retries: int = 2, backoff: float = 1.0):
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

def gerar_audio_gemini(texto: str, voz: str = "pt-BR-Wavenet-B") -> BytesIO:
    """
    Gera áudio MP3 via endpoint generateContent do Generative Language (Gemini).
    Retorna BytesIO com MP3.
    """
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY ausente.")
    if not texto or not texto.strip():
        raise ValueError("Texto vazio.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"

    prompt_text = f"(tts|voice:{voz})\nPor favor, narre o texto abaixo em português do Brasil com entonação natural:\n{texto}"

    payload = {
        "contents": [
            {"role": "user", "parts": [{"text": prompt_text}]}
        ],
        "generationConfig": {"responseMimeType": "audio/mpeg"}
    }

    data = post_json_with_retries(url, payload, timeout=120, retries=2, backoff=1.5)

    try:
        b64 = data["candidates"][0]["content"]["parts"][0]["inline_data"]["data"]
    except Exception as e:
        raise RuntimeError(f"Resposta inesperada do Gemini TTS: {data}") from e

    audio_bytes = base64.b64decode(b64)
    bio = BytesIO(audio_bytes)
    bio.seek(0)
    return bio

def gerar_imagem_gemini(prompt: str, size: str = "1024x1024") -> BytesIO:
    """
    Gera imagem PNG via Gemini generateContent. Retorna BytesIO com PNG.
    """
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY ausente.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"

    payload = {
        "contents": [
            {"role": "user", "parts": [{"text": f"Create a {size} cinematic liturgical image with tasteful composition and soft lighting: {prompt}"}]}
        ],
        "generationConfig": {"responseMimeType": "image/png"}
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

def montar_video(lista_imagens: List[BytesIO], audio_mp3: BytesIO, fps: int = 24) -> BytesIO:
    """
    Monta vídeo MP4 com imagens e áudio. Retorna BytesIO com MP4.
    """
    if ImageClip is None or AudioFileClip is None or concatenate_videoclips is None:
        raise RuntimeError("moviepy não está instalado corretamente.")
    if not lista_imagens or not audio_mp3:
        raise ValueError("Lista de imagens e áudio são necessários")

    temp_dir = tempfile.mkdtemp()
    audio_path = os.path.join(temp_dir, "audio.mp3")
    audio_mp3.seek(0)
    with open(audio_path, "wb") as f:
        f.write(audio_mp3.read())

    image_paths = []
    for i, bio in enumerate(lista_imagens):
        img_path = os.path.join(temp_dir, f"img_{i}.png")
        bio.seek(0)
        with open(img_path, "wb") as f:
            f.write(bio.read())
        image_paths.append(img_path)

    audio_clip = AudioFileClip(audio_path)
    duracao_audio = audio_clip.duration or max(1.0, len(image_paths))
    dur_por_imagem = duracao_audio / max(1, len(image_paths))

    clips = []
    for p in image_paths:
        clip = ImageClip(p).set_duration(dur_por_imagem)
        clips.append(clip)

    video = concatenate_videoclips(clips, method="compose")
    video = video.set_audio(audio_clip)

    saída_path = os.path.join(temp_dir, "final.mp4")
    video.write_videofile(saída_path, fps=fps, codec="libx264", audio_codec="aac", verbose=False, logger=None)

    out_bio = BytesIO()
    with open(saída_path, "rb") as f:
        out_bio.write(f.read())
    out_bio.seek(0)
    return out_bio

# ============================================
# Session state: preserva as várias funções/estados
# ============================================
if "audio_gtts" not in st.session_state:
    st.session_state["audio_gtts"] = None
if "audio_gemini" not in st.session_state:
    st.session_state["audio_gemini"] = None
if "imagens" not in st.session_state:
    st.session_state["imagens"] = []            # original images (if any)
if "imgs_gemini" not in st.session_state:
    st.session_state["imgs_gemini"] = []        # images generated by Gemini
if "video" not in st.session_state:
    st.session_state["video"] = None            # original video slot (if used)
if "video_gemini" not in st.session_state:
    st.session_state["video_gemini"] = None     # video from Gemini images + audio

# ============================================
# === UI: Parte ORIGINAL (gTTS) - restaurada ===
# ============================================
st.markdown("### 1. Texto para narração (ORIGINAL gTTS)")
texto_original = st.text_area(
    "Cole aqui o trecho do roteiro (HOOK, Leitura, Reflexão, Aplicação ou Oração).",
    height=200,
)

col1, col2 = st.columns(2)
with col1:
    gerar_gtts_btn = st.button("🎧 Gerar narração com gTTS (original)", key="gerar_gtts")
with col2:
    limpar_gtts_btn = st.button("🧹 Limpar áudio gTTS", key="limpar_gtts")

if gerar_gtts_btn:
    with st.spinner("Gerando narração com gTTS..."):
        try:
            audio = gerar_audio_gtts(texto_original)
            if audio:
                st.session_state["audio_gtts"] = audio
                st.success("✅ Áudio (gTTS) gerado com sucesso.")
            else:
                st.error("Texto vazio — nada foi gerado (gTTS).")
        except Exception as e:
            st.error(f"Erro ao gerar áudio gTTS: {e}")
            st.error(traceback.format_exc())

if limpar_gtts_btn:
    st.session_state["audio_gtts"] = None
    st.success("Áudio gTTS removido.")

st.markdown("---")
st.markdown("### 2. Player / Download (ORIGINAL gTTS)")
if st.session_state["audio_gtts"]:
    try:
        st.audio(st.session_state["audio_gtts"], format="audio/mp3")
        try:
            st.session_state["audio_gtts"].seek(0)
        except Exception:
            pass
        st.download_button(
            "⬇️ Download narração_gtts.mp3",
            data=st.session_state["audio_gtts"],
            file_name="narracao_gtts.mp3",
            mime="audio/mp3",
        )
    except Exception as e:
        st.error(f"Erro exibindo player de áudio gTTS: {e}")
else:
    st.info("Nenhum áudio gTTS gerado ainda. Gere um áudio para ver o player aqui.")

# ============================================
# === UI: Parte NOVA (Gemini TTS + Imagens + Vídeo) ===
# ============================================
st.markdown("---")
st.markdown("## 3. Gemini TTS (opcional) — voz neural")
st.markdown("Use GEMINI_API_KEY nas Streamlit Secrets para essa opção (opcional).")

texto_gemini = st.text_area("Texto para Gemini TTS (ou cole mesmo texto de cima)", height=150)
colg1, colg2 = st.columns(2)
with colg1:
    gerar_gemini_btn = st.button("🔊 Gerar narração (Gemini TTS)", key="gerar_gemini")
with colg2:
    limpar_gemini_btn = st.button("🧹 Limpar narração Gemini", key="limpar_gemini")

if gerar_gemini_btn:
    if not GEMINI_API_KEY:
        st.error("GEMINI_API_KEY não configurada. Configure em Settings → Secrets.")
    elif not texto_gemini or not texto_gemini.strip():
        st.error("Digite o texto para Gemini TTS.")
    else:
        try:
            with st.spinner("Gerando áudio com Gemini TTS..."):
                st.session_state["audio_gemini"] = gerar_audio_gemini(texto_gemini, voz="pt-BR-Wavenet-B")
                st.success("Áudio Gemini gerado.")
        except Exception as e:
            st.error(f"Erro Gemini TTS: {e}")
            st.error(traceback.format_exc())

if limpar_gemini_btn:
    st.session_state["audio_gemini"] = None
    st.success("Narração Gemini limpa.")

st.markdown("---")
st.subheader("Player / Download (Gemini TTS)")
if st.session_state["audio_gemini"]:
    try:
        st.audio(st.session_state["audio_gemini"], format="audio/mp3")
        try:
            st.session_state["audio_gemini"].seek(0)
        except Exception:
            pass
        st.download_button(
            "⬇️ Download narração_gemini.mp3",
            data=st.session_state["audio_gemini"],
            file_name="narracao_gemini.mp3",
            mime="audio/mp3",
        )
    except Exception as e:
        st.error(f"Erro exibindo player Gemini: {e}")

# ============================================
# === UI: Gerar imagens com Gemini (nova) ===
# ============================================
st.markdown("---")
st.markdown("### 4. Gerar imagens (Gemini)")
prompt_img = st.text_input("Prompt para as imagens", value="Cena cinematográfica do Evangelho do dia, estilo litúrgico, cores suaves")
qtd = st.slider("Quantidade de imagens", 1, 6, 3)
size = st.selectbox("Tamanho da imagem", ["512x512", "768x768", "1024x1024"], index=2)

col_img1, col_img2 = st.columns(2)
with col_img1:
    gerar_imgs_btn = st.button("🎨 Criar imagens (Gemini)", key="gerar_imgs")
with col_img2:
    limpar_imgs_btn = st.button("🧹 Limpar imagens Gemini", key="limpar_imgs")

if gerar_imgs_btn:
    if not GEMINI_API_KEY:
        st.error("GEMINI_API_KEY ausente — configure em Secrets.")
    elif not prompt_img or not prompt_img.strip():
        st.error("Insira um prompt válido para imagens.")
    else:
        st.session_state["imgs_gemini"] = []
        erro = False
        with st.spinner("Gerando imagens..."):
            for i in range(qtd):
                try:
                    img_bio = gerar_imagem_gemini(prompt_img, size=size)
                    st.session_state["imgs_gemini"].append(img_bio)
                except Exception as e:
                    st.error(f"Erro ao gerar imagem #{i+1}: {e}")
                    erro = True
                    break
        if not erro:
            st.success(f"{len(st.session_state['imgs_gemini'])} imagens geradas.")

if limpar_imgs_btn:
    st.session_state["imgs_gemini"] = []
    st.success("Imagens Gemini removidas.")

st.markdown("**Imagens geradas (Gemini):**")
if st.session_state["imgs_gemini"]:
    cols = st.columns(min(4, len(st.session_state["imgs_gemini"])))
    for i, imgbio in enumerate(st.session_state["imgs_gemini"]):
        try:
            imgbio.seek(0)
            cols[i % len(cols)].image(imgbio, caption=f"Gemini img {i+1}", use_column_width=True)
        except Exception as e:
            st.write(f"Erro mostrando imagem {i+1}: {e}")

# ============================================
# === UI: Montar vídeo (nova) ===
# ============================================
st.markdown("---")
st.markdown("### 5. Montar vídeo final (opcional)")
col_v1, col_v2 = st.columns(2)
with col_v1:
    montar_btn = st.button("🎬 Montar vídeo (imagens Gemini + narração Gemini)", key="montar_gemini")
with col_v2:
    limpar_vid_btn = st.button("🧹 Limpar vídeo Gemini", key="limpar_vid")

if montar_btn:
    if not st.session_state["audio_gemini"]:
        st.error("Gere a narração Gemini antes de montar o vídeo.")
    elif not st.session_state["imgs_gemini"]:
        st.error("Gere imagens Gemini antes de montar o vídeo.")
    else:
        try:
            with st.spinner("Renderizando vídeo (MoviePy)..."):
                # garantir seek
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
                st.success("✅ Vídeo criado com sucesso.")
        except Exception as e:
            st.error(f"Erro ao montar vídeo: {e}")
            st.error(traceback.format_exc())

if limpar_vid_btn:
    st.session_state["video_gemini"] = None
    st.success("Vídeo Gemini limpo.")

if st.session_state["video_gemini"]:
    try:
        st.video(st.session_state["video_gemini"])
        try:
            st.session_state["video_gemini"].seek(0)
        except Exception:
            pass
        st.download_button("⬇️ Baixar vídeo_final_gemini.mp4", st.session_state["video_gemini"], file_name="video_final_gemini.mp4", mime="video/mp4")
    except Exception as e:
        st.error(f"Erro exibindo/baixando vídeo Gemini: {e}")

# ============================================
# === UI: Espaço para funcionalidades originais extras (se você tinha mais) ===
# ============================================
st.markdown("---")
st.caption("Observação: este app mantém a função ORIGINAL de gTTS e adiciona Gemini TTS / imagens / vídeo. Se existiam outras funções específicas no seu app original que não identifiquei, cole aqui o trecho que falta e eu restauro exatamente.")

# ============================================
# === Dicas finais / logs simplificados
# ============================================
st.markdown("---")
st.write("Status de sessão (debug rápido):")
st.write({
    "audio_gtts": bool(st.session_state["audio_gtts"]),
    "audio_gemini": bool(st.session_state["audio_gemini"]),
    "imgs_gemini": len(st.session_state["imgs_gemini"]),
    "video_gemini": bool(st.session_state["video_gemini"]),
})
st.caption("Se algo faltar do app original, cole aqui o bloco (ou me diga qual função exata faltou) e eu reponho imediatamente — vou restaurar 1:1 sem mexer no que já funcionava.")
