import streamlit as st
import requests
import json
import os
import re
import calendar
import logging
from datetime import date, timedelta, datetime
from groq import Groq
from bs4 import BeautifulSoup

# ==========================================
# CONFIGURAÇÕES
# ==========================================
st.set_page_config(page_title="Roteirista Litúrgico Multi-Job", layout="wide")
CHARACTERS_FILE = "characters_db.json"
HISTORY_FILE = "history_db.json"
STYLE_SUFFIX = ". Style: Cinematic Realistic, 1080p resolution, highly detailed, masterpiece, cinematic lighting, detailed texture, photography style."

FIXED_CHARACTERS = {
    "Jesus": "Homem de 33 anos, descendência do oriente médio, cabelos longos e escuros, barba, túnica branca, faixa vermelha, expressão serena.",
    "Pessoa Moderna": "Jovem adulto (homem ou mulher), roupas casuais modernas (jeans/camiseta), aparência cotidiana e identificável."
}

# ==========================================
# FUNÇÕES AUXILIARES
# ==========================================
def load_json(file_path):
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f: return json.load(f)
        except: return {} if "char" in file_path else []
    return {} if "char" in file_path else []

def save_json(file_path, data):
    with open(file_path, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2)

def load_characters():
    all_chars = FIXED_CHARACTERS.copy()
    all_chars.update(load_json(CHARACTERS_FILE))
    return all_chars

def save_characters(data): save_json(CHARACTERS_FILE, data)
def load_history(): return load_json(HISTORY_FILE)

def update_history_bulk(dates):
    hist = load_history()
    updated = False
    for d in dates:
        if d not in hist: hist.append(d); updated = True
    if updated: hist.sort(); save_json(HISTORY_FILE, hist)

# ==========================================
# FONTES DE DADOS
# ==========================================
def get_groq_client():
    api_key = st.secrets.get("GROQ_API_KEY") or os.getenv("GROQ_API_KEY")
    if not api_key: st.error("❌ Configure GROQ_API_KEY."); st.stop()
    return Groq(api_key=api_key)

# --- SCRAPER ARAUTOS (BACKUP FORTE) ---
def fetch_liturgia_arautos(date_obj):
    url = f"https://www.arautos.org/liturgia-diaria?date={date_obj.strftime('%Y-%m-%d')}"
    print(f"Tentando Arautos: {url}")
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200: return None
            
        soup = BeautifulSoup(r.content, 'html.parser')
        full_text = soup.get_text("\n")
        
        # Mapa simples
        readings = {}
        
        # Regex para achar posições
        # Procura por "Evangelho" ou "Proclamação..."
        idx_evang = re.search(r'(Evangelho|Proclamação do Evangelho)', full_text, re.IGNORECASE)
        idx_1a = re.search(r'(Primeira Leitura|Leitura do Livro)', full_text, re.IGNORECASE)
        
        # Extração Simples (Evangelho é prioridade)
        if idx_evang:
            # Pega tudo do Evangelho até "Outros santos" ou fim
            raw = full_text[idx_evang.end():]
            clean = re.split(r'(Outros santos|Santo do dia|Comentário)', raw, flags=re.IGNORECASE)[0]
            readings['gospel'] = {'text': clean.strip()[:4000], 'title': 'Evangelho (Arautos)'}
            
        if idx_1a and idx_evang:
            # Pega o que está entre 1a leitura e Evangelho como "1a Leitura" (simplificado)
            raw = full_text[idx_1a.end():idx_evang.start()]
            readings['first_reading'] = {'text': raw.strip()[:3000], 'title': '1ª Leitura (Arautos)'}

        if readings: return {'readings': readings, 'source': 'Backup Arautos'}
    except Exception as e: print(f"Erro Arautos: {e}")
    return None

def fetch_liturgia(date_obj):
    # 1. Tenta Vercel
    try:
        url = f"https://api-liturgia-diaria.vercel.app/?date={date_obj.strftime('%Y-%m-%d')}".strip()
        r = requests.get(url, timeout=5)
        if r.status_code == 200: return r.json()
    except: pass

    # 2. Tenta Railway
    try:
        url = f"https://liturgia.up.railway.app/v2/{date_obj.strftime('%Y-%m-%d')}"
        r = requests.get(url, timeout=8)
        if r.status_code == 200:
            d = r.json()
            # Normaliza Railway
            norm = {'readings': {}}
            if d.get('evangelho'): norm['readings']['gospel'] = {'text': d['evangelho'].get('texto'), 'title': 'Evangelho'}
            if d.get('primeira_leitura'): norm['readings']['first_reading'] = {'text': d['primeira_leitura'].get('texto'), 'title': '1ª Leitura'}
            if d.get('salmo'): norm['readings']['psalm'] = {'text': d['salmo'].get('texto'), 'title': 'Salmo'}
            if d.get('segunda_leitura'): norm['readings']['second_reading'] = {'text': d['segunda_leitura'].get('texto'), 'title': '2ª Leitura'}
            return norm
    except: pass

    # 3. Tenta Arautos
    return fetch_liturgia_arautos(date_obj)

