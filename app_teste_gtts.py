# app_teste_gtts.py — script simples local para testar gTTS (não usa Gemini)
from gtts import gTTS
from io import BytesIO

def teste_gtts(texto="Olá, teste gTTS"):
    tts = gTTS(text=texto, lang="pt", slow=False)
    with open("teste_gtts.mp3", "wb") as f:
        tts.write_to_fp(f)
    print("Arquivo teste_gtts.mp3 gerado.")

if __name__ == "__main__":
    teste_gtts("Olá, este é um teste local com gTTS.")
