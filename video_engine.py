from moviepy.editor import *
from io import BytesIO
import tempfile

def montar_video(lista_imagens: list[BytesIO], audio_mp3: BytesIO) -> BytesIO:
    """
    Monta um vídeo MP4 com:
    - imagens (cada uma com duração igual)
    - áudio MP3 por cima
    Retorna BytesIO com o vídeo final.
    """
    # ====== salvar temporariamente ======
    temp_dir = tempfile.mkdtemp()

    audio_path = f"{temp_dir}/audio.mp3"
    with open(audio_path, "wb") as f:
        f.write(audio_mp3.read())

    imagem_paths = []
    for i, img_bytes in enumerate(lista_imagens):
        p = f"{temp_dir}/img_{i}.png"
        with open(p, "wb") as f:
            f.write(img_bytes.read())
        imagem_paths.append(p)
        img_bytes.seek(0)

    # ====== clipes de imagem ======
    duracao_audio = AudioFileClip(audio_path).duration
    duracao_por_imagem = duracao_audio / len(imagem_paths)

    clips = []
    for p in imagem_paths:
        c = ImageClip(p).set_duration(duracao_por_imagem)
        clips.append(c)

    video = concatenate_videoclips(clips, method="compose")

    # ====== adicionar áudio ======
    audio = AudioFileClip(audio_path)
    video = video.set_audio(audio)

    # ====== exportar para BytesIO ======
    output = BytesIO()
    video.write_videofile(
        f"{temp_dir}/final.mp4",
        fps=30,
        codec="libx264",
        audio_codec="aac",
        verbose=False,
        logger=None,
    )

    with open(f"{temp_dir}/final.mp4", "rb") as f:
        output.write(f.read())

    output.seek(0)
    return output
