# image_engine.py — geração de imagens via Gemini (generateContent)
import os
import base64
import requests
from io import BytesIO

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")  # ou configure via streamlit secrets

def gerar_imagem_gemini(prompt: str, size: str = "1024x1024") -> BytesIO:
    """
    Gera e retorna BytesIO com PNG.
    """
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY ausente.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": f"Create a {size} cinematic liturgical image: {prompt}"}
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "image/png"
        }
    }

    r = requests.post(url, json=payload, timeout=120)
    r.raise_for_status()
    data = r.json()

    try:
        b64 = data["candidates"][0]["content"]["parts"][0]["inline_data"]["data"]
    except Exception:
        raise RuntimeError("Resposta inesperada: " + str(data))

    img_bytes = base64.b64decode(b64)
    bio = BytesIO(img_bytes)
    bio.seek(0)
    return bio
