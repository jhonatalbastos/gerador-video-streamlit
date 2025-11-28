# app.py — Studio Jhonata (arquivo completo)
import os
import tempfile
from io import BytesIO
import base64
import requests

from gtts import gTTS
from PIL import Image

import streamlit as st

# MoviePy import pode ser pesado — deixe no requirements.txt
from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips

# =========================
# Config da página
# =========================
st.set_page_config(
    page_title="Studio Jhonata - Teste de Narração e Vídeo",
    layout="centered",
)
st.title("🎙️ Studio Jhonata - Teste de Narração + Imagens → Vídeo")
st.markdown(
    "App de teste que gera narração (gTTS), imagens (Gemini) e monta um vídeo com MoviePy."
)

# =========================
# Config / Variáveis
# =========================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or st.secrets.get("GEMINI_API_KEY", None)
if not GEMINI_API_KEY:
    st.warning(
        "⚠️ GEMINI_API_KEY não encontrada. Configure `GEMINI_API_KEY` em Secrets (Streamlit Cloud) ou variável de ambiente."
    )

# =========================
# Função de áudio com gTTS
# =========================
def gerar_audio_gtts(texto: str) -> BytesIO | None:
    """Gera áudio MP3 em memória usando gTTS (pt-BR)."""
    if not texto or not texto.strip():
        return None
    mp3_fp = BytesIO()
    tts = gTTS(text=texto, lang="pt", slow=False)
    tts.write_to_fp(mp3_fp)
    mp3_fp.seek(0)
    return mp3_fp

# =========================
# Função de geração de imagem (Gemini - exemplo)
# =========================
def gerar_imagem_gemini(prompt: str, size: str = "1024x1024") -> BytesIO:
    """
    Gera imagem usando endpoint de imagens do Generative Language (exemplo).
    Retorna BytesIO com o conteúdo da imagem (PNG/JPEG).
    OBS: Ajuste endpoint e payload conforme o modelo/contrato da API que você usa.
    """
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY não configurada")

    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateImage?key=" + GEMINI_API_KEY

    payload = {
        "prompt": prompt,
        "size": size
    }

    r = requests.post(url, json=payload, timeout=60)
    r.raise_for_status()
    data = r.json()

    # A estrutura de retorno pode variar. Aqui assumimos que vem base64 em data["images"][0]
    if not data:
        raise RuntimeError("Resposta vazia da API de imagem")

    # tente várias chaves possíveis para compatibilidade
    b64_img = None
    if isinstance(data, dict):
        if "images" in data and isinstance(data["images"], list) and len(data["images"]) > 0:
            b64_img = data["images"][0]
        elif "image" in data and isinstance(data["image"], str):
            b64_img = data["image"]

    if not b64_img:
        raise RuntimeError("Resposta da API não contém imagem em base64. Conteúdo: " + str(data))

    img_bytes = base64.b64decode(b64_img)
    bio = BytesIO(img_bytes)
    bio.seek(0)
    return bio

# =========================
# Função para montar vídeo com MoviePy
# =========================
def montar_video(lista_imagens: list[BytesIO], audio_mp3: BytesIO) -> BytesIO:
    """
    Monta um vídeo MP4 com:
    - imagens (cada uma com duração proporcional)
    - áudio MP3 por cima
    Retorna BytesIO com o vídeo final.
    """
    if not lista_imagens or not audio_mp3:
        raise ValueError("Lista de imagens e áudio são necessários")

    # salvar temporariamente arquivos (MoviePy lida com caminhos)
    temp_dir = tempfile.mkdtemp()
    audio_path = os.path.join(temp_dir, "audio.mp3")
    with open(audio_path, "wb") as f:
        # Se audio_mp3 for BytesIO, garantir posição inicial
        try:
            audio_mp3.seek(0)
        except Exception:
            pass
        f.write(audio_mp3.read())

    image_paths = []
    for i, bio in enumerate(lista_imagens):
        img_path = os.path.join(temp_dir, f"img_{i}.png")
        try:
            bio.seek(0)
        except Exception:
            pass
        with open(img_path, "wb") as f:
            f.write(bio.read())
        image_paths.append(img_path)

    # criar clipes
    audio_clip = AudioFileClip(audio_path)
    duracao_audio = audio_clip.duration or max(1.0, len(image_paths))  # fallback
    duracao_por_imagem = duracao_audio / len(image_paths)

    clips = []
    for p in image_paths:
        # ImageClip automaticamente lê o arquivo
        clip = ImageClip(p).set_duration(duracao_por_imagem)
        # redimensiona se necessário para manter resolução consistente (ex.: 1280x720)
        # clip = clip.resize(height=720)  # opcional
        clips.append(clip)

    video = concatenate_videoclips(clips, method="compose")
    video = video.set_audio(audio_clip)

    saída_path = os.path.join(temp_dir, "final.mp4")
    # escreve arquivo — note que isso pode demorar no Streamlit Cloud dependendo do plano
    video.write_videofile(
        saída_path,
        fps=24,
        codec="libx264",
        audio_codec="aac",
        threads=2,
        verbose=False,
        logger=None,
    )

    # carregar em BytesIO para retorno
    out_bio = BytesIO()
    with open(saída_path, "rb") as f:
        out_bio.write(f.read())
    out_bio.seek(0)
    return out_bio

# =========================
# Helpers UI / Session state
# =========================
if "audio_gtts" not in st.session_state:
    st.session_state["audio_gtts"] = None
