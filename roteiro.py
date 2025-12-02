import streamlit as st
import requests
import json
import os
import re
from datetime import date
from groq import Groq

st.set_page_config(page_title="Roteirista Litúrgico Multi-Job", layout="wide")
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

def generate_script_and_identify_chars(reading_text, reading_type):
    client = get_groq_client()
    if reading_type == "1ª Leitura":
        regras = """O texto completo. 
        1. INÍCIO: 'Leitura do Livro do [Nome]' (sem caps/vers).
        2. FIM: 'Palavra do Senhor!'."""
    elif reading_type == "2ª Leitura":
        regras = """O texto completo.
        1. INÍCIO: 'Leitura da [Nome da Carta]' (sem caps/vers).
        2. FIM: 'Palavra do Senhor!'."""
    elif reading_type == "Salmo":
        regras = """O Salmo completo.
        1. INÍCIO: 'Salmo Responsorial: '.
        2. Sem números de versículos."""
    elif reading_type == "Evangelho":
        regras = """O Evangelho completo.
        1. INÍCIO: 'Proclamação do Evangelho de Jesus Cristo segundo [AUTOR]. Glória a Vós, Senhor!'.
        2. FIM: 'Palavra da Salvação. Glória a Vós, Senhor!'.
        3. NÃO duplique as frases se já existirem."""
    else: regras = "O texto bíblico fornecido, LIMPO."

    system_prompt = f"""Você é um assistente litúrgico católico.
    TAREFA: Crie um roteiro curto baseado na leitura ({reading_type}).
    ESTRUTURA (5 BLOCOS):
    1. hook (5-10s): Impactante (20-30 palavras).
    2. leitura: {regras}
    3. reflexao (20-25s): Ensinamento. INÍCIO: "Reflexão:".
    4. aplicacao (20-25s): Ação prática.
    5. oracao (15-20s): Oração. INÍCIO: "Vamos orar", "Oremos" ou "Ore comigo".
    EXTRA: Identifique PERSONAGENS (exceto Jesus/Deus).
    SAÍDA JSON: {{"roteiro": {{"hook": "...", "leitura": "...", "reflexao": "...", "aplicacao": "...", "oracao": "..."}}, "personagens_identificados": ["Nome"]}}"""
    try:
        chat = client.chat.completions.create(
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": f"Texto:\n{reading_text}"}],
            model="llama-3.3-70b-versatile", response_format={"type": "json_object"}, temperature=0.7)
        return json.loads(chat.choices[0].message.content)
    except Exception as e: st.error(f"Erro Groq: {e}"); return None

def generate_character_description(name):
    client = get_groq_client()
    prompt = f"Crie descrição visual detalhada para personagem bíblico: {name}. Foco: Rosto, cabelo, barba, roupas. ~300 chars. Realista."
    try:
        chat = client.chat.completions.create(messages=[{"role": "user", "content": prompt}], model="llama-3.3-70b-versatile", temperature=0.7)
        return chat.choices[0].message.content.strip()
    except: return "Descrição não gerada."

def build_scene_prompts(roteiro_data, identified_chars, char_db, style_choice):
    prompts = {}
    desc_jesus = char_db.get("Jesus", FIXED_CHARACTERS["Jesus"])
    desc_moderna = char_db.get("Pessoa Moderna", FIXED_CHARACTERS["Pessoa Moderna"])
    desc_biblicos = (" Characters: " + " | ".join([f"{n}: {char_db.get(n,'')}" for n in identified_chars])) if identified_chars else ""
    
    prompts["hook"] = f"Cena Bíblica Cinematográfica realista: {roteiro_data.get('hook','')}. {desc_biblicos} {style_choice}"
    prompts["leitura"] = f"Cena Bíblica Cinematográfica realista. Contexto: {roteiro_data.get('leitura','').strip()[:300]}... {desc_biblicos} {style_choice}"
    prompts["reflexao"] = f"Cena Moderna. Jesus conversando com Pessoa Moderna (café/sala). Jesus: {desc_jesus} Modern: {desc_moderna} {style_choice}"
    prompts["aplicacao"] = f"Cena Moderna. Jesus e Pessoa Moderna caminhando/ensinando. Jesus: {desc_jesus} Modern: {desc_moderna} {style_choice}"
    prompts["oracao"] = f"Cena Moderna. Jesus e Pessoa Moderna orando juntos, paz. Jesus: {desc_jesus} Modern: {desc_moderna} {style_choice}"
    return prompts

def clean_verse_numbers(text):
    if not text: return ""
    text = re.sub(r'\d{1,3}(?=[A-Za-zÀ-ÿ])', '', text)
    text = re.sub(r'\b\d{1,3}\s+(?=["\'A-Za-zÀ-ÿ])', '', text)
    text = re.sub(r'\b\d{1,3}\.\s+', '', text)
    return re.sub(r'\s+', ' ', text).strip()

