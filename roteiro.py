import streamlit as st
import requests
import json
import os
import re
import calendar
from datetime import date, timedelta, datetime
from groq import Groq

# ==========================================
# CONFIGURAÇÕES
# ==========================================
st.set_page_config(page_title="Roteirista Litúrgico", layout="wide")
CHARACTERS_FILE = "characters_db.json"
HISTORY_FILE = "history_db.json"
STYLE_SUFFIX = ". Style: Cinematic Realistic, 1080p resolution, highly detailed, masterpiece, cinematic lighting, detailed texture, photography style."

FIXED_CHARACTERS = {
    "Jesus": "Homem de 33 anos, descendência do oriente médio, cabelos longos e escuros, barba, túnica branca, faixa vermelha, expressão serena.",
    "Pessoa Moderna": "Jovem adulto (homem ou mulher), roupas casuais modernas (jeans/camiseta), aparência cotidiana e identificável."
}

# ==========================================
# PERSISTÊNCIA
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
# FONTES DE DADOS (APIS)
# ==========================================
def get_groq_client():
    api_key = st.secrets.get("GROQ_API_KEY") or os.getenv("GROQ_API_KEY")
    if not api_key: st.error("❌ Configure GROQ_API_KEY."); st.stop()
    return Groq(api_key=api_key)

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
            norm = {'readings': {}}
            if d.get('evangelho'): norm['readings']['gospel'] = {'text': d['evangelho'].get('texto'), 'title': 'Evangelho'}
            if d.get('primeira_leitura'): norm['readings']['first_reading'] = {'text': d['primeira_leitura'].get('texto'), 'title': '1ª Leitura'}
            if d.get('salmo'): norm['readings']['psalm'] = {'text': d['salmo'].get('texto'), 'title': 'Salmo'}
            if d.get('segunda_leitura'): norm['readings']['second_reading'] = {'text': d['segunda_leitura'].get('texto'), 'title': '2ª Leitura'}
            return norm
    except: pass
    
    return None # Falha total

def send_to_gas(payload):
    gas_url = st.secrets.get("GAS_SCRIPT_URL") or os.getenv("GAS_SCRIPT_URL")
    if not gas_url: st.error("❌ Configure GAS_SCRIPT_URL."); return None
    try:
        r = requests.post(f"{gas_url}?action=generate_job", json=payload)
        return r.json() if r.status_code == 200 else None
    except: return None

# ==========================================
# LÓGICA IA (GROQ)
# ==========================================
def generate_script_and_identify_chars(reading_text, reading_type):
    client = get_groq_client()
    regras = "Texto LIMPO."
    if "1ª" in reading_type: regras = "1. INÍCIO: 'Leitura do Livro...'. 2. FIM: 'Palavra do Senhor!'."
    if "2ª" in reading_type: regras = "1. INÍCIO: 'Leitura da Carta...'. 2. FIM: 'Palavra do Senhor!'."
    if "Salmo" in reading_type: regras = "1. INÍCIO: 'Salmo Responsorial: '. 2. Sem números."
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
                border = "1px solid blue" if d_str == today.strftime("%Y-%m-%d") else "none"
                html += f"<div style='background:{bg}; border:{border}; border-radius:3px;'>{day}</div>"
    st.sidebar.markdown(html + "</div></div>", unsafe_allow_html=True)

