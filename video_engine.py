# video_engine.py — monta vídeo com MoviePy
import os
import tempfile
from io import BytesIO
from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips

def montar_video(lista_imagens: list[BytesIO], audio_mp3: BytesIO, fps: int = 24) -> BytesIO:
    if not lista_imagens or not audio_mp3:
        raise ValueError("Imagens e áudio são necessários.")

    temp_dir = tempfile.mkdtemp()
    audio_path = os.path.join(temp_dir, "audio.mp3")
    with open(audio_path, "wb") as f:
        audio_mp3.seek(0)
        f.write(audio_mp3.read())

    image_paths = []
    for i, bio in enumerate(lista_imagens):
        img_path = os.path.join(temp_dir, f"img_{i}.png")
        bio.seek(0)
        with open(img_path, "wb") as f:
            f.write(bio.read())
        image_paths.append(img_path)

    audio_clip = AudioFileClip(audio_path)
    dur = audio_clip.duration or max(1.0, len(image_paths))
    dur_per = dur / len(image_paths)

    clips = []
    for p in image_paths:
        clip = ImageClip(p).set_duration(dur_per)
        clips.append(clip)

    final = concatenate_videoclips(clips, method="compose")
    final = final.set_audio(audio_clip)

    out_path = os.path.join(temp_dir, "final.mp4")
    final.write_videofile(out_path, fps=fps, codec="libx264", audio_codec="aac", verbose=False, logger=None)

    bio_out = BytesIO()
    with open(out_path, "rb") as f:
        bio_out.write(f.read())
    bio_out.seek(0)
    return bio_out
