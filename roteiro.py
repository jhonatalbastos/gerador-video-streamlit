import streamlit as st
import requests
import json
import os
from datetime import date
from groq import Groq

st.set_page_config(page_title="Roteirista Litúrgico AI", layout="wide")
CHARACTERS_FILE = "characters_db.json"
STYLE_SUFFIX = ". Style: Cinematic Realistic, 1080p resolution, highly detailed, masterpiece, cinematic lighting, detailed texture, photography style."
FIXED_CHARACTERS = {
    "Jesus": "Homem de 33 anos, descendência do oriente médio, cabelos longos e escuros, barba, túnica branca, faixa vermelha, expressão serena.",
    "Pessoa Moderna": "Jovem adulto (homem ou mulher), roupas casuais modernas (jeans/camiseta), aparência cotidiana e identificável."
}

def load_characters():
    if os.path.exists(CHARACTERS_FILE):
        try:
            with open(CHARACTERS_FILE, "r", encoding="utf-8") as f: custom_chars = json.load(f)
        except: custom_chars = {}
    else: custom_chars = {}
    all_chars = FIXED_CHARACTERS.copy()
    all_chars.update(custom_chars)
    return all_chars

def save_characters(chars_dict):
    with open(CHARACTERS_FILE, "w", encoding="utf-8") as f: json.dump(chars_dict, f, ensure_ascii=False, indent=2)

def get_groq_client():
    api_key = st.secrets.get("GROQ_API_KEY") or os.getenv("GROQ_API_KEY")
    if not api_key: st.error("❌ GROQ_API_KEY não encontrada."); st.stop()
    return Groq(api_key=api_key)

def fetch_liturgia(date_obj):
    date_str = date_obj.strftime("%Y-%m-%d")
    url = f"https://api-liturgia-diaria.vercel.app/?date={date_str}".strip()
    try:
        resp = requests.get(url)
        resp.raise_for_status()
        return resp.json()
    except Exception as e: st.error(f"Erro ao buscar liturgia: {e}"); return None

def send_to_gas(payload):
    gas_url = st.secrets.get("GAS_SCRIPT_URL") or os.getenv("GAS_SCRIPT_URL")
    if not gas_url: st.error("❌ GAS_SCRIPT_URL não encontrada."); return None
    try:
        full_url = f"{gas_url}?action=generate_job"
        resp = requests.post(full_url, json=payload)
        if resp.status_code == 200: return resp.json()
        else: st.error(f"Erro GAS ({resp.status_code}): {resp.text}"); return None
    except Exception as e: st.error(f"Erro de conexão com GAS: {e}"); return None

def generate_script_and_identify_chars(full_text_readings):
    client = get_groq_client()
    system_prompt = """Você é um assistente litúrgico católico especializado em roteiros de vídeo curto.
    TAREFA: 1. Analise as leituras. 2. Crie um roteiro dividido em: hook (5-8s), leitura (texto limpo), reflexao (20-25s), aplicacao (20-25s), oracao (15-20s).
    3. IDENTIFIQUE OS PERSONAGENS BÍBLICOS (exceto Jesus/Deus).
    SAÍDA JSON: {"roteiro": {"hook": "...", "leitura": "...", "reflexao": "...", "aplicacao": "...", "oracao": "..."}, "personagens_identificados": ["Nome1"]}"""
    try:
        chat_completion = client.chat.completions.create(
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": f"Leituras:\n\n{full_text_readings}"}],
            model="llama-3.3-70b-versatile", response_format={"type": "json_object"}, temperature=0.7)
        return json.loads(chat_completion.choices[0].message.content)
    except Exception as e: st.error(f"Erro na geração (Groq): {e}"); return None

def generate_character_description(name):
    client = get_groq_client()
    prompt = f"Crie descrição visual física detalhada para personagem bíblico: {name}. Foco: Rosto, cabelo, barba, roupas. ~300 chars. Realista."
    try:
        chat = client.chat.completions.create(messages=[{"role": "user", "content": prompt}], model="llama-3.3-70b-versatile", temperature=0.7)
        return chat.choices[0].message.content.strip()
    except: return "Descrição não gerada."

def build_scene_prompts(roteiro_data, identified_chars, char_db, style_choice):
    prompts = {}
    desc_jesus = char_db.get("Jesus", FIXED_CHARACTERS["Jesus"])
    desc_moderna = char_db.get("Pessoa Moderna", FIXED_CHARACTERS["Pessoa Moderna"])
    desc_biblicos = ""
    if identified_chars:
        desc_list = [f"{name}: {char_db.get(name, 'Trajes bíblicos genéricos')}" for name in identified_chars]
        desc_biblicos = " Characters in scene: " + " | ".join(desc_list)
    prompts["hook"] = f"Cena Bíblica Cinematográfica realista baseada na leitura: {roteiro_data['hook']}. {desc_biblicos} {style_choice}"
    prompts["leitura"] = f"Cena Bíblica Cinematográfica realista baseada na leitura. Contexto: {roteiro_data['leitura'][:300]}... {desc_biblicos} {style_choice}"
    prompts["reflexao"] = f"Cena Moderna. Jesus conversando amigavelmente com a Pessoa Moderna em um café ou sala de estar. Jesus description: {desc_jesus} Modern Person description: {desc_moderna} {style_choice}"
    prompts["aplicacao"] = f"Cena Moderna. Jesus e a Pessoa Moderna caminhando na cidade/trabalho. Jesus ensinando. Jesus description: {desc_jesus} Modern Person description: {desc_moderna} {style_choice}"
    prompts["oracao"] = f"Cena Moderna. Jesus e a Pessoa Moderna orando juntos, olhos fechados, paz. Jesus description: {desc_jesus} Modern Person description: {desc_moderna} {style_choice}"
    return prompts