# ==========================================
# INTERFACE PRINCIPAL
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

    # --- ABAS DE NAVEGAÇÃO ---
    tab1, tab2, tab3 = st.tabs(["📅 Roteiro Único", "📚 Roteiros em Massa", "👥 Personagens"])

    # Inicialização de Estado Global
    if 'daily' not in st.session_state: st.session_state['daily'] = []
    if 'scripts' not in st.session_state: st.session_state['scripts'] = []
    if 'manual_queue' not in st.session_state: st.session_state['manual_queue'] = [] # Fila de dias sem dados

    # ==========================================
    # ABA 1: ROTEIRO ÚNICO
    # ==========================================
    with tab1:
        st.header("Gerar Roteiro de Um Dia")
        dt_single = st.date_input("Selecione a Data", value=date.today())
        
        if st.button("Buscar Leituras (Dia Único)"):
            st.session_state['daily'] = [] # Limpa anterior
            st.session_state['scripts'] = []
            st.session_state['manual_queue'] = []
            
            with st.spinner("Buscando..."):
                data = fetch_liturgia(dt_single)
                found = False
                if data:
                    rds = data.get('readings') or data.get('today', {}).get('readings', {}) or data
                    # Verifica se tem Evangelho (mínimo necessário)
                    if rds.get('gospel') or rds.get('evangelho'):
                        # Processa normalmente
                        def add(k, t):
                            obj = rds.get(k)
                            # Fallbacks
                            if not obj and k=='gospel': obj = rds.get('evangelho')
                            if not obj and k=='first_reading': obj = rds.get('primeira_leitura') or rds.get('leitura_1')
                            if not obj and k=='psalm': obj = rds.get('salmo') or rds.get('salmo_responsorial')
                            if not obj and k=='second_reading': obj = rds.get('segunda_leitura') or rds.get('leitura_2')
                            
                            if obj:
                                txt = extract({'text': obj.get('text') or obj.get('texto') or obj.get('conteudo'), 'content_psalm': obj.get('content_psalm'), 'response': obj.get('response')})
                                ref = obj.get('title') or obj.get('referencia', t)
                                if txt and len(txt) > 20:
                                    st.session_state['daily'].append({"type": t, "text": txt, "ref": ref, "d_show": dt_single.strftime("%d/%m/%Y"), "d_iso": dt_single.strftime("%Y-%m-%d")})
                        
                        add('first_reading', '1ª Leitura'); add('psalm', 'Salmo'); add('second_reading', '2ª Leitura'); add('gospel', 'Evangelho')
                        found = True
                
                if not found:
                    st.warning(f"Dados não encontrados para {dt_single.strftime('%d/%m')}. Ativando modo manual.")
                    st.session_state['manual_queue'].append(dt_single)

    # ==========================================
    # ABA 2: ROTEIROS EM MASSA
    # ==========================================
    with tab2:
        st.header("Gerar Roteiros em Lote")
        c1, c2 = st.columns(2)
        with c1: dt_ini = st.date_input("Data Inicial", value=date.today(), key="mass_ini")
        with c2: dt_fim = st.date_input("Data Final", value=date.today() + timedelta(days=6), key="mass_fim")
        
        if st.button("Buscar Leituras (Intervalo)"):
            if dt_fim < dt_ini: st.error("Data final menor que inicial"); st.stop()
            st.session_state['daily'] = []
            st.session_state['scripts'] = []
            st.session_state['manual_queue'] = []
            
            with st.status("Processando intervalo...", expanded=True) as status:
                curr = dt_ini
                while curr <= dt_fim:
                    st.write(f"🗓️ Verificando {curr.strftime('%d/%m')}...")
                    data = fetch_liturgia(curr)
                    has_gospel = False
                    
                    if data:
                        rds = data.get('readings') or data.get('today', {}).get('readings', {}) or data
                        
                        # Verifica Evangelho antes de adicionar qualquer coisa
                        g_obj = rds.get('gospel') or rds.get('evangelho')
                        if g_obj:
                            has_gospel = True
                            # Função Add local
                            def add_m(k, t):
                                obj = rds.get(k)
                                if not obj and k=='gospel': obj = rds.get('evangelho')
                                if not obj and k=='first_reading': obj = rds.get('primeira_leitura') or rds.get('leitura_1')
                                if not obj and k=='psalm': obj = rds.get('salmo') or rds.get('salmo_responsorial')
                                if not obj and k=='second_reading': obj = rds.get('segunda_leitura') or rds.get('leitura_2')
                                
                                if obj:
                                    txt = extract({'text': obj.get('text') or obj.get('texto') or obj.get('conteudo'), 'content_psalm': obj.get('content_psalm'), 'response': obj.get('response')})
                                    ref = obj.get('title') or obj.get('referencia', t)
                                    if txt and len(txt) > 20:
                                        st.session_state['daily'].append({"type": t, "text": txt, "ref": ref, "d_show": curr.strftime("%d/%m/%Y"), "d_iso": curr.strftime("%Y-%m-%d")})
                            
                            add_m('first_reading', '1ª Leitura')
                            add_m('psalm', 'Salmo')
                            add_m('second_reading', '2ª Leitura')
                            add_m('gospel', 'Evangelho')

                    if not has_gospel:
                        st.warning(f"⚠️ {curr.strftime('%d/%m')}: Falha na API. Adicionado à fila manual.")
                        st.session_state['manual_queue'].append(curr)
                    
                    curr += timedelta(days=1)
                status.update(label="Busca concluída!", state="complete")

    # ==========================================
    # ÁREA COMUM: MANUAL, GERAÇÃO E ENVIO
    # ==========================================
    
    # 1. PROCESSAMENTO MANUAL (FILA)
    if st.session_state['manual_queue']:
        curr_manual = st.session_state['manual_queue'][0]
        st.markdown("---")
        st.error(f"✍️ **Entrada Manual Necessária: {curr_manual.strftime('%d/%m/%Y')}**")
        st.info(f"Restam {len(st.session_state['manual_queue'])} dias para preencher.")
        
        with st.form(f"manual_form_{curr_manual}"):
            c1, c2 = st.columns([1,3])
            r1 = c1.text_input("Ref. 1ª Leitura (ex: Is 26,1-6)")
            t1 = c2.text_area("Texto 1ª Leitura", height=100)
            
            c3, c4 = st.columns([1,3])
            rsl = c3.text_input("Ref. Salmo (ex: Sl 118)")
            tsl = c4.text_area("Texto Salmo", height=100)
            
            c5, c6 = st.columns([1,3])
            r2 = c5.text_input("Ref. 2ª Leitura (Opcional)")
            t2 = c6.text_area("Texto 2ª Leitura", height=100)
            
            c7, c8 = st.columns([1,3])
            rev = c7.text_input("Ref. Evangelho (Obrigatório)")
            tev = c8.text_area("Texto Evangelho", height=150)
            
            if st.form_submit_button("💾 Salvar e Próximo"):
                d_show = curr_manual.strftime("%d/%m/%Y")
                d_iso = curr_manual.strftime("%Y-%m-%d")
                
                if t1: st.session_state['daily'].append({"type": "1ª Leitura", "text": t1, "ref": r1 or "1ª Leitura", "d_show": d_show, "d_iso": d_iso})
                if tsl: st.session_state['daily'].append({"type": "Salmo", "text": tsl, "ref": rsl or "Salmo", "d_show": d_show, "d_iso": d_iso})
                if t2: st.session_state['daily'].append({"type": "2ª Leitura", "text": t2, "ref": r2 or "2ª Leitura", "d_show": d_show, "d_iso": d_iso})
                if tev: st.session_state['daily'].append({"type": "Evangelho", "text": tev, "ref": rev or "Evangelho", "d_show": d_show, "d_iso": d_iso})
                
                st.session_state['manual_queue'].pop(0)
                st.rerun()

    # 2. LISTAGEM E BOTÃO GERAR
    if st.session_state['daily'] and not st.session_state['manual_queue']:
        st.divider()
        st.session_state['daily'].sort(key=lambda x: x['d_iso']) # Ordena por data
        st.write(f"📖 **{len(st.session_state['daily'])} Leituras na Fila de Processamento**")
        
        with st.expander("Ver lista detalhada"):
            for item in st.session_state['daily']:
                st.text(f"{item['d_show']} | {item['type']} | {item['ref']}")

        if st.button("✨ Gerar Roteiros com IA"):
            st.session_state['scripts'] = []
            char_db = load_characters()
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
            st.rerun()

    # 3. PREVIEW E ENVIO
    if st.session_state['scripts']:
        st.divider()
        st.write("🚀 **Revisão e Envio**")
        
        # Verifica duplicidade no histórico
        hist = load_history()
        dates = sorted(list(set([s['meta']['d_iso'] for s in st.session_state['scripts']])))
        dups = [d for d in dates if d in hist]
        
        if dups: st.warning(f"⚠️ Datas já enviadas anteriormente: {', '.join(dups)}")
        force = st.checkbox("Forçar envio duplicado") if dups else True

        # Preview detalhado
        for s in st.session_state['scripts']:
            m, r = s['meta'], s['roteiro']
            prompts = build_prompts(r, s['chars'], load_characters(), STYLE_SUFFIX)
            with st.expander(f"✅ {m['d_show']} - {m['type']} ({m['ref']})"):
                c1, c2 = st.columns(2)
                with c1: 
                    st.info(f"**Hook:** {r.get('hook')}")
                    st.text_area("Leitura", r.get('leitura'), height=100, key=f"view_{m['d_iso']}_{m['type']}")
                with c2:
                    st.write(f"Reflexão: {r.get('reflexao')[:100]}...")
                    st.write(f"Oração: {r.get('oracao')}")
                st.caption("🎨 Prompts:")
                st.code(f"HOOK: {prompts['hook']}\nLEITURA: {prompts['leitura']}", language="text")

        if st.button("🚀 Enviar para Drive", disabled=not force):
            prog = st.progress(0)
            sent_dates = set()
            char_db = load_characters()
            
            for i, s in enumerate(st.session_state['scripts']):
                m, r = s['meta'], s['roteiro']
                prompts = build_prompts(r, s['chars'], char_db, STYLE_SUFFIX)
                payload = {
                    "meta_dados": {"data": m['d_show'], "ref": f"{m['type']} - {m['ref']}"},
                    "roteiro": {k: {"text": r.get(k,''), "prompt": prompts.get(k,'')} for k in ["hook", "leitura", "reflexao", "aplicacao", "oracao"]},
                    "assets": []
                }
                if send_to_gas(payload): sent_dates.add(m['d_iso'])
                prog.progress((i+1)/len(st.session_state['scripts']))
            
            if sent_dates:
                update_history_bulk(list(sent_dates))
                st.balloons()
                st.success("Envio concluído!")
                st.session_state['daily'] = []
                st.session_state['scripts'] = []
                st.rerun()
            else:
                st.error("Nenhum roteiro enviado.")

    # ==========================================
    # ABA 3: PERSONAGENS
    # ==========================================
    with tab3:
        st.header("Banco de Personagens")
        char_db = load_characters()
        for n, d in char_db.items():
            with st.expander(n):
                new_d = st.text_area("Desc", d, key=f"desc_{n}")
                if st.button("Salvar", key=f"save_{n}"): char_db[n]=new_d; save_characters(char_db); st.rerun()
                if n not in FIXED_CHARACTERS and st.button("Excluir", key=f"del_{n}"): del char_db[n]; save_characters(char_db); st.rerun()
        
        st.divider()
        n = st.text_input("Novo Personagem")
        d = st.text_area("Descrição Visual")
        if st.button("Criar Personagem") and n: char_db[n]=d; save_characters(char_db); st.rerun()

if __name__ == "__main__": main()
