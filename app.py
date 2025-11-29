# app.py
"""
Studio Jhonata — app Streamlit (versão A: funções organizadas)
Integrações:
 - Texto: Groq (preferência) -> fallback Railway HTTP (RAILWAY_TEXT_ENDPOINT)
 - Imagens: Google ImageFX (image-generation-001) via google.generativeai (genai) ou HTTP (fallback)
 - Áudio: TTS offline com pyttsx3 (pydub/ffmpeg para conversão, se necessário)
 - Vídeo: montagem com ffmpeg
Como usar:
 - Defina as variáveis de ambiente necessárias (ver README abaixo)
 - Instale dependências listadas em REQUIREMENTS
"""

import os
import re
import io
import time
import json
import tempfile
import subprocess
import shlex
from typing import List, Optional, Tuple

import streamlit as st
from PIL import Image, ImageDraw, ImageFont

# -----------------------
# REQUIREMENTS (instalar via pip)
# -----------------------
# streamlit pillow pyttsx3 pydub requests google-generativeai openai
# ffmpeg no PATH (instalar via apt/brew/choco)
#
# Exemplo:
# pip install streamlit pillow pyttsx3 pydub requests google-generativeai

st.set_page_config(page_title="Studio Jhonata — Automação Litúrgica", layout="wide")

# -----------------------
# Helpers de sistema
# -----------------------
def run_cmd(cmd: List[str], timeout: int = 300) -> Tuple[int, str]:
    """Executa comando subprocess e retorna (code, stdout)."""
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        stdout, _ = proc.communicate(timeout=timeout)
        return proc.returncode, stdout
    except subprocess.TimeoutExpired:
        proc.kill()
        return -1, "timeout"
    except Exception as e:
        return -1, str(e)

def check_ffmpeg() -> bool:
    code, _ = run_cmd(["ffmpeg", "-version"])
    return code == 0

def sanitize_filename(name: str) -> str:
    """Sanitiza texto para usar em nome de arquivo."""
    name = name.strip()
    if not name:
        name = "file"
    # remove chars problemáticos
    name = re.sub(r"[^\w\-_\. ]", "_", name)
    name = name[:120]
    return name

# -----------------------
# 1) BUSCAR ROTEIRO (Groq -> Railway fallback)
# -----------------------
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
RAILWAY_TEXT_ENDPOINT = os.environ.get("RAILWAY_TEXT_ENDPOINT")  # ex: https://api-yourproject.up.railway.app/roteiro

def fetch_script_from_groq(prompt: str) -> str:
    """
    Tenta usar cliente Groq (se disponível). Se não existir ou falhar, lança Exception.
    O usuário disse que está usando Groq para texto — aqui tentamos chamar o cliente se instalado.
    """
    try:
        # Import dinâmico para não falhar se não instalado
        import groq  # substitua se o nome do pacote no pip for outro
        # ADAPTAR: abaixo é pseudocódigo; ajuste conforme o client real que você tem.
        client = groq.Client(api_key=GROQ_API_KEY) if GROQ_API_KEY else groq.Client()
        # A forma exata de chamadas depende do cliente groq do pip que você instalou.
        # Exemplo fictício:
        resp = client.query(prompt)
        # convert result to text (adaptar conforme estrutura)
        if isinstance(resp, dict):
            return resp.get("text") or json.dumps(resp)
        return str(resp)
    except ModuleNotFoundError:
        raise RuntimeError("Cliente 'groq' não instalado no ambiente.")
    except Exception as e:
        raise RuntimeError(f"Falha ao consultar Groq: {e}")

