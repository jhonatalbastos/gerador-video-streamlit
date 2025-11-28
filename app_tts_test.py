import google.genai as genai  # google-genai
from google.genai import types
from io import BytesIO

client = genai.Client(api_key=st.secrets["GOOGLE_AI_API_KEY"])

def gerar_audio_gemini(texto: str) -> BytesIO | None:
    if not texto.strip():
        return None

    response = client.models.generate_content(
        model="gemini-2.5-flash-preview-tts",          # modelo de TTS da Gemini [web:358]
        contents=texto,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                # aqui você ajusta voz, idioma, tom etc.
                voice_config=types.VoiceConfig(
                    language_code="pt-BR",
                    # name pode ser vazio ou um nome de voz suportado
                )
            )
        ),
    )

    # response.candidates[0].content.parts[0].inline_data.data traz o áudio em bytes [web:358]
    audio_bytes = response.candidates[0].content.parts[0].inline_data.data
    buf = BytesIO(audio_bytes)
    buf.seek(0)
    return buf
