# app.py
"""
Projeto Studio Jhonata - Streamlit app
Integra:
 - Groq (opcional) para gerar/recuperar roteiro (se disponível)
 - TTS offline (pyttsx3) + pydub para conversão
 - Geração/uso de imagens (upload local OU OpenAI Images API se OPENAI_API_KEY presente)
 - Montagem do vídeo com ffmpeg (necessário ffmpeg no PATH)

Requisitos (sugestão pip):
pip install streamlit pillow pydub pyttsx3 requests openai python-multipart
# se for usar groq (se existir um cliente pip):
pip install groq-client   # nome hipotético — se você instalou um pacote diferente, ajuste
# Nota: pydub requer ffmpeg instalado no sistema (apt, brew, choco, etc).
"""

import os
import io
import json
import tempfile
import subprocess
import shlex
import time
from typing import List, Optional

import streamlit as st
from PIL import Image

# Optional dependencies: import inside functions with graceful fallback
# TTS: pyttsx3 (offline)
# Audio conversion: pydub
# OpenAI images: openai (optional)

st.set_page_config(page_title="Studio Jhonata", layout="wide")

# -----------------------
# Utility helpers
# -----------------------
def run_cmd(cmd: List[str], timeout: int = 300):
    """Run subprocess command and stream output to st (for debugging)."""
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        stdout, _ = proc.communicate(timeout=timeout)
        return proc.returncode, stdout
    except subprocess.TimeoutExpired:
        proc.kill()
        return -1, "timeout"
    except Exception as e:
        return -1, str(e)

def check_ffmpeg():
    code, out = run_cmd(["ffmpeg", "-version"])
    return code == 0

# -----------------------
# Groq integration (optional)
# -----------------------
def fetch_script_from_groq(prompt: str) -> str:
    """
    Try to use Groq client to fetch/generate a script.
    If groq isn't installed or fails, return a fallback sample script.
    """
    try:
        # Try to import a groq client (name may differ); adjust if your environment uses a different package
        import groq
        # Example usage pattern (pseudo) - replace with actual usage for your installed groq client:
        # client = groq.Client(api_key=os.environ.get("GROQ_API_KEY"))
        # resp = client.query(prompt)
        # return resp["text"]
        # Since clients differ, raise NotImplementedError to remind user to adapt:
        raise NotImplementedError(
            "Groq client detected but usage is not implemented in this template. "
            "Adapt fetch_script_from_groq() to your Groq client methods."
        )
    except ModuleNotFoundError:
        st.warning("Módulo 'groq' não encontrado. Usando roteiro de exemplo. Se quiser integrar Groq, instale o cliente e adapte fetch_script_from_groq().")
    except NotImplementedError as e:
        st.info(str(e))
    except Exception as e:
        st.error(f"Erro ao inicializar Groq client: {e}")

    # Fallback sample script (simple storyboard)
    sample = (
        "Título: A Jornada do Espaço\n\n"
        "Cena 1 (0:00-0:20): Visão ampla do cosmos. Narração: 'No silêncio do infinito, surge uma história.'\n"
        "Cena 2 (0:20-0:50): Aproximação em um buraco negro. Narração: 'Lá onde o tempo dobra...' \n"
        "Cena 3 (0:50-1:20): Imagens conceituais, dados e gráficos animados. Narração: 'A ciência desafia o imaginável.'\n"
        "Encerramento (1:20-1:30): Créditos rápidos.\n"
    )
    return sample

# -----------------------
# TTS (pyttsx3 offline) -> exports WAV file
# -----------------------
def tts_generate_offline(text: str, outfile: str, rate: int = 150, voice_name_contains: Optional[str] = None):
    """
    Generate TTS using pyttsx3 (offline).
    Saves WAV to outfile. Returns path.
    """
    try:
        import pyttsx3
    except Exception as e:
        raise RuntimeError("pyttsx3 não está instalado. pip install pyttsx3") from e

    engine = pyttsx3.init()
    try:
        engine.setProperty("rate", rate)
    except Exception:
        pass

    # select voice if requested
    if voice_name_contains:
        voices = engine.getProperty("voices")
        for v in voices:
            try:
                if voice_name_contains.lower() in v.name.lower() or voice_name_contains.lower() in v.id.lower():
                    engine.setProperty("voice", v.id)
                    break
            except Exception:
                continue

    # pyttsx3 can save to file via engine.save_to_file
    engine.save_to_file(text, outfile)
    engine.runAndWait()
    # Wait a bit to ensure file flushed
    time.sleep(0.5)
    if not os.path.exists(outfile):
        raise RuntimeError("Falha ao gerar áudio com pyttsx3.")
    return outfile

