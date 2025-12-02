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
# FONTES DE DADOS
# ==========================================
def get_groq_client():
    api_key = st.secrets.get("GROQ_API_KEY") or os.getenv("GROQ_API_KEY")
    if not api_key: st.error("❌ Configure GROQ_API_KEY."); st.stop()
    return Groq(api_key=api_key)

def fetch_liturgia(date_obj):
    # 1. Tenta Vercel (Principal)
    try:
        url = f"https://api-liturgia-diaria.vercel.app/?date={date_obj.strftime('%Y-%m-%d')}".strip()
        r = requests.get(url, timeout=5)
        if r.status_code == 200: return r.json()
    except: pass

    # 2. Tenta Railway (Backup)
    try:
        url = f"https://liturgia.up.railway.app/v2/{date_obj.strftime('%Y-%m-%d')}"
        r = requests.get(url, timeout=8)
        if r.status_code == 200:
            d = r.json()
            # Normaliza Railway para padrão
            norm = {'readings': {}}
            if d.get('evangelho'): norm['readings']['gospel'] = {'text': d['evangelho'].get('texto'), 'title': d['evangelho'].get('referencia')}
            if d.get('primeira_leitura'): norm['readings']['first_reading'] = {'text': d['primeira_leitura'].get('texto'), 'title': d['primeira_leitura'].get('referencia')}
            if d.get('salmo'): norm['readings']['psalm'] = {'text': d['salmo'].get('texto'), 'title': d['salmo'].get('referencia')}
            if d.get('segunda_leitura'): norm['readings']['second_reading'] = {'text': d['segunda_leitura'].get('texto'), 'title': d['segunda_leitura'].get('referencia')}
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
# LÓGICA IA & EXTRAÇÃO
# ==========================================
def clean_text(text):
    if not text: return ""
    text = re.sub(r'\d{1,3}(?=[A-Za-zÀ-ÿ])', '', text)
    return re.sub(r'\b\d{1,3}\s+(?=["\'A-Za-zÀ-ÿ])', '', text).strip()

def extract(obj):
    if not obj: return ""
    # Verifica valor do salmo
    if obj.get("content_psalm"): 
        c = obj["content_psalm"]
        full_psalm = "\n".join(c) if isinstance(c, list) else str(c)
        return f"{obj.get('response', '')}\n{full_psalm}"
    
    # Texto normal
    raw_text = obj.get("text") or obj.get("texto") or obj.get("conteudo") or ""
    return clean_text(raw_text)

