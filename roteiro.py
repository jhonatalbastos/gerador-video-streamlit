import streamlit as st
import requests
import json
import os
from datetime import date
from groq import Groq

# ==========================================
# CONFIGURAÇÕES E CONSTANTES
# ==========================================

st.set_page_config(page_title="Roteirista Litúrgico AI", layout="wide")

# Arquivo para "Banco de Dados" de personagens
CHARACTERS_FILE = "characters_db.json"

# Sufixo de Estilo Padrão
STYLE_SUFFIX = ". Style: Cinematic Realistic, 1080p resolution, highly detailed, masterpiece, cinematic lighting, detailed texture, photography style."

# Personagens Fixos (Sempre presentes no sistema)
FIXED_CHARACTERS = {
    "Jesus": "Homem de 33 anos, descendência do oriente médio, cabelos longos e escuros, barba, túnica branca, faixa vermelha, expressão serena.",
    "Pessoa Moderna": "Jovem adulto (homem ou mulher), roupas casuais modernas (jeans/camiseta), aparência cotidiana e identificável."
}

# ==========================================
# FUNÇÕES DE PERSISTÊNCIA (PERSONAGENS)
# ==========================================

def load_characters():
    """Carrega o banco de personagens, mesclando com os fixos."""
    if os.path.exists(CHARACTERS_FILE):
        try:
            with open(CHARACTERS_FILE, "r", encoding="utf-8") as f:
                custom_chars = json.load(f)
        except:
            custom_chars = {}
    else:
        custom_chars = {}
    
    # Garante que os fixos existam, mas dá preferência à versão salva se houver edição
    all_chars = FIXED_CHARACTERS.copy()
    all_chars.update(custom_chars)
    return all_chars

def save_characters(chars_dict):
    """Salva apenas os personagens que não são os padrões imutáveis."""
    with open(CHARACTERS_FILE, "w", encoding="utf-8") as f:
        json.dump(chars_dict, f, ensure_ascii=False, indent=2)

# ==========================================
# SERVIÇOS EXTERNOS (API, GROQ, GAS)
# ==========================================

def get_groq_client():
    # Tenta pegar dos secrets ou env var
    api_key = st.secrets.get("GROQ_API_KEY") or os.getenv("GROQ_API_KEY")
    if not api_key:
        st.error("❌ GROQ_API_KEY não encontrada nos secrets.")
        st.stop()
    return Groq(api_key=api_key)

def fetch_liturgia(date_obj):
    """Busca a liturgia na API da Vercel."""
    date_str = date_obj.strftime("%Y-%m-%d")
    url = f"[https://api-liturgia-diaria.vercel.app/?date=](https://api-liturgia-diaria.vercel.app/?date=){date_str}"
    try:
        resp = requests.get(url)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        st.error(f"Erro ao buscar liturgia: {e}")
        return None

def send_to_gas(payload):
    """Envia o payload JSON para o Google Apps Script."""
    gas_url = st.secrets.get("GAS_SCRIPT_URL") or os.getenv("GAS_SCRIPT_URL")
    if not gas_url:
        st.error("❌ GAS_SCRIPT_URL não encontrada nos secrets.")
        return None
    
    try:
        # A action 'generate_job' deve estar tratada no seu script GAS
        full_url = f"{gas_url}?action=generate_job"
        
        # Requests trata automaticamente a conversão para JSON no parâmetro 'json'
        resp = requests.post(full_url, json=payload)
        
        if resp.status_code == 200:
            return resp.json()
        else:
            st.error(f"Erro GAS ({resp.status_code}): {resp.text}")
            return None
    except Exception as e:
        st.error(f"Erro de conexão com GAS: {e}")
        return None

# ==========================================
# LÓGICA DE IA (GROQ)
# ==========================================

def generate_script_and_identify_chars(full_text_readings):
    """
    Usa o Groq para gerar roteiro e identificar personagens.
    """
    client = get_groq_client()
    
    system_prompt = """
    Você é um assistente litúrgico católico especializado em roteiros de vídeo curto.
    
    TAREFA:
    1. Analise as leituras fornecidas.
    2. Crie um roteiro dividido EXATAMENTE nestes 5 blocos:
       - hook: Uma frase impactante de 5-8s para prender a atenção.
       - leitura: O texto do Evangelho (ou leitura principal) LIMPO (sem números de versículos, sem cabeçalhos, apenas o texto falado).
       - reflexao: Um texto de 20-25s trazendo o ensinamento para hoje. Tom amigável.
       - aplicacao: Um texto de 20-25s com uma dica prática de ação baseada no texto.
       - oracao: Uma oração curta de 15-20s de encerramento.
    
    3. IDENTIFIQUE OS PERSONAGENS BÍBLICOS presentes na cena da leitura. Não inclua Jesus ou Deus nesta lista.
    
    SAÍDA ESPERADA (JSON PURO):
    {
      "roteiro": {
        "hook": "texto...",
        "leitura": "texto limpo...",
        "reflexao": "texto...",
        "aplicacao": "texto...",
        "oracao": "texto..."
      },
      "personagens_identificados": ["Nome1", "Nome2"]
    }
    """
    
    try:
        # CORREÇÃO: Usando modelo estável da Groq (llama-3.1-70b-versatile)
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"As leituras de hoje são:\n\n{full_text_readings}"}
            ],
            model="llama-3.1-70b-versatile",
            response_format={"type": "json_object"},
            temperature=0.7,
        )
        return json.loads(chat_completion.choices[0].message.content)
    except Exception as e:
        st.error(f"Erro na geração do roteiro (Groq): {e}")
        return None

