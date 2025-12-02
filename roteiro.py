import streamlit as st
import requests
import json
import os
import re
import calendar
from datetime import date, datetime
from groq import Groq

st.set_page_config(page_title="Roteirista Litúrgico Multi-Job", layout="wide")
CHARACTERS_FILE = "characters_db.json"
HISTORY_FILE = "history_db.json"
STYLE_SUFFIX = ". Style: Cinematic Realistic, 1080p resolution, highly detailed, masterpiece, cinematic lighting, detailed texture, photography style."
FIXED_CHARACTERS = {
    "Jesus": "Homem de 33 anos, descendência do oriente médio, cabelos longos e escuros, barba, túnica branca, faixa vermelha, expressão serena.",
    "Pessoa Moderna": "Jovem adulto (homem ou mulher), roupas casuais modernas (jeans/camiseta), aparência cotidiana e identificável."
}

def load_json(file_path):
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f: return json.load(f)
        except: return {} if "char" in file_path else []
    return {} if "char" in file_path else []

def save_json(file_path, data):
    with open(file_path, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2)

def load_characters():
    custom = load_json(CHARACTERS_FILE)
    all_chars = FIXED_CHARACTERS.copy()
    all_chars.update(custom)
    return all_chars

def save_characters(data): save_json(CHARACTERS_FILE, data)

def load_history(): return load_json(HISTORY_FILE)

def update_history(date_str):
    hist = load_history()
    if date_str not in hist:
        hist.append(date_str)
        hist.sort()
        save_json(HISTORY_FILE, hist)

def get_groq_client():
    api_key = st.secrets.get("GROQ_API_KEY") or os.getenv("GROQ_API_KEY")
    if not api_key: st.error("❌ GROQ_API_KEY não encontrada."); st.stop()
    return Groq(api_key=api_key)

def fetch_liturgia(date_obj):
    url = f"https://api-liturgia-diaria.vercel.app/?date={date_obj.strftime('%Y-%m-%d')}".strip()
    try:
        resp = requests.get(url)
        resp.raise_for_status()
        return resp.json()
    except Exception as e: st.error(f"Erro liturgia: {e}"); return None

def send_to_gas(payload):
    gas_url = st.secrets.get("GAS_SCRIPT_URL") or os.getenv("GAS_SCRIPT_URL")
    if not gas_url: st.error("❌ GAS_SCRIPT_URL não encontrada."); return None
    try:
        resp = requests.post(f"{gas_url}?action=generate_job", json=payload)
        return resp.json() if resp.status_code == 200 else None
    except Exception as e: st.error(f"Erro GAS: {e}"); return None

def generate_script_and_identify_chars(reading_text, reading_type):
    client = get_groq_client()
    if reading_type == "1ª Leitura":
        regras = "1. INÍCIO: 'Leitura do Livro do [Nome]' (sem caps/vers). 2. FIM: 'Palavra do Senhor!'."
    elif reading_type == "2ª Leitura":
        regras = "1. INÍCIO: 'Leitura da [Nome da Carta]' (sem caps/vers). 2. FIM: 'Palavra do Senhor!'."
    elif reading_type == "Salmo":
        regras = "1. INÍCIO: 'Salmo Responsorial: '. 2. Sem números."
    elif reading_type == "Evangelho":
        regras = "1. INÍCIO: 'Proclamação do Evangelho de Jesus Cristo segundo [AUTOR]. Glória a Vós, Senhor!'. 2. FIM: 'Palavra da Salvação. Glória a Vós, Senhor!'. 3. NÃO duplicar frases."
    else: regras = "Texto LIMPO."

    prompt = f"""Assistente litúrgico. TAREFA: Roteiro curto ({reading_type}).
    ESTRUTURA: 1. hook (5-10s): Impactante. 2. leitura: {regras} 3. reflexao (20-25s): Inicie com "Reflexão:". 4. aplicacao (20-25s). 5. oracao (15-20s): Inicie com "Vamos orar"/"Oremos". FIM: "Amém!".
    EXTRA: Identifique PERSONAGENS (exceto Jesus/Deus). SAÍDA JSON: {{"roteiro": {{...}}, "personagens_identificados": [...]}}"""
    try:
        chat = client.chat.completions.create(messages=[{"role": "system", "content": prompt}, {"role": "user", "content": f"Texto:\n{reading_text}"}], model="llama-3.3-70b-versatile", response_format={"type": "json_object"}, temperature=0.7)
        return json.loads(chat.choices[0].message.content)
    except: return None