def convert_audio_to_mp3(input_path: str, output_path: str):
    """
    Convert wav to mp3 using ffmpeg (via subprocess) or pydub if available.
    """
    # Prefer ffmpeg via subprocess
    if check_ffmpeg():
        cmd = ["ffmpeg", "-y", "-i", input_path, "-vn", "-ar", "44100", "-ac", "2", "-b:a", "192k", output_path]
        code, out = run_cmd(cmd)
        if code != 0:
            raise RuntimeError(f"ffmpeg conversion failed: {out}")
        return output_path
    else:
        # Try pydub
        try:
            from pydub import AudioSegment
            a = AudioSegment.from_file(input_path)
            a.export(output_path, format="mp3")
            return output_path
        except Exception as e:
            raise RuntimeError("Não foi possível converter áudio: instale ffmpeg ou pydub.") from e

# -----------------------
# Image generation / handling
# -----------------------
def generate_images_openai(prompt: str, n_images: int = 1, size: str = "1024x1024") -> List[Image.Image]:
    """
    Generate images using OpenAI Images API if OPENAI_API_KEY is present.
    Returns list of PIL Images.
    """
    try:
        import openai
    except Exception as e:
        raise RuntimeError("openai package não instalado. pip install openai") from e

    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY não configurada no ambiente.")
    openai.api_key = key

    images = []
    try:
        resp = openai.images.generate(model="gpt-image-1", prompt=prompt, size=size, n=n_images)
        # The structure may vary depending on the OpenAI SDK version; adjust if needed.
        for item in resp.data:
            b64 = item.b64_json
            import base64
            img_bytes = base64.b64decode(b64)
            img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            images.append(img)
    except Exception as e:
        raise RuntimeError(f"Erro ao gerar imagens via OpenAI: {e}")
    return images

# -----------------------
# Video assembly (FFmpeg)
# -----------------------
def create_video_from_images_and_audio(images_paths: List[str], audio_path: str, output_path: str, fps: int = 1):
    """
    Create a simple video from a sequence of images and a single audio track using ffmpeg.
    images_paths: ordered list of image file paths
    audio_path: path to audio (mp3/wav)
    output_path: final mp4 path
    fps: how many frames per second (use low fps and repeat frames to extend duration)
    """
    if not check_ffmpeg():
        raise RuntimeError("ffmpeg não encontrado no PATH. Instale ffmpeg para montar o vídeo.")

    tmpdir = tempfile.mkdtemp(prefix="sj_vid_")
    # Prepare input images as sequentially numbered files
    seq_dir = os.path.join(tmpdir, "seq")
    os.makedirs(seq_dir, exist_ok=True)

    # We'll create each image as img0001.png ...
    for idx, img_path in enumerate(images_paths):
        dst = os.path.join(seq_dir, f"img{idx:04d}.png")
        img = Image.open(img_path).convert("RGB")
        img.save(dst)

    # Build ffmpeg command:
    # 1) Create video from images (set framerate to 1 fps, then scale)
    # 2) Add audio, encode to mp4
    # Using image2 demuxer
    input_pattern = os.path.join(seq_dir, "img%04d.png")
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", input_pattern,
        "-i", audio_path,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-shortest",
        output_path
    ]
    code, out = run_cmd(cmd, timeout=600)
    if code != 0:
        raise RuntimeError(f"ffmpeg falhou: {out}")
    return output_path

# -----------------------
# Streamlit UI
# -----------------------
st.title("🎬 Studio Jhonata — Streamlit Groq · Áudio · Imagem · Vídeo")

st.sidebar.header("Configurações")
use_groq = st.sidebar.checkbox("Tentar obter roteiro via Groq", value=True)
openai_images = st.sidebar.checkbox("Permitir geração de imagens via OpenAI (se chave presente)", value=False)
tts_offline = st.sidebar.checkbox("Usar TTS offline (pyttsx3)", value=True)
voice_search = st.sidebar.text_input("Procurar voz contendo (nome)", value="")  # ex: "male", "brazil"
audio_rate = st.sidebar.slider("Taxa de fala (words/min)", 100, 250, 150)
fps = st.sidebar.selectbox("Frames por segundo (para montagem)", options=[1, 0.5, 0.2], index=0, format_func=lambda x: f"{x} fps")

