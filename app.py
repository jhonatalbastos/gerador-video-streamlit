import streamlit as st
import json
import os
import tempfile
import numpy as np
from PIL import Image, ImageDraw
from google import genai
from moviepy.editor import ImageClip, AudioFileClip, concatenate_audioclips, concatenate_videoclips, TextClip
from edge_tts import communicate # Biblioteca para Text-to-Speech

# =========================================================================
# 1. FUNÇÕES DE GERAÇÃO (IA E TTS)
# =========================================================================

@st.cache_data
def create_placeholder_image(scene_id, text, width=1280, height=720):
    """
    Cria uma imagem de placeholder colorida no diretório temporário
    para simular o asset de imagem gerado por IA.
    """
    try:
        # Cria uma imagem colorida baseada no ID da cena
        color = (100 + scene_id * 20) % 255
        img = Image.new('RGB', (width, height), (color, 50, 80))
        draw = ImageDraw.Draw(img)

        # Adiciona o texto da cena
        font_color = (255, 255, 255)
        text_to_display = f"CENA {scene_id}\n\n{text}"
        
        # Simplesmente desenha o texto (o Streamlit não lida bem com fontes complexas aqui)
        draw.text((50, 50), text_to_display, font=font_color) 

        # Salva o arquivo temporariamente
        temp_img_path = os.path.join(tempfile.gettempdir(), f"cena_{scene_id}.png")
        img.save(temp_img_path)
        return temp_img_path
    except Exception as e:
        st.error(f"Erro ao criar imagem placeholder: {e}")
        return None


def generate_tts_audio(scene_id, text_narration, voice="pt-BR-FranciscaNeural"):
    """
    Gera o arquivo de áudio (narração) usando Edge-TTS e retorna o caminho e a duração.
    """
    temp_audio_path = os.path.join(tempfile.gettempdir(), f"audio_cena_{scene_id}.mp3")
    
    try:
        # Cria o comunicador TTS
        comm = communicate(text_narration, voice)
        
        # Salva o áudio no arquivo temporário
        with open(temp_audio_path, "wb") as file:
            for chunk in comm:
                if chunk[0] == 2:
                    file.write(chunk[1])
        
        # Usa o MoviePy para determinar a duração exata do áudio
        audio_clip = AudioFileClip(temp_audio_path)
        duration = audio_clip.duration
        audio_clip.close() 

        return temp_audio_path, duration
    
    except Exception as e:
        st.error(f"Erro ao gerar áudio TTS: {e}")
        return None, 0.0


def generate_script_and_prompts(idea_central, gemini_api_key):
    """
    Usa a API do Gemini para gerar um roteiro estruturado no formato JSON.
    """
    
    # 1. Configuração da API
    # O Streamlit acessa a chave de forma segura
    try:
        client = genai.Client(api_key=gemini_api_key)
    except Exception as e:
        st.error(f"Erro de inicialização da API Gemini: {e}. Verifique a chave em 'st.secrets'.")
        return {"error": "Falha na inicialização da API."}


    # 2. PROMPT DE ENGENHARIA (O coração da automação)
    prompt_instruction = f"""
    Você é um roteirista profissional de vídeos curtos (YouTube Shorts) no estilo "Motivacional" ou "Curiosidades".
    O vídeo final deve ter no máximo 45 segundos.

    A IDEIA CENTRAL do vídeo é: "{idea_central}".

    Sua resposta deve ser estruturada em 3 a 5 Cenas, seguindo o FORMATO JSON estrito.
    Não adicione texto introdutório, explicações ou qualquer conteúdo fora do JSON.

    Para cada cena, gere TRÊS campos:
    1. "texto_narração": O texto exato (curto e envolvente) que será falado.
    2. "duracao_segundos": O tempo de duração exato em segundos (entre 3.0 e 10.0) para esta cena.
    3. "prompt_imagem_ingles": Um prompt em INGLÊS, altamente descritivo e pronto para ser usado em um gerador de Imagens por IA (ex: Midjourney ou Stable Diffusion). O prompt deve ser ultra-realista e esteticamente agradável, e refletir exatamente o texto de narração.

    EXEMPLO DO FORMATO JSON (Use este modelo exatamente):

    {{
      "titulo_sugerido": "Título chamativo aqui.",
      "cenas": [
        {{
          "id": 1,
          "texto_narração": "A jornada de mil milhas começa com um único passo.",
          "duracao_segundos": 4.5,
          "prompt_imagem_ingles": "Cinematic shot of a lone traveler standing on a misty mountain path at sunrise, deep focus, epic, 8k, photorealistic."
        }}
        // ...
      ]
    }}
    """
    
    # 3. Chamada à API
    try:
        with st.spinner('Gerando roteiro estruturado com Gemini...'):
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt_instruction,
                config={"response_mime_type": "application/json"}
            )
        
        # 4. Retorno
        return json.loads(response.text)
        
    except Exception as e:
        st.error(f"Erro na API do Gemini. Verifique se a chave está correta ou o limite de uso foi atingido: {e}")
        return {"error": "Falha na geração do roteiro."}


# =========================================================================
# 2. INTERFACE STREAMLIT
# =========================================================================