def fetch_script_from_railway(prompt: str) -> str:
    """
    Chama endpoint Railway que você hospedou para retornar roteiro.
    Deve aceitar POST JSON { "prompt": "<texto>" } e retornar JSON { "script": "..." }
    """
    import requests
    endpoint = RAILWAY_TEXT_ENDPOINT
    if not endpoint:
        raise RuntimeError("RAILWAY_TEXT_ENDPOINT não configurado. Defina a variável de ambiente.")
    try:
        resp = requests.post(endpoint, json={"prompt": prompt}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        # Accept several possible keys
        script = data.get("script") or data.get("text") or data.get("roteiro") or data.get("result") or ""
        if not script:
            # if response is plain text
            if isinstance(data, str):
                script = data
        return script
    except Exception as e:
        raise RuntimeError(f"Falha ao consultar Railway: {e}")

def fetch_script(prompt: str) -> str:
    """
    Função principal para buscar roteiro: tenta Groq primeiro (se disponível),
    depois Railway. Se tudo falhar, retorna um roteiro de fallback simples.
    """
    # Try Groq if GROQ_API_KEY present or module installed
    try:
        return fetch_script_from_groq(prompt)
    except Exception as e_groq:
        st.warning(f"Groq indisponível ou falhou: {e_groq}")
        # fallback railway
        try:
            return fetch_script_from_railway(prompt)
        except Exception as e_rail:
            st.warning(f"Railway fallback falhou: {e_rail}")
            st.info("Usando roteiro de fallback local.")
            # fallback simple script
            sample = (
                "Título: A Jornada do Espaço\n\n"
                "Cena 1: Visão ampla do cosmos. Narração: 'No silêncio do infinito, surge uma história.'\n"
                "Cena 2: Aproximação em um buraco negro. Narração: 'Lá onde o tempo dobra...'\n"
                "Cena 3: Encerramento com créditos."
            )
            return sample

# -----------------------
# 2) GERAÇÃO DE IMAGENS — ImageFX (Google)
# -----------------------
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")

def gerar_imagem_imagefx_with_lib(prompt: str, output_path: str, size: str = "1024x1024") -> str:
    """
    Tenta usar google.generativeai (genai). Se não disponível, lança.
    Garante que textos nas imagens estejam em Português do Brasil.
    """
    if not GOOGLE_API_KEY:
        raise RuntimeError("GOOGLE_API_KEY não configurada no ambiente.")
    if not prompt or not prompt.strip():
        raise RuntimeError("Prompt vazio para gerar imagem.")

    try:
        import google.generativeai as genai
    except Exception as e:
        raise RuntimeError(f"Biblioteca 'google.generativeai' não disponível: {e}")

    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        # Use model image-generation-001
        model = genai.ImageGenerationModel("image-generation-001")
        prompt_pt = (
            "Por favor, gere uma imagem altamente detalhada a partir da descrição abaixo. "
            "Se houver qualquer texto exibido dentro da imagem, garanta que esteja em Português do Brasil, "
            "com ortografia correta e sem abreviações. Não inclua marcas registradas. Descrição: "
            + prompt
        )
        result = model.generate_image(prompt=prompt_pt, size=size)
        # Algumas versões retornam bytes; outras podem retornar base64 em result.images[0]
        # Tentar lidar com ambas estruturas:
        # result.images[0] pode ser bytes ou um objeto com .b64_json
        image_bytes = None
        if hasattr(result, "images") and result.images:
            # result.images[0] pode ser bytes
            first = result.images[0]
            if isinstance(first, (bytes, bytearray)):
                image_bytes = bytes(first)
            elif isinstance(first, str):
                # possivelmente base64 string
                import base64
                try:
                    image_bytes = base64.b64decode(first)
                except Exception:
                    image_bytes = first.encode("utf-8")
            elif hasattr(first, "b64_json"):
                import base64
                image_bytes = base64.b64decode(first.b64_json)
            else:
                # try to convert repr
                image_bytes = bytes(first)
        else:
            raise RuntimeError("Resposta inesperada do ImageFX: sem imagens retornadas.")

        with open(output_path, "wb") as f:
            f.write(image_bytes)
        return output_path
    except Exception as e:
        raise RuntimeError(f"Erro ImageFX (lib): {e}")

def gerar_imagem_imagefx_with_http(prompt: str, output_path: str, size: str = "1024x1024") -> str:
    """
    Fallback: chama endpoint HTTP do ImageFX para gerar imagem.
    Endpoint: https://generativelanguage.googleapis.com/v1beta/models/image-generation-001:generateImage?key=API_KEY
    """
    import requests, base64
    if not GOOGLE_API_KEY:
        raise RuntimeError("GOOGLE_API_KEY não configurada no ambiente.")
    if not prompt or not prompt.strip():
        raise RuntimeError("Prompt vazio para gerar imagem.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/image-generation-001:generateImage?key={GOOGLE_API_KEY}"
    prompt_pt = {
        "prompt": {
            "text": (
                "Gere uma imagem detalhada para a descrição a seguir. "
                "Se houver texto dentro da imagem, coloque em Português do Brasil e revise ortografia. "
                + prompt
            )
        },
        "image_format": "PNG",
        "size": size
    }
    try:
        resp = requests.post(url, json=prompt_pt, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        # Estrutura típica: data['result']['images'][0]['image'] base64
        image_b64 = None
        # verificar várias possibilidades
        if "images" in data:
            # older formats
            img_entry = data["images"][0]
            if isinstance(img_entry, dict) and "image" in img_entry:
                image_b64 = img_entry["image"]
            elif isinstance(img_entry, str):
                image_b64 = img_entry
        elif "result" in data and "images" in data["result"]:
            image_b64 = data["result"]["images"][0].get("image")
        # fallback common keys
        if not image_b64:
            # inspect raw output
            # tentar encontrar qualquer string base64
            text = json.dumps(data)
            m = re.search(r"data:image/[^;]+;base64,([A-Za-z0-9+/=]+)", text)
            if m:
                image_b64 = m.group(1)
        if not image_b64:
            raise RuntimeError(f"Resposta ImageFX inesperada: {data}")

        image_bytes = base64.b64decode(image_b64)
        with open(output_path, "wb") as f:
            f.write(image_bytes)
        return output_path
    except Exception as e:
        raise RuntimeError(f"Erro ImageFX (HTTP): {e}")

def gerar_imagem_imagefx(prompt: str, output_path: str, size: str = "1024x1024") -> str:
    """
    Wrapper: tenta com lib genai, senão tenta via HTTP. Lança RuntimeError em caso de falha.
    """
    # Tenta com lib
    try:
        return gerar_imagem_imagefx_with_lib(prompt, output_path, size=size)
    except Exception as e_lib:
        st.info(f"ImageFX (lib) falhou: {e_lib}. Tentando via HTTP...")
        try:
            return gerar_imagem_imagefx_with_http(prompt, output_path, size=size)
        except Exception as e_http:
            raise RuntimeError(f"Falha ImageFX (lib e HTTP): lib={e_lib} | http={e_http}")

# -----------------------
# 3) TTS OFFLINE (pyttsx3) -> gera WAV, converte para MP3 se pedido
# -----------------------
def tts_generate_offline(text: str, outfile_wav: str, rate: int = 150, voice_name_contains: Optional[str] = None) -> str:
    """Gera arquivo WAV com pyttsx3. Retorna caminho do WAV."""
    try:
        import pyttsx3
    except Exception as e:
        raise RuntimeError("pyttsx3 não instalado. pip install pyttsx3") from e

    engine = pyttsx3.init()
    try:
        engine.setProperty("rate", rate)
    except Exception:
        pass

    if voice_name_contains:
        try:
            voices = engine.getProperty("voices")
            for v in voices:
                if voice_name_contains.lower() in v.name.lower() or voice_name_contains.lower() in v.id.lower():
                    engine.setProperty("voice", v.id)
                    break
        except Exception:
            pass

    # save to file
    engine.save_to_file(text, outfile_wav)
    engine.runAndWait()
    time.sleep(0.4)
    if not os.path.exists(outfile_wav):
        raise RuntimeError("Falha ao gerar arquivo WAV com pyttsx3.")
    return outfile_wav

def convert_audio_to_mp3(input_path: str, output_path: str) -> str:
    """Converte wav -> mp3 usando ffmpeg quando disponível, senão usa pydub."""
    if check_ffmpeg():
        code, out = run_cmd(["ffmpeg", "-y", "-i", input_path, "-vn", "-ar", "44100", "-ac", "2", "-b:a", "192k", output_path])
        if code != 0:
            raise RuntimeError(f"ffmpeg falhou na conversão: {out}")
        return output_path
    else:
        try:
            from pydub import AudioSegment
            seg = AudioSegment.from_file(input_path)
            seg.export(output_path, format="mp3")
            return output_path
        except Exception as e:
            raise RuntimeError(f"Não foi possível converter áudio (ffmpeg ausente e pydub falhou): {e}")

# -----------------------
# 4) MONTAGEM DE VÍDEO (ffmpeg)
# -----------------------
def create_video_from_images_and_audio(images_paths: List[str], audio_path: str, output_path: str, resolution: str = "1280x720") -> str:
    """
    Monta um vídeo concatenando clipes gerados a partir de cada imagem (duração proporcional ao áudio).
    """
    if not check_ffmpeg():
        raise RuntimeError("ffmpeg não encontrado no PATH. Instale ffmpeg para montar o vídeo.")

    tmpdir = tempfile.mkdtemp(prefix="sj_vid_")
    try:
        # obter duração do áudio
        code, out = run_cmd(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", audio_path])
        audio_dur = None
        if code == 0:
            try:
                audio_dur = float(out.strip())
            except Exception:
                audio_dur = None

        if not audio_dur:
            audio_dur = max(1.0, len(images_paths) * 2.0)

        per_img_seconds = max(0.8, audio_dur / max(1, len(images_paths)))

        prepared = []
        concat_txt = os.path.join(tmpdir, "concat.txt")
        for i, img in enumerate(images_paths):
            # Create a clip from the image
            img_vid = os.path.join(tmpdir, f"img_{i}.mp4")
            cmd = [
                "ffmpeg", "-y",
                "-loop", "1",
                "-i", img,
                "-c:v", "libx264",
                "-t", str(per_img_seconds),
                "-pix_fmt", "yuv420p",
                "-vf", f"scale={resolution}",
                "-r", "25",
                img_vid
            ]
            code, out = run_cmd(cmd, timeout=120)
            if code != 0:
                raise RuntimeError(f"ffmpeg falhou ao criar clipe de imagem: {out}")
            prepared.append(img_vid)

        # gerar arquivo concat
        with open(concat_txt, "w", encoding="utf-8") as f:
            for p in prepared:
                f.write(f"file '{p}'\n")

        video_no_audio = os.path.join(tmpdir, "video_no_audio.mp4")
        code, out = run_cmd(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_txt, "-c", "copy", video_no_audio])
        if code != 0:
            raise RuntimeError(f"ffmpeg falhou ao concatenar clipes: {out}")

        # juntar audio
        code, out = run_cmd(["ffmpeg", "-y", "-i", video_no_audio, "-i", audio_path, "-c:v", "copy", "-c:a", "aac", "-shortest", output_path], timeout=120)
        if code != 0:
            raise RuntimeError(f"ffmpeg falhou ao juntar audio: {out}")

        return output_path
    finally:
        # Não removemos temporários automaticamente para facilitar debug.
        pass

# -----------------------
# 5) UI STREAMLIT
# -----------------------
st.title("🎬 Studio Jhonata — Automação Litúrgica")
st.sidebar.header("Configurações rápidas")

# Config options
use_groq_checkbox = st.sidebar.checkbox("Usar Groq para texto (se configurado)", value=True)
use_railway_checkbox = st.sidebar.checkbox("Usar Railway fallback (RAILWAY_TEXT_ENDPOINT)", value=True)
openai_images_checkbox = st.sidebar.checkbox("Gerar imagens com ImageFX (Google)", value=True)
tts_offline_checkbox = st.sidebar.checkbox("Usar TTS offline (pyttsx3)", value=True)

voice_name_contains = st.sidebar.text_input("Selecionar voz contendo (pyttsx3, opcional)", value="")
audio_rate = st.sidebar.slider("Velocidade fala (words/min)", 100, 200, 150)
video_resolution = st.sidebar.selectbox("Resolução final", ["1280x720", "1920x1080"], index=0)

st.header("Entrada — Liturgia / Prompt")
col_date, col_action = st.columns([2, 1])
with col_date:
    liturgia_date = st.date_input("Data da liturgia", value=None)
with col_action:
    generate_script_btn = st.button("📖 Gerar Roteiro (Groq / Railway)")

prompt_text = st.text_area("Prompt / descrição (use para orientar geração de roteiro e imagens)", height=140)

# State: script
if "script_text" not in st.session_state:
    st.session_state["script_text"] = ""

# Generate script
if generate_script_btn:
    st.info("Solicitando roteiro...")
    try:
        if use_groq_checkbox:
            script = ""
            try:
                script = fetch_script(prompt_text or f"Roteiro para liturgia de {liturgia_date}")
            except Exception as e:
                st.warning(f"Groq/Railway falhou: {e}. Usando fallback interno.")
                script = fetch_script("")  # fallback interno
        else:
            if use_railway_checkbox:
                try:
                    script = fetch_script_from_railway(prompt_text or f"Roteiro para liturgia {liturgia_date}")
                except Exception as e:
                    st.warning(f"Railway falhou: {e}")
                    script = fetch_script("")  # fallback
            else:
                script = fetch_script("")  # fallback
        st.session_state["script_text"] = script
        st.success("Roteiro gerado/obtido.")
    except Exception as e:
        st.error(f"Erro ao gerar roteiro: {e}")

st.subheader("Roteiro (edite se quiser)")
script_text_area = st.text_area("Roteiro final (texto que será narrado)", value=st.session_state.get("script_text", ""), height=240)
st.session_state["script_text"] = script_text_area

# Split into blocks
st.header("Mapeamento de blocos e imagens")
n_blocks = st.number_input("Dividir roteiro em quantos blocos (cada bloco terá 1+ imagens)", min_value=1, max_value=20, value=3)
# naive split: por parágrafos ou sentenças
def split_into_blocks(text: str, n: int) -> List[str]:
    parts = [p.strip() for p in text.strip().split("\n\n") if p.strip()]
    if len(parts) < n:
        sents = re.split(r'(?<=[.!?])\s+', text.strip())
        import math
        chunk_size = max(1, math.ceil(len(sents) / n)) if sents else 1
        parts = [" ".join(sents[i:i+chunk_size]) for i in range(0, len(sents), chunk_size)]
    if len(parts) < n:
        parts += [""] * (n - len(parts))
    return parts[:n]

blocks = split_into_blocks(st.session_state.get("script_text", ""), n_blocks)
blocks_edits = []
for i in range(n_blocks):
    blocks_edits.append(st.text_area(f"Bloco {i+1}", value=blocks[i] if i < len(blocks) else "", height=80, key=f"block_{i}"))

st.subheader("Imagens (upload opcional) e geração")
uploaded = st.file_uploader("Faça upload de imagens (opcional) — manter ordem", accept_multiple_files=True, type=["png", "jpg", "jpeg"])
uploaded_paths = []
if uploaded:
    for f in uploaded:
        tf = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(f.name)[1])
        tf.write(f.getbuffer())
        tf.flush()
        uploaded_paths.append(tf.name)

image_prompt_override = st.text_input("Prompt geral para geração de imagens (deixe vazio para usar texto de cada bloco)")
num_images_per_block = st.slider("Imagens por bloco (quando gerando)", 1, 4, 1)

st.markdown("---")
st.header("Áudio & Vídeo")
audio_format = st.selectbox("Formato de áudio gerado", ["mp3", "wav"], index=0)
btn_generate_audio = st.button("🔊 Gerar Áudio TTS (para todos blocos)")
btn_generate_images = st.button("🖼️ Gerar Imagens (ImageFX)")
btn_assemble_video = st.button("🎬 Montar Vídeo Final (imagens + áudio)")

# storage for generated files
if "generated_images" not in st.session_state:
    st.session_state["generated_images"] = []  # list of image paths
if "generated_audio" not in st.session_state:
    st.session_state["generated_audio"] = []  # list of audio paths

# Generate images per block
if btn_generate_images:
    st.info("Gerando imagens por bloco (ImageFX)...")
    temp_images = []
    try:
        # If user uploaded images, use them first (one per block if count matches)
        if uploaded_paths and len(uploaded_paths) >= n_blocks:
            st.info("Usando imagens feitas upload (uma por bloco).")
            # map first n_blocks uploaded to blocks
            for i in range(n_blocks):
                temp_images.append(uploaded_paths[i])
        else:
            # generate images for each block
            temp_dir = tempfile.mkdtemp(prefix="sj_images_")
            for i, txt in enumerate(blocks_edits):
                prompt_for_image = (image_prompt_override.strip() or txt.strip() or f"Ilustração para bloco {i+1} da liturgia.")
                for j in range(num_images_per_block):
                    safe_name = sanitize_filename(f"bloco_{i}_{j}")
                    out_path = os.path.join(temp_dir, f"{safe_name}.png")
                    try:
                        gerar_imagem_imagefx(prompt_for_image, out_path, size="1024x1024")
                        temp_images.append(out_path)
                        st.success(f"Imagem gerada: {out_path}")
                    except Exception as e:
                        st.error(f"Erro gerando imagem para bloco {i} (tentativa {j+1}): {e}")
                        # continuar tentando com próximo bloco
            if not temp_images:
                st.warning("Nenhuma imagem gerada. Verifique GOOGLE_API_KEY e logs.")
        st.session_state["generated_images"] = temp_images
    except Exception as e:
        st.error(f"Erro no processo de geração de imagens: {e}")

# Generate audio for each block
if btn_generate_audio:
    st.info("Gerando áudio TTS para cada bloco...")
    aud_paths = []
    temp_dir_audio = tempfile.mkdtemp(prefix="sj_audio_")
    for i, txt in enumerate(blocks_edits):
        if not txt or not txt.strip():
            st.warning(f"Bloco {i+1} vazio — pulando.")
            continue
        safe_name = sanitize_filename(f"block_{i}")
        wav_path = os.path.join(temp_dir_audio, f"{safe_name}.wav")
        try:
            tts_generate_offline(txt, wav_path, rate=audio_rate, voice_name_contains=(voice_name_contains or None))
            if audio_format == "mp3":
                mp3_path = os.path.join(temp_dir_audio, f"{safe_name}.mp3")
                convert_audio_to_mp3(wav_path, mp3_path)
                aud_paths.append(mp3_path)
                st.success(f"Áudio bloco {i+1} -> {mp3_path}")
            else:
                aud_paths.append(wav_path)
                st.success(f"Áudio bloco {i+1} -> {wav_path}")
        except Exception as e:
            st.error(f"Falha TTS bloco {i+1}: {e}")
    st.session_state["generated_audio"] = aud_paths

# Assemble video
if btn_assemble_video:
    st.info("Montando vídeo final...")
    try:
        images_for_video = st.session_state.get("generated_images", []) or uploaded_paths
        auds = st.session_state.get("generated_audio", [])
        if not images_for_video:
            # criar imagens simples com texto dos blocos
            st.info("Sem imagens: criando imagens simples de fundo com texto.")
            tmp_img_dir = tempfile.mkdtemp(prefix="sj_auto_img_")
            for i, txt in enumerate(blocks_edits):
                im = Image.new("RGB", (1280, 720), color=(12, 12, 12))
                draw = ImageDraw.Draw(im)
                try:
                    font = ImageFont.truetype("DejaVuSans.ttf", 28)
                except Exception:
                    font = ImageFont.load_default()
                wrapped = "\n".join(re.sub(r'\s+', ' ', txt).strip() and txt[i:i+800] for i in range(0, len(txt or ""), 800)) if txt else f"Bloco {i+1}"
                draw.multiline_text((60, 60), txt or f"Bloco {i+1}", font=font, fill=(230, 230, 230))
                p = os.path.join(tmp_img_dir, f"auto_{i}.png")
                im.save(p)
                images_for_video.append(p)

        if not auds:
            # criar áudio silencioso na duração estimada
            st.info("Sem áudio gerado: criando áudio silencioso.")
            duration = max(1.0, len(images_for_video) * 2.0)
            silent_path = os.path.join(tempfile.gettempdir(), f"silent_{int(time.time())}.wav")
            if check_ffmpeg():
                code, out = run_cmd(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100", "-t", str(duration), silent_path])
                if code != 0:
                    raise RuntimeError(f"ffmpeg falhou ao criar silêncio: {out}")
            else:
                raise RuntimeError("ffmpeg ausente para criar arquivo de áudio silencioso.")
            final_audio = silent_path
        else:
            # concatenar audios em um só
            if len(auds) == 1:
                final_audio = auds[0]
            else:
                list_txt = os.path.join(tempfile.gettempdir(), f"list_{int(time.time())}.txt")
                with open(list_txt, "w", encoding="utf-8") as f:
                    for p in auds:
                        f.write(f"file '{p}'\n")
                concat_audio = os.path.join(tempfile.gettempdir(), f"concat_{int(time.time())}.mp3")
                code, out = run_cmd(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_txt, "-c", "copy", concat_audio])
                if code != 0:
                    # fallback com pydub
                    try:
                        from pydub import AudioSegment
                        combined = None
                        for p in auds:
                            seg = AudioSegment.from_file(p)
                            combined = seg if combined is None else combined + seg
                        combined.export(concat_audio, format="mp3")
                    except Exception as e:
                        raise RuntimeError(f"Falha ao concatenar audios: {e}")
                final_audio = concat_audio

        # criar vídeo
        out_mp4 = os.path.join(tempfile.gettempdir(), f"studio_jhonata_{int(time.time())}.mp4")
        create_video_from_images_and_audio(images_for_video, final_audio, out_mp4, resolution=video_resolution)
        st.success(f"Vídeo criado: {out_mp4}")
        with open(out_mp4, "rb") as f:
            video_bytes = f.read()
            st.video(video_bytes)
            st.download_button("Download do vídeo (.mp4)", data=video_bytes, file_name=os.path.basename(out_mp4), mime="video/mp4")

    except Exception as e:
        st.error(f"Falha ao montar vídeo: {e}")

st.markdown("---")
st.header("Logs, dicas e variáveis de ambiente")
st.markdown("""
- Variáveis de ambiente úteis:
  - GROQ_API_KEY (opcional, se usar cliente groq)
  - RAILWAY_TEXT_ENDPOINT (obrigatório se quiser usar Railway fallback; ex: https://.../roteiro)
  - GOOGLE_API_KEY (obrigatório para ImageFX / Image Generation)
  - ELEVENLABS_API_KEY (opcional, se substituir TTS)
- Instale ffmpeg no PATH (necessário para montagem de vídeo e conversões).
- Se ocorrerem erros 400/401 ao ImageFX, verifique GOOGLE_API_KEY e permissões do projeto Google Cloud.
""")

st.code("""
REQUIREMENTS:
streamlit
pillow
pyttsx3
pydub
requests
google-generativeai
# opcional: groq client se disponível no pip
# ffmpeg no PATH (instalar via apt/brew/choco)
""")