st.header("1) Entrada do roteiro / prompt")
prompt_text = st.text_area("Prompt ou breve descrição do vídeo (use para Groq ou geração de imagens/roteiro)", height=140)
if not prompt_text:
    st.info("Digite um prompt ou descrição para começar. Você pode também colar um roteiro pré-produzido.")
    # still allow continuing with sample script
fetch_button = st.button("Gerar/Buscar roteiro")

script_text = ""
if fetch_button:
    if use_groq:
        try:
            script_text = fetch_script_from_groq(prompt_text)
        except Exception as e:
            st.error(f"Erro ao usar Groq: {e}")
            script_text = fetch_script_from_groq("")  # fallback
    else:
        # Just generate simple script locally (very naive split)
        script_text = fetch_script_from_groq(prompt_text)

if "script_cached" not in st.session_state:
    st.session_state["script_cached"] = ""

if script_text:
    st.session_state["script_cached"] = script_text

st.header("2) Roteiro (edite se quiser)")
script_text = st.text_area("Roteiro / Roteiro final (texto que será narrado)", value=st.session_state.get("script_cached", ""), height=220)

st.header("3) Imagens (upload ou gerar)")
col1, col2 = st.columns(2)
uploaded_files = col1.file_uploader("Upload de imagens (PNG/JPG) — ordem será respeitada", type=["png", "jpg", "jpeg"], accept_multiple_files=True)
generate_images_prompt = col2.text_input("Prompt para gerar imagens (se usar OpenAI) — deixa vazio para pular")
num_images = col2.slider("Quantidade de imagens ao gerar", 1, 6, 3)

images_paths = []
if uploaded_files:
    # Save uploaded images to temp
    for f in uploaded_files:
        tfile = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(f.name)[1])
        tfile.write(f.getbuffer())
        tfile.flush()
        images_paths.append(tfile.name)

# If no uploads and user wants to generate via OpenAI (and key present)
if (not images_paths) and generate_images_prompt and openai_images:
    try:
        imgs = generate_images_openai(generate_images_prompt, n_images=num_images)
        for i, img in enumerate(imgs):
            p = os.path.join(tempfile.gettempdir(), f"sj_img_{int(time.time())}_{i}.png")
            img.save(p)
            images_paths.append(p)
        st.success(f"{len(images_paths)} imagens geradas via OpenAI.")
    except Exception as e:
        st.error(f"Falha ao gerar imagens via OpenAI: {e}")

# If still no images, show placeholder and allow user to continue
if not images_paths:
    st.info("Sem imagens fornecidas. Faça upload ou ative geração via OpenAI (se tiver OPENAI_API_KEY). Você também pode continuar e eu montarei um vídeo apenas com texto (plano de fundo simples).")

# Display thumbnails
if images_paths:
    st.write("Pré-visualização das imagens selecionadas:")
    cols = st.columns(4)
    for i, p in enumerate(images_paths):
        try:
            img = Image.open(p)
            cols[i % 4].image(img, caption=os.path.basename(p), use_column_width=True)
        except Exception:
            cols[i % 4].text(os.path.basename(p))

st.header("4) Texto da narração / divisão em blocos")
# Allow user to split script into N parts for separate image mapping
n_blocks = st.number_input("Dividir roteiro em quantas partes (cada parte corresponderá a 1+ imagens)", min_value=1, max_value=20, value=3)
if script_text.strip():
    # Naive split
    parts = [p.strip() for p in script_text.strip().split("\n\n") if p.strip()]
    # If not enough parts, do chunking by sentences
    if len(parts) < n_blocks:
        import re, math
        sents = re.split(r'(?<=[.!?])\s+', script_text.strip())
        chunk_size = max(1, math.ceil(len(sents)/n_blocks))
        parts = [" ".join(sents[i:i+chunk_size]) for i in range(0, len(sents), chunk_size)]
    # Ensure exactly n_blocks (pad or trim)
    if len(parts) < n_blocks:
        parts += [""] * (n_blocks - len(parts))
    parts = parts[:n_blocks]
else:
    parts = [""] * n_blocks

st.write("Blocos de narração (edite cada um):")
parts_edits = []
for i in range(n_blocks):
    p = st.text_area(f"Bloco {i+1}", value=parts[i], height=80, key=f"block_{i}")
    parts_edits.append(p)

st.header("5) Gerar áudio (TTS) e montar vídeo")
col_audio, col_video = st.columns(2)
with col_audio:
    st.subheader("Configurações de Áudio")
    audio_format = st.selectbox("Formato de saída do áudio", ["mp3", "wav"], index=0)
    generate_tts_btn = st.button("Gerar áudio TTS")
