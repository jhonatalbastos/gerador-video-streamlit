# app_tts_test.py — testa a função de Gemini TTS (para rodar localmente)
import os
from app import gerar_audio_gemini  # se estiver usando pacote; caso contrário, copie a função

def main():
    texto = "Teste de voz com Gemini TTS. Esta é uma frase de verificação."
    audio = gerar_audio_gemini(texto, voz="pt-BR-Wavenet-B")
    with open("teste_gemini.mp3", "wb") as f:
        audio.seek(0)
        f.write(audio.read())
    print("teste_gemini.mp3 salvo.")

if __name__ == "__main__":
    main()