def generate_script_and_identify_chars(reading_text, reading_type):
    client = get_groq_client()
    regras = "Texto LIMPO."
    if "1ª" in reading_type: regras = "1. INÍCIO: 'Leitura do Livro...'. 2. FIM: 'Palavra do Senhor!'."
    if "2ª" in reading_type: regras = "1. INÍCIO: 'Leitura da Carta...'. 2. FIM: 'Palavra do Senhor!'."
    if "Salmo" in reading_type: regras = "1. INÍCIO: 'Salmo Responsorial: '. 2. Sem números."
    if "Evangelho" in reading_type: regras = "1. INÍCIO: 'Proclamação do Evangelho...'. 2. FIM: 'Palavra da Salvação...'. 3. NÃO duplicar."
    
    # PROMPT ATUALIZADO COM HOOK + CTA
    prompt = f"""Assistente litúrgico. TAREFA: Roteiro curto ({reading_type}).
    ESTRUTURA: 
    1. hook (10-20s): Deve conter DOIS elementos:
       - Parte A (5-10s): Frase impactante e curiosa relacionada ao tema da leitura para prender a atenção.
       - Parte B (5-10s): CTA breve perguntando de qual cidade a pessoa está acompanhando ou pedindo interação.
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
# PROCESSAMENTO CENTRAL
# ==========================================
def run_process_dashboard(mode_key, dt_ini, dt_fim):
    k_daily = f"{mode_key}_daily"
    k_scripts = f"{mode_key}_scripts"
    k_missing = f"{mode_key}_missing"

    if k_daily not in st.session_state: st.session_state[k_daily] = []
    if k_scripts not in st.session_state: st.session_state[k_scripts] = []
    if k_missing not in st.session_state: st.session_state[k_missing] = []

    # 1. BUSCA
    if st.button("🔎 Buscar Leituras", key=f"btn_fetch_{mode_key}"):
        if dt_fim < dt_ini: st.error("Data final < inicial"); return
        st.session_state[k_daily] = []
        st.session_state[k_scripts] = []
        st.session_state[k_missing] = []
        
        with st.status("Processando...", expanded=True) as status:
            curr = dt_ini
            while curr <= dt_fim:
                st.write(f"🗓️ {curr.strftime('%d/%m')}")
                data = fetch_liturgia(curr)
                day_readings = []
                has_gospel = False
                
                if data:
                    rds = data.get('readings') or data.get('today', {}).get('readings', {}) or data
                    def check_add(k, t):
                        obj = rds.get(k)
                        if not obj and k=='gospel': obj = rds.get('evangelho')
                        if not obj and k=='first_reading': obj = rds.get('primeira_leitura') or rds.get('leitura_1')
                        if not obj and k=='psalm': obj = rds.get('salmo') or rds.get('salmo_responsorial')
                        if not obj and k=='second_reading': obj = rds.get('segunda_leitura') or rds.get('leitura_2')
                        
                        if obj:
                            txt = extract(obj)
                            ref = obj.get('title') or obj.get('referencia', t)
                            if txt and len(txt)>20:
                                return {"type": t, "text": txt, "ref": ref, "d_show": curr.strftime("%d/%m/%Y"), "d_iso": curr.strftime("%Y-%m-%d")}
                        return None

                    r1 = check_add('first_reading', '1ª Leitura'); 
                    if r1: day_readings.append(r1)
                    
                    sl = check_add('psalm', 'Salmo'); 
                    if sl: day_readings.append(sl)
                    
                    r2 = check_add('second_reading', '2ª Leitura'); 
                    if r2: day_readings.append(r2)
                    
                    ev = check_add('gospel', 'Evangelho'); 
                    if ev: day_readings.append(ev); has_gospel = True

                if has_gospel:
                    st.session_state[k_daily].extend(day_readings)
                else:
                    st.warning(f"⚠️ {curr.strftime('%d/%m')}: Dados insuficientes. Fila manual.")
                    st.session_state[k_missing].append(curr)
                
                curr += timedelta(days=1)
            status.update(label="Busca finalizada!", state="complete")

    # 2. FILA MANUAL
    if st.session_state[k_missing]:
        curr_m = st.session_state[k_missing][0]
        st.markdown("---")
        st.error(f"✍️ **Entrada Manual: {curr_m.strftime('%d/%m/%Y')}**")
        
        with st.form(f"manual_{mode_key}_{curr_m}"):
            c1, c2 = st.columns([1,3]); r1=c1.text_input("Ref. 1ª Leitura"); t1=c2.text_area("Texto 1ª Leitura")
            c3, c4 = st.columns([1,3]); rsl=c3.text_input("Ref. Salmo"); tsl=c4.text_area("Texto Salmo")
            c5, c6 = st.columns([1,3]); r2=c5.text_input("Ref. 2ª Leitura"); t2=c6.text_area("Texto 2ª Leitura")
            c7, c8 = st.columns([1,3]); rev=c7.text_input("Ref. Evangelho"); tev=c8.text_area("Texto Evangelho (Obrigatório)")
            
            if st.form_submit_button("💾 Salvar"):
                ds, di = curr_m.strftime("%d/%m/%Y"), curr_m.strftime("%Y-%m-%d")
                if t1: st.session_state[k_daily].append({"type": "1ª Leitura", "text": t1, "ref": r1 or "1ª Leitura", "d_show": ds, "d_iso": di})
                if tsl: st.session_state[k_daily].append({"type": "Salmo", "text": tsl, "ref": rsl or "Salmo", "d_show": ds, "d_iso": di})
                if t2: st.session_state[k_daily].append({"type": "2ª Leitura", "text": t2, "ref": r2 or "2ª Leitura", "d_show": ds, "d_iso": di})
                if tev: st.session_state[k_daily].append({"type": "Evangelho", "text": tev, "ref": rev or "Evangelho", "d_show": ds, "d_iso": di})
                st.session_state[k_missing].pop(0); st.rerun()

    # 3. LISTAGEM & GERAÇÃO
    if st.session_state[k_daily] and not st.session_state[k_missing]:
        st.session_state[k_daily].sort(key=lambda x: x['d_iso'])
        st.divider(); st.write(f"📖 **{len(st.session_state[k_daily])} Leituras Prontas**")
        
        with st.expander("Ver Detalhes"):
            for i in st.session_state[k_daily]: st.text(f"{i['d_show']} | {i['type']} | {i['ref']}")

        if st.button("✨ Gerar Roteiros", key=f"btn_gen_{mode_key}"):
            st.session_state[k_scripts] = []
            char_db = load_characters()
            prog = st.progress(0)
            for i, r in enumerate(st.session_state[k_daily]):
                res = generate_script_and_identify_chars(r['text'], r['type'])
                if res:
                    chars = res.get('personagens_identificados', [])
                    for c in chars:
                        if c not in char_db: char_db[c] = generate_character_description(c)
                    save_characters(char_db)
                    st.session_state[k_scripts].append({"meta": r, "roteiro": res.get('roteiro', {}), "chars": chars})
                prog.progress((i+1)/len(st.session_state[k_daily]))
            st.rerun()

    # 4. PREVIEW & ENVIO
    if st.session_state[k_scripts]:
        st.divider(); st.write("🚀 **Envio**")
        hist = load_history()
        dates = sorted(list(set([s['meta']['d_iso'] for s in st.session_state[k_scripts]])))
        dups = [d for d in dates if d in hist]
        
        if dups: st.warning(f"⚠️ Já enviados: {dups}")
        force = st.checkbox("Confirmar duplicidade", key=f"chk_{mode_key}") if dups else True

        for s in st.session_state[k_scripts]:
            m, r = s['meta'], s['roteiro']
            prompts = build_prompts(r, s['chars'], load_characters(), STYLE_SUFFIX)
            with st.expander(f"✅ {m['d_show']} - {m['type']} ({m['ref']})"):
                c1, c2 = st.columns(2)
                with c1: 
                    st.info(f"**Hook:** {r.get('hook')}")
                    st.text_area("Leitura", r.get('leitura'), height=150, key=f"l_{m['ref']}_{mode_key}")
                with c2:
                    st.write(f"**Reflexão:** {r.get('reflexao')[:100]}...")
                    st.write(f"**Aplicação:** {r.get('aplicacao')}")
                    st.write(f"**Oração:** {r.get('oracao')}")
                
                st.divider()
                st.caption("🎨 Prompts:")
                c3, c4 = st.columns(2)
                with c3:
                    st.code(f"Hook: {prompts['hook']}", language="text")
                    st.code(f"Leitura: {prompts['leitura']}", language="text")
                    st.code(f"Reflexão: {prompts['reflexao']}", language="text")
                with c4:
                    st.code(f"Aplicação: {prompts['aplicacao']}", language="text")
                    st.code(f"Oração: {prompts['oracao']}", language="text")

        if st.button("🚀 Enviar Lote", disabled=not force, key=f"snd_{mode_key}"):
            prog = st.progress(0); sent = set(); cnt=0
            char_db = load_characters()
            for i, s in enumerate(st.session_state[k_scripts]):
                m, r = s['meta'], s['roteiro']
                prompts = build_prompts(r, s['chars'], char_db, STYLE_SUFFIX)
                pld = {
                    "meta_dados": {"data": m['d_show'], "ref": f"{m['type']} - {m['ref']}"},
                    "roteiro": {k: {"text": r.get(k,''), "prompt": prompts.get(k,'')} for k in ["hook", "leitura", "reflexao", "aplicacao", "oracao"]},
                    "assets": []
                }
                if send_to_gas(pld): cnt+=1; sent.add(m['d_iso'])
                prog.progress((i+1)/len(st.session_state[k_scripts]))
            
            if cnt>0: update_history_bulk(list(sent)); st.balloons(); st.success(f"{cnt} enviados!"); st.rerun()
            else: st.error("Falha.")

# ==========================================
# MAIN APP
# ==========================================
def main():
    st.sidebar.title("⚙️ Config")
    history = load_history()
    render_calendar(history)
    st.sidebar.markdown("---")
    if st.sidebar.button("Limpar Histórico"):
        if os.path.exists(HISTORY_FILE): os.remove(HISTORY_FILE); st.rerun()
    if st.sidebar.button("Limpar Cache"): st.session_state.clear(); st.rerun()

    tab1, tab2, tab3 = st.tabs(["📅 Roteiro Único", "📚 Roteiros em Massa", "👥 Personagens"])

    with tab1:
        st.header("Gerador Diário")
        dt = st.date_input("Data", value=date.today(), key="dt1")
        run_process_dashboard("single", dt, dt)

    with tab2:
        st.header("Gerador em Lote")
        c1, c2 = st.columns(2)
        with c1: d1 = st.date_input("Início", value=date.today(), key="dt2a")
        with c2: d2 = st.date_input("Fim", value=date.today()+timedelta(days=6), key="dt2b")
        run_process_dashboard("mass", d1, d2)

    with tab3:
        char_db = load_characters()
        st.header("Banco de Personagens")
        for n, d in char_db.items():
            with st.expander(n):
                new_d = st.text_area("Desc", d, key=f"ed_{n}")
                if st.button("Salvar", key=f"sv_{n}"): char_db[n]=new_d; save_characters(char_db); st.rerun()
        n = st.text_input("Novo"); d = st.text_area("Desc")
        if st.button("Criar") and n: char_db[n]=d; save_characters(char_db); st.rerun()

if __name__ == "__main__": main()