with col_video:
    st.subheader("Configurações de Vídeo")
    final_resolution = st.selectbox("Resolução de saída", ["1280x720", "1920x1080"], index=0)
    assemble_video_btn = st.button("Montar vídeo final (imagens + áudio)")

generated_audio_files = []

if generate_tts_btn:
    # For each block, generate audio file and show progress
    st.info("Gerando TTS para cada bloco...")
    for idx, txt in enumerate(parts_edits):
        if not txt.strip():
            continue
        # Create temporary wav path (pyttsx3 may generate wav)
        temp_wav = os.path.join(tempfile.gettempdir(), f"sj_tts_block_{idx}.wav")
        try:
            tts_generate_offline(txt, temp_wav, rate=audio_rate, voice_name_contains=voice_search if voice_search else None)
            # Convert to requested format if needed
            if audio_format == "mp3":
                mp3_path = temp_wav.replace(".wav", ".mp3")
                convert_audio_to_mp3(temp_wav, mp3_path)
                generated_audio_files.append(mp3_path)
                st.success(f"Bloco {idx+1} -> {os.path.basename(mp3_path)}")
            else:
                generated_audio_files.append(temp_wav)
                st.success(f"Bloco {idx+1} -> {os.path.basename(temp_wav)}")
        except Exception as e:
            st.error(f"Erro gerando áudio para bloco {idx+1}: {e}")

    if not generated_audio_files:
        st.warning("Nenhum áudio foi gerado (provavelmente todos os blocos vazios).")

# Assemble video
if assemble_video_btn:
    st.info("Montando vídeo... (isso usa ffmpeg no servidor local)")
    try:
        if not images_paths:
            st.warning("Sem imagens: vou criar imagens simples (background preto + texto).")
            # Create simple images with the text of each block
            images_paths = []
            for i, txt in enumerate(parts_edits):
                im = Image.new("RGB", (1280, 720), color=(10, 10, 10))
                from PIL import ImageDraw, ImageFont
                draw = ImageDraw.Draw(im)
                # Try to load a truetype font if available
                try:
                    font = ImageFont.truetype("DejaVuSans.ttf", 28)
                except Exception:
                    font = ImageFont.load_default()
                # Wrap text
                import textwrap
                wrapped = "\n".join(textwrap.wrap(txt, width=40))
                draw.multiline_text((60, 60), wrapped, font=font, fill=(230, 230, 230))
                p = os.path.join(tempfile.gettempdir(), f"sj_auto_img_{i}.png")
                im.save(p)
                images_paths.append(p)

        # If there are multiple audio files, concatenate them into one
        if generated_audio_files:
            if len(generated_audio_files) == 1:
                final_audio = generated_audio_files[0]
            else:
                # concatenate via ffmpeg
                list_txt = os.path.join(tempfile.gettempdir(), f"sj_list_{int(time.time())}.txt")
                with open(list_txt, "w", encoding="utf-8") as f:
                    for p in generated_audio_files:
                        f.write(f"file '{p}'\n")
                final_audio = os.path.join(tempfile.gettempdir(), f"sj_final_audio_{int(time.time())}.mp3")
                code, out = run_cmd(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_txt, "-c", "copy", final_audio])
                if code != 0:
                    # fallback: try pydub
                    try:
                        from pydub import AudioSegment
                        combined = None
                        for p in generated_audio_files:
                            seg = AudioSegment.from_file(p)
                            combined = seg if combined is None else combined + seg
                        combined.export(final_audio, format="mp3")
                    except Exception as e:
                        raise RuntimeError("Falha ao concatenar áudios com ffmpeg/pydub: " + str(e))
        else:
            # If no audio, create a silent audio track of some length (e.g., 1s per image)
            duration = max(1, len(images_paths) * 2)
            final_audio = os.path.join(tempfile.gettempdir(), f"sj_silent_{int(time.time())}.wav")
            if check_ffmpeg():
                cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"anullsrc=channel_layout=stereo:sample_rate=44100", "-t", str(duration), final_audio]
                code, out = run_cmd(cmd)
                if code != 0:
                    raise RuntimeError("Falha ao criar áudio silencioso.")
            else:
                raise RuntimeError("Não há áudio e ffmpeg não disponível para gerar silêncio.")

        # Compute frame duration per image: produce a video length matched to audio duration
        # Get audio duration via ffprobe
        def get_audio_duration(path):
            code, out = run_cmd(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path])
            if code != 0:
                return None
            try:
                return float(out.strip())
            except:
                return None

        audio_dur = get_audio_duration(final_audio)
        if audio_dur:
            # We'll set fps such that each image shows for a proportional time: images_count / audio_dur => frames per second small.
            # Simpler: compute per-image duration and create slideshow by repeating frames with fps=1 and letting -shortest cut by audio.
            per_img_seconds = max(1.0, audio_dur / max(1, len(images_paths)))
            # We'll set fps=1 and duplicate images so each image lasts per_img_seconds (use -framerate 1 and -t param in ffmpeg won't easily set per-image duration).
            # Simpler approach: create a video using -loop 1 per image and concat them with durations.
            concat_list = []
            concat_tmpdir = tempfile.mkdtemp(prefix="sj_concat_")
            prepared = []
            for i, img in enumerate(images_paths):
                # create a short video from each image of duration per_img_seconds
                img_vid = os.path.join(concat_tmpdir, f"img_{i}.mp4")
                cmd = [
                    "ffmpeg", "-y",
                    "-loop", "1",
                    "-i", img,
                    "-c:v", "libx264",
                    "-t", str(per_img_seconds),
                    "-pix_fmt", "yuv420p",
                    "-vf", f"scale={final_resolution}",
                    img_vid
                ]
                code, out = run_cmd(cmd)
                if code != 0:
                    raise RuntimeError(f"ffmpeg falhou ao criar clipe de imagem: {out}")
                prepared.append(img_vid)
            # create concat file
            concat_txt = os.path.join(concat_tmpdir, "concat.txt")
            with open(concat_txt, "w", encoding="utf-8") as f:
                for p in prepared:
                    f.write(f"file '{p}'\n")
            video_no_audio = os.path.join(tempfile.gettempdir(), f"sj_video_noaudio_{int(time.time())}.mp4")
            code, out = run_cmd(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_txt, "-c", "copy", video_no_audio])
            if code != 0:
                raise RuntimeError(f"ffmpeg falhou ao concatenar clipes: {out}")

            final_output = os.path.join(tempfile.gettempdir(), f"studio_jhonata_video_{int(time.time())}.mp4")
            code, out = run_cmd(["ffmpeg", "-y", "-i", video_no_audio, "-i", final_audio, "-c:v", "copy", "-c:a", "aac", "-shortest", final_output])
            if code != 0:
                raise RuntimeError(f"ffmpeg falhou ao juntar áudio e vídeo: {out}")
        else:
            # fallback to image-to-video simple approach
            final_output = os.path.join(tempfile.gettempdir(), f"studio_jhonata_video_{int(time.time())}.mp4")
            create_video_from_images_and_audio(images_paths, final_audio, final_output, fps=1)

        st.success(f"Vídeo gerado: {final_output}")
        # Provide download link
        with open(final_output, "rb") as f:
            video_bytes = f.read()
            st.video(video_bytes)
            st.download_button("Download do vídeo (.mp4)", data=video_bytes, file_name=os.path.basename(final_output), mime="video/mp4")

    except Exception as e:
        st.error(f"Falha ao montar vídeo: {e}")