def main():
    st.sidebar.title("⚙️ Configurações")
    char_db = load_characters()
    tab_roteiro, tab_personagens = st.tabs(["📜 Roteiro", "👥 Personagens"])
    
    with tab_roteiro:
        st.header("1. Buscar Liturgia")
        date_sel = st.date_input("Data", value=date.today())
        if st.button("Buscar Leituras"):
            with st.spinner("Conectando à Vercel..."):
                data = fetch_liturgia(date_sel)
                if data:
                    readings_text = ""
                    today_data = data.get('readings') or data
                    if 'first_reading' in today_data: readings_text += f"1ª Leitura: {today_data['first_reading'].get('text', '')}\n\n"
                    if 'psalm' in today_data: readings_text += f"Salmo: {today_data['psalm'].get('text', '')}\n\n"
                    if 'second_reading' in today_data: readings_text += f"2ª Leitura: {today_data['second_reading'].get('text', '')}\n\n"
                    if 'gospel' in today_data: readings_text += f"Evangelho: {today_data['gospel'].get('text', '')}\n\n"
                    st.session_state['raw_readings'] = readings_text
                    ref_title = today_data.get('gospel', {}).get('title', 'Evangelho do Dia')
                    st.session_state['liturgy_meta'] = {"data": date_sel.strftime("%d/%m/%Y"), "ref": ref_title}
                    st.success("Leituras obtidas!")
                    with st.expander("Ver texto"): st.text(readings_text)

        st.markdown("---"); st.header("2. Gerar Roteiro")
        if 'raw_readings' in st.session_state:
            if st.button("✨ Gerar Roteiro e Identificar"):
                with st.status("Trabalhando...", expanded=True) as status:
                    ai_result = generate_script_and_identify_chars(st.session_state['raw_readings'])
                    if ai_result:
                        st.session_state['roteiro_data'] = ai_result.get('roteiro')
                        st.session_state['identified_chars'] = ai_result.get('personagens_identificados', [])
                        new_chars_found = False
                        for char_name in st.session_state['identified_chars']:
                            if char_name not in char_db:
                                new_desc = generate_character_description(char_name)
                                char_db[char_name] = new_desc
                                new_chars_found = True
                        if new_chars_found: save_characters(char_db)
                        status.update(label="Concluído!", state="complete", expanded=False)
                    else: status.update(label="Falha.", state="error")

        if 'roteiro_data' in st.session_state and st.session_state['roteiro_data']:
            roteiro = st.session_state['roteiro_data']
            st.subheader("Roteiro Gerado")
            c1, c2 = st.columns(2)
            with c1: st.info(f"Hook: {roteiro.get('hook', '')}"); st.write(f"Leitura: {roteiro.get('leitura', '')[:100]}...")
            with c2: st.write(f"Reflexão: {roteiro.get('reflexao', '')}"); st.write(f"Aplicação: {roteiro.get('aplicacao', '')}")
            st.markdown("---"); st.header("3. Enviar (Drive)")
            if st.button("🚀 Enviar para Drive"):
                prompts_finais = build_scene_prompts(roteiro, st.session_state.get('identified_chars', []), char_db, STYLE_SUFFIX)
                payload = {
                    "meta_dados": st.session_state['liturgy_meta'],
                    "roteiro": {k: {"text": roteiro.get(k, ''), "prompt": prompts_finais[k]} for k in ["hook", "leitura", "reflexao", "aplicacao", "oracao"]},
                    "assets": []
                }
                with st.spinner("Enviando..."):
                    result = send_to_gas(payload)
                    if result and result.get('status') == 'success': st.balloons(); st.success(f"Job: {result.get('job_id')}")
                    else: st.error("Falha no envio.")

    with tab_personagens:
        st.header("Personagens")
        for name, desc in char_db.items():
            with st.expander(f"👤 {name}", expanded=False):
                new_desc = st.text_area(f"Desc ({name})", value=desc, height=100)
                if st.button(f"Salvar {name}"): char_db[name] = new_desc; save_characters(char_db); st.success("Atualizado!")
                if name not in FIXED_CHARACTERS:
                    if st.button(f"Excluir {name}"): del char_db[name]; save_characters(char_db); st.rerun()
        st.divider()
        new_name = st.text_input("Nome"); new_desc_manual = st.text_area("Descrição")
        if st.button("Adicionar") and new_name: char_db[new_name] = new_desc_manual; save_characters(char_db); st.success("Adicionado!"); st.rerun()

if __name__ == "__main__": main()