def generate_character_description(name):
    """Gera descrição visual para um novo personagem."""
    client = get_groq_client()
    prompt = f"""
    Crie uma descrição visual física detalhada para o personagem bíblico: {name}.
    Foco: Rosto, cabelo, barba (se houver), roupas da época.
    Tamanho: Aproximadamente 300 caracteres.
    Estilo: Realista, histórico, cinematográfico.
    Apenas a descrição.
    """
    try:
        chat = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.1-70b-versatile", # Modelo corrigido
            temperature=0.7,
        )
        return chat.choices[0].message.content.strip()
    except:
        return "Descrição não gerada."

# ==========================================
# CONSTRUTOR DE PROMPTS
# ==========================================

def build_scene_prompts(roteiro_data, identified_chars, char_db, style_choice):
    """
    Monta os prompts de imagem seguindo estritamente as instruções.
    """
    prompts = {}
    
    desc_jesus = char_db.get("Jesus", FIXED_CHARACTERS["Jesus"])
    desc_moderna = char_db.get("Pessoa Moderna", FIXED_CHARACTERS["Pessoa Moderna"])
    
    desc_biblicos = ""
    if identified_chars:
        # Pega do DB apenas se existir, para evitar erro de chave
        desc_list = [f"{name}: {char_db.get(name, 'Trajes bíblicos genéricos')}" for name in identified_chars]
        desc_biblicos = " Characters in scene: " + " | ".join(desc_list)

    # Hook
    prompts["hook"] = (
        f"Cena Bíblica Cinematográfica realista baseada na leitura: {roteiro_data['hook']}. "
        f"{desc_biblicos} "
        f"{style_choice}"
    )

    # Leitura
    prompts["leitura"] = (
        f"Cena Bíblica Cinematográfica realista baseada na leitura do texto bíblico fornecido. "
        f"Contexto: {roteiro_data['leitura'][:300]}... "
        f"{desc_biblicos} "
        f"{style_choice}"
    )

    # Reflexão
    prompts["reflexao"] = (
        f"Cena Moderna. Jesus conversando amigavelmente com a Pessoa Moderna em um café ou sala de estar confortável. Iluminação suave. "
        f"Jesus description: {desc_jesus} "
        f"Modern Person description: {desc_moderna} "
        f"{style_choice}"
    )

    # Aplicação
    prompts["aplicacao"] = (
        f"Cena Moderna. Jesus e a Pessoa Moderna caminhando na cidade, na rua ou em um ambiente de trabalho. Jesus está apontando para algo ou ensinando algo ativamente. "
        f"Jesus description: {desc_jesus} "
        f"Modern Person description: {desc_moderna} "
        f"{style_choice}"
    )

    # Oração
    prompts["oracao"] = (
        f"Cena Moderna. Jesus e a Pessoa Moderna orando juntos (lado a lado ou frente a frente), olhos fechados, ambiente de paz profunda. "
        f"Jesus description: {desc_jesus} "
        f"Modern Person description: {desc_moderna} "
        f"{style_choice}"
    )

    return prompts

# ==========================================
# INTERFACE STREAMLIT
# ==========================================