st.header("Logs e dicas")
st.markdown("""
- Certifique-se de ter `ffmpeg` instalado no servidor/PC (ffmpeg no PATH).
- Para integrar Groq: instale o cliente Python adequado e edite `fetch_script_from_groq()` com o fluxo do seu cliente (autenticação, método de query).
- Para gerar imagens automaticamente, configure `OPENAI_API_KEY` e marque a opção correspondente.
- O TTS offline com `pyttsx3` funciona sem Internet, mas você pode trocar por serviços online (Google, ElevenLabs, OpenAI) se preferir maior qualidade.
""")

st.markdown("### Requisitos sugeridos (arquivo requirements.txt)")
st.code("""streamlit
pillow
pyttsx3
pydub
requests
openai
# opcional (se existir cliente groq no pip)
# groq-client
""")

st.markdown("### Observações finais")
st.write("""
Este app é uma base funcional e robusta para seu fluxo: adquirir roteiro (Groq), preparar imagens, gerar narração e montar o vídeo via ffmpeg.
Você pode adaptar:
- fetch_script_from_groq() para usar o seu cliente/endpoint Groq (incluir chave em env GROQ_API_KEY).
- generate_images_openai() dependendo da versão do SDK OpenAI que você usa.
- Substituir TTS offline por serviços (ElevenLabs, OpenAI TTS) para voz mais natural.
Se quiser, eu adapto este arquivo para o seu ambiente específico (ex.: nome exato do package groq que você instalou, ou se prefere ElevenLabs para TTS).""")

# End of app.py