def send_to_gas(payload):
    gas_url = st.secrets.get("GAS_SCRIPT_URL") or os.getenv("GAS_SCRIPT_URL")
    if not gas_url: st.error("❌ Configure GAS_SCRIPT_URL."); return None
    try:
        r = requests.post(f"{gas_url}?action=generate_job", json=payload)
        return r.json() if r.status_code == 200 else None
    except: return None

# ==========================================
# LÓGICA IA
# ==========================================
def generate_script_and_identify_chars(reading_text, reading_type):
    client = get_groq_client()
    regras = "Texto LIMPO."
    if "1ª" in reading_type: regras = "1. INÍCIO: 'Leitura do Livro...'. 2. FIM: 'Palavra do Senhor!'."
    if "Evangelho" in reading_type: regras = "1. INÍCIO: 'Proclamação do Evangelho...'. 2. FIM: 'Palavra da Salvação...'. 3. NÃO duplicar."
    
    prompt = f"""Assistente litúrgico. TAREFA: Roteiro curto ({reading_type}).
    ESTRUTURA: 
    1. hook (5-10s): Impactante. FIM: CTA "Comente sua cidade".
    2. leitura: {regras}
    3. reflexao (20-25s): Inicie "Reflexão:".
    4. aplicacao (20-25s).
    5. oracao (15-20s): Inicie "Vamos orar". FIM "Amém!".
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
        "reflexao": f"Cena Moderna. Jesus e Pessoa Moderna (café). Jesus: {desc_j} Modern: {desc_m} {style}",
        "aplicacao": f"Cena Moderna. Jesus e Pessoa Moderna caminhando. Jesus: {desc_j} Modern: {desc_m} {style}",
        "oracao": f"Cena Moderna. Jesus e Pessoa Moderna orando. Jesus: {desc_j} Modern: {desc_m} {style}"
    }

def clean_text(text):
    if not text: return ""
    text = re.sub(r'\d{1,3}(?=[A-Za-zÀ-ÿ])', '', text)
    return re.sub(r'\b\d{1,3}\s+(?=["\'A-Za-zÀ-ÿ])', '', text).strip()

def extract(obj):
    if not obj: return ""
    if "content_psalm" in obj: return f"{obj.get('response', '')}\n" + ("\n".join(obj["content_psalm"]) if isinstance(obj["content_psalm"], list) else str(obj["content_psalm"]))
    return clean_text(obj.get("text") or obj.get("texto"))

def render_calendar(history):
    today = date.today()
    cal = calendar.monthcalendar(today.year, today.month)
    html = f"<div style='font-size:12px; font-family:monospace; text-align:center; border:1px solid #ddd; padding:5px; border-radius:5px; background:white;'><strong>{calendar.month_name[today.month]}</strong><div style='display:grid; grid-template-columns:repeat(7, 1fr); gap:2px;'>"
    for week in cal:
        for day in week:
            if day == 0: html += "<div></div>"
            else:
                d_str = f"{today.year}-{today.month:02d}-{day:02d}"
                bg = "#d1fae5" if d_str in history else "transparent"
                html += f"<div style='background:{bg}; border-radius:3px;'>{day}</div>"
    st.sidebar.markdown(html + "</div></div>", unsafe_allow_html=True)

# ==========================================
# MAIN
# ==========================================
def main():
    st.sidebar.title("⚙️ Config")
    char_db = load_characters()
    history = load_history()
    render_calendar(history)
    
    st.sidebar.markdown("---")
    if st.sidebar.button("Limpar Histórico"):
        if os.path.exists(HISTORY_FILE): os.remove(HISTORY_FILE); st.rerun()
    if st.sidebar.button("Limpar Cache"): st.session_state.clear(); st.rerun()

    tab1, tab2 = st.tabs(["📜 Roteiros (Massa)", "👥 Personagens"])
    if 'daily' not in st.session_state: st.session_state['daily'] = []
    if 'scripts' not in st.session_state: st.session_state['scripts'] = []

    with tab1:
        st.header("1. Seleção de Datas")
        c1, c2 = st.columns(2)
        with c1: dt_ini = st.date_input("Início", value=date.today())
        with c2: dt_fim = st.date_input("Fim", value=date.today())
        
        if st.button("Buscar Leituras"):
            st.session_state['daily'] = []
            st.session_state['scripts'] = []
            
            with st.status("🔍 Buscando...", expanded=True) as status:
                curr = dt_ini
                while curr <= dt_fim:
                    st.write(f"🗓️ {curr.strftime('%d/%m')}")
                    data = fetch_liturgia(curr)
                    
                    if data:
                        # DEBUG: Mostra o que chegou para entendermos o erro
                        # st.write(data) 
                        
                        # Tenta normalizar 'readings'
                        rds = {}
                        if 'readings' in data: 
                            if 'today' in data and 'readings' in data['today']: rds = data['today']['readings']
                            else: rds = data['readings']
                        else: rds = data

                        # Função ADD robusta
                        def add(key_list, label):
                            obj = None
                            for k in key_list:
                                if k in rds and rds[k]:
                                    obj = rds[k]
                                    break
                            
                            if obj:
                                txt = extract(obj)
                                if len(txt) > 20:
                                    ref = obj.get('title') or label
                                    st.session_state['daily'].append({"type": label, "text": txt, "ref": ref, "d_show": curr.strftime("%d/%m/%Y"), "d_iso": curr.strftime("%Y-%m-%d")})
                        
                        # Tenta várias chaves possíveis para cada tipo
                        add(['first_reading', 'primeira_leitura', 'leitura_1'], '1ª Leitura')
                        add(['psalm', 'salmo', 'salmo_responsorial'], 'Salmo')
                        add(['second_reading', 'segunda_leitura', 'leitura_2'], '2ª Leitura')
                        add(['gospel', 'evangelho', 'evangelho_do_dia'], 'Evangelho')
                    else:
                        st.error(f"❌ Falha para {curr.strftime('%d/%m')}")
                    curr += timedelta(days=1)
                
                status.update(label=f"Fim! {len(st.session_state['daily'])} leituras encontradas.", state="complete")

        if st.session_state['daily']:
            st.divider(); st.write(f"📖 **{len(st.session_state['daily'])} Leituras Prontas**")
            with st.expander("Ver lista"):
                for r in st.session_state['daily']: st.text(f"{r['d_show']} - {r['type']}")
            
            st.divider(); st.header("2. Gerar Roteiros")
            if st.button("✨ Gerar Tudo"):
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
            unique_dates = sorted(list(set([s['meta']['d_iso'] for s in st.session_state['scripts']])))
            already_sent = [d for d in unique_dates if d in history]
            
            if already_sent: st.warning(f"⚠️ Já enviados: {already_sent}")
            force = st.checkbox("Forçar envio duplicado") if already_sent else True

            st.write("▼ **Preview:**")
            for s in st.session_state['scripts']:
                m, r = s['meta'], s['roteiro']
                prompts = build_prompts(r, s['chars'], char_db, STYLE_SUFFIX)
                with st.expander(f"✅ {m['d_show']} - {m['type']}"):
                    c1, c2 = st.columns(2)
                    with c1: 
                        st.info(f"**Hook:** {r.get('hook')}")
                        st.text_area("Leitura", r.get('leitura'), height=150, key=f"l_{m['d_iso']}_{m['type']}")
                    with c2:
                        st.write(f"Reflexão: {r.get('reflexao')}")
                        st.write(f"Aplicação: {r.get('aplicacao')}")
                        st.write(f"Oração: {r.get('oracao')}")
                    st.caption("🎨 Prompts:")
                    st.code(f"HOOK: {prompts['hook']}\nLEITURA: {prompts['leitura']}\nREFLEXÃO: {prompts['reflexao']}\nAPLICAÇÃO: {prompts['aplicacao']}\nORAÇÃO: {prompts['oracao']}", language="text")

            if st.button("🚀 Enviar", disabled=not force):
                prog, cnt = st.progress(0), 0
                sent = set()
                for i, s in enumerate(st.session_state['scripts']):
                    m, r = s['meta'], s['roteiro']
                    prompts = build_prompts(r, s['chars'], char_db, STYLE_SUFFIX)
                    pld = {
                        "meta_dados": {"data": m['d_show'], "ref": f"{m['type']} - {m['ref']}"},
                        "roteiro": {k: {"text": r.get(k,''), "prompt": prompts.get(k,'')} for k in ["hook", "leitura", "reflexao", "aplicacao", "oracao"]},
                        "assets": []
                    }
                    if send_to_gas(pld): cnt += 1; sent.add(m['d_iso'])
                    prog.progress((i+1)/len(st.session_state['scripts']))
                
                if cnt > 0: update_history_bulk(list(sent)); st.balloons(); st.success(f"{cnt} enviados!"); st.rerun()
                else: st.error("Falha no envio.")

    with tab2:
        st.header("Personagens")
        for n, d in char_db.items():
            with st.expander(n):
                new_d = st.text_area("Desc", d, key=f"d_{n}")
                if st.button("Salvar", key=f"s_{n}"): char_db[n]=new_d; save_characters(char_db); st.rerun()
        n = st.text_input("Novo"); d = st.text_area("Desc")
        if st.button("Criar") and n: char_db[n]=d; save_characters(char_db); st.rerun()

if __name__ == "__main__": main()