def extract_text(obj):
    if not obj: return ""
    if "content_psalm" in obj:
        c = obj["content_psalm"]
        text = "\n".join(c) if isinstance(c, list) else str(c)
        return f"{obj.get('response', '')}\n{text}"
    raw = obj.get("text") or obj.get("texto") or ""
    return clean_verse_numbers(raw)

def main():
    st.sidebar.title("⚙️ Configurações")
    char_db = load_characters()
    tab_roteiro, tab_personagens = st.tabs(["📜 Roteiros", "👥 Personagens"])
    if 'daily_readings' not in st.session_state: st.session_state['daily_readings'] = []
    if 'generated_scripts' not in st.session_state: st.session_state['generated_scripts'] = []

    with tab_roteiro:
        st.header("1. Buscar Liturgia")
        date_sel = st.date_input("Data", value=date.today())
        if st.button("Buscar Leituras"):
            with st.spinner("Conectando..."):
                data = fetch_liturgia(date_sel)
                if data:
                    st.session_state['daily_readings'] = []
                    st.session_state['generated_scripts'] = []
                    today = data.get('today', {})
                    readings = today.get('readings', {}) or data.get('readings', {})
                    
                    def add(key, type_name):
                        if key in readings:
                            txt = extract_text(readings[key])
                            ref = readings[key].get('title', type_name)
                            if txt.strip(): st.session_state['daily_readings'].append({"type": type_name, "text": txt, "ref": ref, "date_display": date_sel.strftime("%d/%m/%Y")})
                    
                    add('first_reading', '1ª Leitura')
                    add('psalm', 'Salmo')
                    add('second_reading', '2ª Leitura')
                    add('gospel', 'Evangelho')
                    
                    if st.session_state['daily_readings']: st.success(f"{len(st.session_state['daily_readings'])} leituras!")
                    else: st.warning("Vazio.")

        if st.session_state['daily_readings']:
            st.divider(); st.write("📖 **Leituras (Limpas):**")
            for r in st.session_state['daily_readings']:
                with st.expander(f"{r['type']}: {r['ref']}"): st.text(r['text'])
            
            st.divider(); st.header("2. Gerar Roteiros")
            if st.button("✨ Gerar Todos"):
                st.session_state['generated_scripts'] = []
                prog = st.progress(0)
                with st.status("Gerando...", expanded=True):
                    for i, r in enumerate(st.session_state['daily_readings']):
                        st.write(f"Processando {r['type']}...")
                        res = generate_script_and_identify_chars(r['text'], r['type'])
                        if res:
                            chars = res.get('personagens_identificados', [])
                            for c in chars:
                                if c not in char_db:
                                    char_db[c] = generate_character_description(c)
                            save_characters(char_db)
                            st.session_state['generated_scripts'].append({"meta": r, "roteiro": res.get('roteiro', {}), "chars": chars})
                        prog.progress((i+1)/len(st.session_state['daily_readings']))

        if st.session_state['generated_scripts']:
            st.divider(); st.header("3. Enviar (Drive)")
            for s in st.session_state['generated_scripts']:
                m = s['meta']; r = s['roteiro']
                with st.expander(f"✅ {m['type']} - {m['ref']}"):
                    c1, c2 = st.columns(2)
                    with c1: st.info(f"Hook: {r.get('hook')}"); st.text_area("Leitura", r.get('leitura'), height=100, key=f"l_{m['type']}")
                    with c2: st.write(f"Reflexão: {r.get('reflexao')}"); st.write(f"Aplicação: {r.get('aplicacao')}"); st.write(f"Oração: {r.get('oracao')}")

            if st.button("🚀 Enviar Todos"):
                prog = st.progress(0); cnt = 0
                for i, s in enumerate(st.session_state['generated_scripts']):
                    m = s['meta']; r = s['roteiro']
                    prompts = build_scene_prompts(r, s['chars'], char_db, STYLE_SUFFIX)
                    payload = {
                        "meta_dados": {"data": m['date_display'], "ref": f"{m['type']} - {m['ref']}"},
                        "roteiro": {k: {"text": r.get(k,''), "prompt": prompts.get(k,'')} for k in ["hook", "leitura", "reflexao", "aplicacao", "oracao"]},
                        "assets": []
                    }
                    if send_to_gas(payload): cnt += 1
                    prog.progress((i+1)/len(st.session_state['generated_scripts']))
                if cnt == len(st.session_state['generated_scripts']): st.balloons(); st.success("Sucesso!")
                else: st.warning(f"{cnt} enviados.")

    with tab_personagens:
        st.header("Personagens")
        for n, d in char_db.items():
            with st.expander(n):
                new_d = st.text_area("Desc", d, key=f"d_{n}"); 
                if st.button("Salvar", key=f"s_{n}"): char_db[n]=new_d; save_characters(char_db); st.rerun()
                if n not in FIXED_CHARACTERS and st.button("Excluir", key=f"x_{n}"): del char_db[n]; save_characters(char_db); st.rerun()
        n = st.text_input("Novo Nome"); d = st.text_area("Nova Descrição")
        if st.button("Adicionar") and n: char_db[n]=d; save_characters(char_db); st.rerun()

if __name__ == "__main__": main()