def generate_character_description(name):
    try:
        chat = get_groq_client().chat.completions.create(messages=[{"role": "user", "content": f"Descrição visual detalhada personagem bíblico: {name}. Rosto, roupas. ~300 chars. Realista."}], model="llama-3.3-70b-versatile", temperature=0.7)
        return chat.choices[0].message.content.strip()
    except: return "Sem descrição."

def build_prompts(roteiro, chars, db, style):
    desc_j = db.get("Jesus", FIXED_CHARACTERS["Jesus"])
    desc_m = db.get("Pessoa Moderna", FIXED_CHARACTERS["Pessoa Moderna"])
    desc_b = ("Chars: " + " | ".join([f"{n}: {db.get(n,'')}" for n in chars])) if chars else ""
    return {
        "hook": f"Cena Bíblica Realista: {roteiro.get('hook','')}. {desc_b} {style}",
        "leitura": f"Cena Bíblica Realista. Contexto: {roteiro.get('leitura','').strip()[:300]}... {desc_b} {style}",
        "reflexao": f"Cena Moderna. Jesus conversando com Pessoa Moderna. Jesus: {desc_j} Modern: {desc_m} {style}",
        "aplicacao": f"Cena Moderna. Jesus e Pessoa Moderna caminhando. Jesus: {desc_j} Modern: {desc_m} {style}",
        "oracao": f"Cena Moderna. Jesus e Pessoa Moderna orando. Jesus: {desc_j} Modern: {desc_m} {style}"
    }

def clean_text(text):
    if not text: return ""
    text = re.sub(r'\d{1,3}(?=[A-Za-zÀ-ÿ])', '', text)
    text = re.sub(r'\b\d{1,3}\s+(?=["\'A-Za-zÀ-ÿ])', '', text)
    return re.sub(r'\b\d{1,3}\.\s+', '', text).replace('  ', ' ').strip()

def extract(obj):
    if not obj: return ""
    if "content_psalm" in obj: return f"{obj.get('response', '')}\n" + ("\n".join(obj["content_psalm"]) if isinstance(obj["content_psalm"], list) else str(obj["content_psalm"]))
    return clean_text(obj.get("text") or obj.get("texto"))

def render_calendar(history):
    today = date.today()
    cal = calendar.monthcalendar(today.year, today.month)
    month_name = calendar.month_name[today.month]
    html = f"<div style='font-size:12px; font-family:monospace; text-align:center; border:1px solid #ddd; padding:5px; border-radius:5px; background:white;'>"
    html += f"<strong>{month_name} {today.year}</strong><br><br>"
    html += "<div style='display:grid; grid-template-columns:repeat(7, 1fr); gap:2px;'>"
    for d in ["S","M","T","W","T","F","S"]: html += f"<div>{d}</div>"
    for week in cal:
        for day in week:
            if day == 0: html += "<div></div>"
            else:
                d_str = f"{today.year}-{today.month:02d}-{day:02d}"
                bg = "#d1fae5" if d_str in history else "transparent"
                border = "1px solid blue" if d_str == today.strftime("%Y-%m-%d") else "none"
                html += f"<div style='background:{bg}; border:{border}; border-radius:3px;'>{day}</div>"
    html += "</div><div style='margin-top:5px; font-size:10px;'>🟩 Enviado</div></div>"
    st.sidebar.markdown(html, unsafe_allow_html=True)