def main():
    st.sidebar.title("⚙️ Configurações")
    
    char_db = load_characters()
    
    tab_roteiro, tab_personagens = st.tabs(["📜 Roteiro & Geração", "👥 Gerenciar Personagens"])
    
    with tab_roteiro:
        st.header("1. Buscar Liturgia")
        date_sel = st.date_input("Data", value=date.today())
        
        if st.button("Buscar Leituras"):
            with st.spinner("Conectando à Vercel..."):
                data = fetch_liturgia(date_sel)
                if data:
                    readings_text = ""
                    # Verifica a estrutura da API Vercel (às vezes muda ligeiramente, aqui tentamos pegar o máximo)
                    today_data = data.get('readings') or data
                    
                    if 'first_reading' in today_data:
                        readings_text += f"1ª Leitura: {today_data['first_reading'].get('text', '')}\n\n"
                    if 'psalm' in today_data:
                        readings_text += f"Salmo: {today_data['psalm'].get('text', '')}\n\n"
                    if 'second_reading' in today_data:
                        readings_text += f"2ª Leitura: {today_data['second_reading'].get('text', '')}\n\n"
                    if 'gospel' in today_data:
                        readings_text += f"Evangelho: {today_data['gospel'].get('text', '')}\n\n"
                    
                    st.session_state['raw_readings'] = readings_text
                    
                    # Tenta pegar referência
                    ref_title = today_data.get('gospel', {}).get('title', 'Evangelho do Dia')
                    st.session_state['liturgy_meta'] = {
                        "data": date_sel.strftime("%d/%m/%Y"),
                        "ref": ref_title
                    }
                    st.success("Leituras obtidas!")
                    with st.expander("Ver texto bruto"):
                        st.text(readings_text)

        st.markdown("---")
        st.header("2. Gerar Roteiro e Processar")
        
        if 'raw_readings' in st.session_state:
            if st.button("✨ Gerar Roteiro e Identificar Personagens"):
                with st.status("Trabalhando...", expanded=True) as status:
                    st.write("🧠 Groq: Criando roteiro e limpando texto...")
                    ai_result = generate_script_and_identify_chars(st.session_state['raw_readings'])
                    
                    if ai_result:
                        st.session_state['roteiro_data'] = ai_result.get('roteiro')
                        identified = ai_result.get('personagens_identificados', [])
                        st.session_state['identified_chars'] = identified
                        
                        st.write(f"🕵️ Personagens identificados: {', '.join(identified)}")
                        
                        new_chars_found = False
                        for char_name in identified:
                            if char_name not in char_db:
                                st.write(f"🎨 Criando visual para: {char_name}...")
                                new_desc = generate_character_description(char_name)
                                char_db[char_name] = new_desc
                                new_chars_found = True
                        
                        if new_chars_found:
                            save_characters(char_db)
                            st.write("💾 Banco de personagens atualizado.")
                        
                        status.update(label="Processo concluído!", state="complete", expanded=False)
                    else:
                        status.update(label="Falha na geração.", state="error")

        if 'roteiro_data' in st.session_state and st.session_state['roteiro_data']:
            roteiro = st.session_state['roteiro_data']
            
            st.subheader("Roteiro Gerado")
            c1, c2 = st.columns(2)
            with c1:
                st.info(f"**Hook:** {roteiro.get('hook', '')}")
                st.write(f"**Leitura:** {roteiro.get('leitura', '')[:200]}...")
                st.write(f"**Reflexão:** {roteiro.get('reflexao', '')}")
            with c2:
                st.write(f"**Aplicação:** {roteiro.get('aplicacao', '')}")
                st.write(f"**Oração:** {roteiro.get('oracao', '')}")
            
            st.markdown("---")
            st.header("3. Enviar para Produção (Drive)")
            
            if st.button("🚀 Gerar Prompts e Enviar para Drive"):
                prompts_finais = build_scene_prompts(
                    roteiro, 
                    st.session_state.get('identified_chars', []), 
                    char_db, 
                    STYLE_SUFFIX
                )
                
                payload = {
                    "meta_dados": st.session_state['liturgy_meta'],
                    "roteiro": {
                        "hook": {"text": roteiro.get('hook', ''), "prompt": prompts_finais['hook']},
                        "leitura": {"text": roteiro.get('leitura', ''), "prompt": prompts_finais['leitura']},
                        "reflexao": {"text": roteiro.get('reflexao', ''), "prompt": prompts_finais['reflexao']},
                        "aplicacao": {"text": roteiro.get('aplicacao', ''), "prompt": prompts_finais['aplicacao']},
                        "oracao": {"text": roteiro.get('oracao', ''), "prompt": prompts_finais['oracao']}
                    },
                    "assets": []
                }
                
                with st.spinner("Enviando para o Google Drive via GAS..."):
                    result = send_to_gas(payload)
                    if result and result.get('status') == 'success':
                        st.balloons()
                        st.success(f"Sucesso! Job criado: {result.get('job_id')}")
                        st.info("Agora abra o aplicativo do AI Studio para processar as mídias.")
                    else:
                        st.error("Falha no envio.")

    with tab_personagens:
        st.header("Banco de Personagens")
        st.info("Aqui você pode ajustar a aparência dos personagens para garantir consistência.")
        
        for name, desc in char_db.items():
            with st.expander(f"👤 {name}", expanded=False):
                new_desc = st.text_area(f"Descrição Visual ({name})", value=desc, height=150)
                if st.button(f"Salvar {name}"):
                    char_db[name] = new_desc
                    save_characters(char_db)
                    st.success(f"{name} atualizado!")
                
                if name not in FIXED_CHARACTERS:
                    if st.button(f"🗑️ Excluir {name}", type="primary"):
                        del char_db[name]
                        save_characters(char_db)
                        st.rerun()

        st.markdown("---")
        st.subheader("Adicionar Manualmente")
        new_name = st.text_input("Nome do Personagem")
        new_desc_manual = st.text_area("Descrição")
        if st.button("Adicionar"):
            if new_name and new_desc_manual:
                char_db[new_name] = new_desc_manual
                save_characters(char_db)
                st.success("Adicionado!")
                st.rerun()

if __name__ == "__main__":
    main()