if "imagens" not in st.session_state:
    st.session_state["imagens"] = []
if "video" not in st.session_state:
    st.session_state["video"] = None

# =========================
# UI: Texto para narração
# =========================
st.markdown("## 1. Texto para narração")
texto = st.text_area(
    "Cole aqui o trecho do roteiro (HOOK, Leitura, Reflexão, Aplicação ou Oração).",
    height=200,
)

col1, col2 = st.columns(2)
with col1:
    gerar = st.button("🎧 Gerar narração com gTTS", type="primary")
with col2:
    limpar = st.button("🧹 Limpar áudio")

if gerar:
    with st.spinner("Gerando narração..."):
        try:
            audio = gerar_audio_gtts(texto)
            if audio:
                st.session_state["audio_gtts"] = audio
                st.success("✅ Áudio gerado com sucesso.")
            else:
                st.error("Texto vazio — nada foi gerado.")
        except Exception as e:
            st.error(f"Erro ao gerar áudio: {e}")

if limpar:
    st.session_state["audio_gtts"] = None
    st.success("Áudio removido.")

st.markdown("---")
st.markdown("## 2. Player / Download de Áudio")

if st.session_state["audio_gtts"]:
    try:
        st.audio(st.session_state["audio_gtts"], format="audio/mp3")
        # Reset cursor para download
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
        st.error(f"Erro exibindo player de áudio: {e}")
else:
    st.info("Nenhum áudio gerado ainda. Gere um áudio para ver o player aqui.")

st.markdown("---")

# =========================
# UI: Gerar Imagens
# =========================
st.markdown("## 3. Gerar Imagens (Gemini)")
prompt_img = st.text_input("Prompt para as imagens", value="Cena cinematográfica do Evangelho do dia, estilo litúrgico, cores suaves")
qtd = st.slider("Quantidade de imagens", 1, 8, 4)
size = st.selectbox("Tamanho da imagem", ["512x512", "768x768", "1024x1024"], index=2)

col_img1, col_img2 = st.columns(2)
with col_img1:
    gerar_imgs_btn = st.button("🎨 Criar imagens")
with col_img2:
    limpar_imgs_btn = st.button("🧹 Limpar imagens")

if gerar_imgs_btn:
    if not prompt_img or not prompt_img.strip():
        st.error("Insira um prompt válido para gerar imagens.")
    else:
        if not GEMINI_API_KEY:
            st.error("GEMINI_API_KEY ausente — não é possível gerar imagens.")
        else:
            imagens_geradas = []
            with st.spinner("Gerando imagens... (cada imagem pode levar alguns segundos)"):
                for i in range(qtd):
                    try:
                        img_bio = gerar_imagem_gemini(prompt_img, size=size)
                        imagens_geradas.append(img_bio)
                    except Exception as e:
                        st.error(f"Erro gerando imagem #{i+1}: {e}")
                        break
            if imagens_geradas:
                st.session_state["imagens"] = imagens_geradas
                st.success(f"✅ {len(imagens_geradas)} imagens geradas.")

if limpar_imgs_btn:
    st.session_state["imagens"] = []
    st.success("Imagens removidas.")

# Mostrar imagens (se existirem)
if st.session_state["imagens"]:
    st.markdown("**Imagens geradas:**")
    cols = st.columns(min(4, len(st.session_state["imagens"])))
    for i, imgbio in enumerate(st.session_state["imagens"]):
        try:
            imgbio.seek(0)
            st.image(imgbio, caption=f"Imagem {i+1}", use_column_width=True)
        except Exception as e:
            st.write(f"Erro mostrando imagem {i+1}: {e}")

st.markdown("---")

# =========================
# UI: Montar Vídeo
# =========================
st.markdown("## 4. Montar Vídeo com Áudio e Imagens")
col_vid1, col_vid2 = st.columns(2)
with col_vid1:
    montar_btn = st.button("🎬 Montar vídeo")
with col_vid2:
    limpar_video_btn = st.button("🧹 Limpar vídeo")

if montar_btn:
    if not st.session_state["audio_gtts"]:
        st.error("Gere a narração antes de montar o vídeo.")
    elif not st.session_state["imagens"]:
        st.error("Gere imagens antes de montar o vídeo.")
    else:
        with st.spinner("Renderizando vídeo (MoviePy)..."):
            try:
                # garantir ponteiros no inicio
                try:
                    st.session_state["audio_gtts"].seek(0)
                except Exception:
                    pass
                for b in st.session_state["imagens"]:
                    try:
                        b.seek(0)
                    except Exception:
                        pass

                video_bio = montar_video(st.session_state["imagens"], st.session_state["audio_gtts"])
                st.session_state["video"] = video_bio
                st.success("✅ Vídeo gerado com sucesso.")
            except Exception as e:
                st.error(f"Erro ao montar vídeo: {e}")

if limpar_video_btn:
    st.session_state["video"] = None
    st.success("Vídeo removido.")

if st.session_state["video"]:
    try:
        st.video(st.session_state["video"])
        try:
            st.session_state["video"].seek(0)
        except Exception:
            pass
        st.download_button(
            "⬇️ Baixar vídeo_final.mp4",
            data=st.session_state["video"],
            file_name="video_final.mp4",
            mime="video/mp4",
        )
    except Exception as e:
        st.error(f"Erro exibindo/baixando vídeo: {e}")

st.markdown("---")
st.caption("Versão de teste: gTTS + Gemini + MoviePy. Ajuste prompts, tamanhos e parâmetros conforme necessidade.")