def main():
    st.set_page_config(page_title="Video Maestro AI", layout="centered")
    st.title("🎬 Video Maestro AI (Streamlit + Gemini + MoviePy)")
    st.markdown("---")

    # Verifica se a chave da API Gemini está configurada nos Secrets
    gemini_api_key = st.secrets.get("GEMINI_API_KEY")

    if not gemini_api_key:
        st.warning("⚠️ Chave GEMINI_API_KEY não encontrada nos Streamlit Secrets. Insira sua chave para continuar.")
        # Permite a entrada manual para testes em ambiente local
        gemini_api_key = st.text_input("Insira sua chave Gemini API aqui (Apenas para testes):", type="password")
        if not gemini_api_key:
            st.stop()
            

    st.header("1. Ideia Central do Vídeo")
    idea_central = st.text_area(
        "Descreva a ideia principal do vídeo (ex: 'O futuro da inteligência artificial no mercado de trabalho', 'Três lições de grandes líderes')",
        max_chars=200,
        height=100
    )

    if st.button("🚀 Gerar e Renderizar Vídeo Automatizado"):
        if not idea_central:
            st.error("Por favor, insira uma ideia central para começar.")
            return

        # ----------------------------------------------------
        # ETAPA 1: GERAÇÃO DO ROTEIRO E BLUEPRINT (JSON)
        # ----------------------------------------------------
        st.subheader("2. Geração do Roteiro (IA)")
        script_data = generate_script_and_prompts(idea_central, gemini_api_key)

        if "error" in script_data:
            return
        
        st.success("Roteiro gerado com sucesso!")
        st.json(script_data)

        # ----------------------------------------------------
        # ETAPA 2: GERAÇÃO DE ASSETS (ÁUDIO E IMAGEM)
        # ----------------------------------------------------
        st.subheader("3. Geração de Assets e Clipes")
        
        video_clips = []
        status_placeholder = st.empty()
        
        for scene in script_data.get("cenas", []):
            scene_id = scene["id"]
            narration = scene["texto_narração"]
            
            status_placeholder.info(f"Processando Cena {scene_id}: Gerando Áudio e Imagem Placeholder...")

            # Geração de Áudio (TTS)
            audio_path, duration = generate_tts_audio(scene_id, narration)
            
            if duration == 0.0:
                 st.warning(f"Cena {scene_id} pulada devido a erro de áudio.")
                 continue

            # Geração de Imagem (Placeholder, pois não temos a API de Imagem aqui)
            # COMENTÁRIO: Aqui é onde você integraria o DALL-E/Stability AI
            image_path = create_placeholder_image(scene_id, narration)
            
            # ----------------------------------------------------
            # ETAPA 3: MONTAGEM DO CLIPE (MoviePy)
            # ----------------------------------------------------
            
            # 3.1. Clipe de Áudio
            audio_clip = AudioFileClip(audio_path)
            
            # 3.2. Clipe de Imagem (ajusta a duração para o áudio)
            image_clip = ImageClip(image_path, duration=duration)
            
            # 3.3. Sincronização e Adição de Texto Simples (Legenda)
            # Adiciona o texto da narração como legenda simples no centro
            text_clip = TextClip(
                narration, 
                fontsize=40, 
                color='yellow', 
                bg_color='black', 
                size=image_clip.size
            ).set_duration(duration)
            
            final_scene = image_clip.set_audio(audio_clip)
            
            # Combina a imagem com a legenda (posicionamento central, 80% do topo)
            final_scene = final_scene.set_duration(duration)
            
            # Se for adicionar texto como overlay:
            final_scene = final_scene.set_duration(duration).set_overlay(
                text_clip.set_pos(("center", 0.8), relative=True).margin(bottom=15, opacity=0.8)
            )

            video_clips.append(final_scene)
        
        status_placeholder.empty()
        
        # ----------------------------------------------------
        # ETAPA 4: RENDERIZAÇÃO FINAL
        # ----------------------------------------------------
        st.subheader("4. Renderização do Vídeo Final")

        if not video_clips:
            st.error("Nenhum clipe foi gerado para renderizar.")
            return

        final_video_path = os.path.join(tempfile.gettempdir(), "video_final.mp4")
        
        with st.spinner('⏳ Concatenando e Renderizando... Isso pode levar de 1 a 3 minutos dependendo do tamanho do vídeo.'):
            # Concatena todos os clipes de vídeo em sequência
            final_clip = concatenate_videoclips(video_clips)
            
            # Renderiza o vídeo final
            final_clip.write_videofile(
                final_video_path, 
                codec='libx264', 
                audio_codec='aac', 
                fps=24, 
                verbose=False, 
                logger=None
            )
            
        st.success("✅ Vídeo Finalizado!")
        
        # ----------------------------------------------------
        # ETAPA 5: DOWNLOAD
        # ----------------------------------------------------
        
        # Exibe o player de vídeo
        st.video(final_video_path)
        
        # Oferece o arquivo para download
        with open(final_video_path, "rb") as file:
            st.download_button(
                label="⬇️ Baixar Vídeo MP4",
                data=file,
                file_name="video_automatizado.mp4",
                mime="video/mp4"
            )

if __name__ == "__main__":
    # Garante que o diretório temporário exista
    os.makedirs(tempfile.gettempdir(), exist_ok=True)
    main()
