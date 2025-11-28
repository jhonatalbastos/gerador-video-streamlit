import base64
import requests
from io import BytesIO
from PIL import Image
import os

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

def gerar_imagem(prompt: str) -> BytesIO:
    """
    Gera imagem via Gemini 1.5 Flash (ou outro modelo permitido para imagens).
    Retorna BytesIO contendo PNG.
    """
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateImage?key=" + GEMINI_API_KEY

    body = {
        "prompt": prompt,
        "size": "1024x1024"
    }

    resp = requests.post(url, json=body)
    resp.raise_for_status()

    b64_data = resp.json()["images"][0]
    img_bytes = base64.b64decode(b64_data)

    buffer = BytesIO()
    buffer.write(img_bytes)
    buffer.seek(0)

    return buffer