def main():
    st.sidebar.title("⚙️ Configurações")
    char_db = load_characters()
    history = load_history()
    render_calendar(history)
    
    tab1, tab2 = st.tabs(["📜 Roteiros", "👥 Personagens"])
    if 'daily' not in st.session_state: st.session_state['daily'] = []
    if 'scripts' not in st.session_state: st.session_state['scripts'] = []

    with tab1:
        st.header("1. Buscar Liturgia")
        d_sel = st.date_input("Data", value=date.today())
        d_str = d_sel.strftime("%Y-%m-%d")
        
        is_done = d_str in history
        if is_done: st.success(f"✅ Tarefas do dia {d_sel.strftime('%d/%m')} já concluídas!")
        
        if st.button("Buscar Leituras"):
            data = fetch_liturgia(d_sel)
            if data:
                st.session_state['daily'] = []
                st.session_state['scripts'] = []
                rds = data.get('today', {}).get('readings', {}) or data.get('readings', {})
                def add(k, t):
                    if k in rds:
                        txt, ref = extract(rds[k]), rds[k].get('title', t)
                        if txt.strip(): st.session_state['daily'].append({"type": t, "text": txt, "ref": ref, "d_show": d_sel.strftime("%d/%m/%Y"), "d_iso": d_str})
                add('first_reading', '1ª Leitura'); add('psalm', 'Salmo'); add('second_reading', '2ª Leitura'); add('gospel', 'Evangelho')
                if st.session_state['daily']: st.success(f"{len(st.session_state['daily'])} leituras!")
                else: st.warning("Vazio.")

        if st.session_state['daily']:
            st.divider()
            for r in st.session_state['daily']:
                with st.expander(f"{r['type']}: {r['ref']}"): st.text(r['text'])
            
            st.divider(); st.header("2. Gerar Roteiros")
            if st.button("✨ Gerar Todos"):
                st.session_state['scripts'] = []
                prog = st.progress(0)
                for i, r in enumerate(st.session_state['daily']):
                    res = generate_script_and_identify_chars(r['text'], r['type'])
                    if res:
                        chars = res.get('personagens_identificados', [])
                        for c in chars:
                            if c not in char_db: char_db[c] = generate_character_description(c)
                        save_characters(char_db)
                        st.session_state['scripts'].append({"meta": r, "roteiro": res.get('roteiro', {}), "chars": chars})
                    prog.progress((i+1)/len(st.session_state['daily']))

        if st.session_state['scripts']:
            st.divider(); st.header("3. Enviar (Drive)")
            for s in st.session_state['scripts']:
                m, r = s['meta'], s['roteiro']
                prompts = build_prompts(r, s['chars'], char_db, STYLE_SUFFIX)
                with st.expander(f"✅ {m['type']} - {m['ref']}"):
                    c1, c2 = st.columns(2)
                    with c1: st.info(f"Hook: {r.get('hook')}"); st.text_area("Leitura", r.get('leitura'), height=100, key=f"l_{m['type']}")
                    with c2: st.write(f"Reflexão: {r.get('reflexao')}"); st.write(f"Aplicação: {r.get('aplicacao')}"); st.write(f"Oração: {r.get('oracao')}")
                    st.caption(f"Prompt Hook: {prompts['hook']}")

            force_dup = False
            if is_done:
                st.warning(f"⚠️ O dia {d_sel.strftime('%d/%m')} já consta no histórico de envios.")
                force_dup = st.checkbox("Confirmar envio em duplicidade (Pode gerar arquivos repetidos no Drive)")
            
            if st.button("🚀 Enviar Todos", disabled=(is_done and not force_dup)):
                prog, cnt = st.progress(0), 0
                for i, s in enumerate(st.session_state['scripts']):
                    m, r = s['meta'], s['roteiro']
                    pld = {
                        "meta_dados": {"data": m['d_show'], "ref": f"{m['type']} - {m['ref']}"},
                        "roteiro": {k: {"text": r.get(k,''), "prompt": build_prompts(r, s['chars'], char_db, STYLE_SUFFIX).get(k,'')} for k in ["hook", "leitura", "reflexao", "aplicacao", "oracao"]},
                        "assets": []
                    }
                    if send_to_gas(pld): cnt += 1
                    prog.progress((i+1)/len(st.session_state['scripts']))
                
                if cnt == len(st.session_state['scripts']):
                    update_history(d_str)
                    st.balloons(); st.success("Sucesso! Histórico atualizado."); st.rerun()
                else: st.warning(f"{cnt} enviados.")

    with tab2:
        st.header("Personagens")
        for n, d in char_db.items():
            with st.expander(n):
                new_d = st.text_area("Desc", d, key=f"d_{n}")
                if st.button("Salvar", key=f"s_{n}"): char_db[n]=new_d; save_characters(char_db); st.rerun()
                if n not in FIXED_CHARACTERS and st.button("Excluir", key=f"x_{n}"): del char_db[n]; save_characters(char_db); st.rerun()
        n = st.text_input("Novo"); d = st.text_area("Desc")
        if st.button("Criar") and n: char_db[n]=d; save_characters(char_db); st.rerun()

if __name__ == "__main__": main()
