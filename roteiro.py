import streamlit as st
import requests
import json
import os
import re
import calendar
import logging
import io
from datetime import date, timedelta, datetime
from groq import Groq
from bs4 import BeautifulSoup

# ==========================================
# CONFIGURAÇÃO DE LOGS
# ==========================================
if 'system_logs' not in st.session_state:
    st.session_state['system_logs'] = []

def add_log(message, level="INFO"):
    timestamp = datetime.now().strftime("%H:%M:%S")
    entry = f"[{timestamp}] [{level}] {message}"
    st.session_state['system_logs'].append(entry)
    if len(st.session_state['system_logs']) > 500:
        st.session_state['system_logs'].pop(0)
    print(entry)

def get_logs_as_text():
    return "\n".join(st.session_state['system_logs'])

# ==========================================
# CONFIGURAÇÕES GERAIS
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
# PERSISTÊNCIA
# ==========================================

def load_json(file_path):
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f: return json.load(f)
        except Exception as e:
            add_log(f"Erro JSON {file_path}: {e}", "ERROR"); return {} if "char" in file_path else []
    return {} if "char" in file_path else []

def save_json(file_path, data):
    try:
        with open(file_path, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e: add_log(f"Erro salvar JSON: {e}", "ERROR")

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
# FONTES DE DADOS (SCRAPERS E APIS)
# ==========================================

def get_groq_client():
    api_key = st.secrets.get("GROQ_API_KEY") or os.getenv("GROQ_API_KEY")
    if not api_key:
        add_log("GROQ_API_KEY ausente.", "CRITICAL")
        st.error("Configure GROQ_API_KEY."); st.stop()
    return Groq(api_key=api_key)

# --- FONTE 2: API RAILWAY ---
def fetch_liturgia_railway(date_obj):
    url = f"https://liturgia.up.railway.app/v2/{date_obj.strftime('%Y-%m-%d')}"
    add_log(f"Tentando Backup 1 (Railway): {url}")
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            add_log("Sucesso Railway.")
            d = r.json()
            norm = {'readings': {}}
            # Normalização simples
            if 'evangelho' in d: norm['readings']['gospel'] = {'text': d['evangelho'].get('texto',''), 'title': d['evangelho'].get('referencia','Evangelho')}
            if 'primeira_leitura' in d: norm['readings']['first_reading'] = {'text': d['primeira_leitura'].get('texto',''), 'title': d['primeira_leitura'].get('referencia','1ª Leitura')}
            if 'salmo' in d: norm['readings']['psalm'] = {'text': d['salmo'].get('texto','') or d['salmo'].get('refrao',''), 'title': d['salmo'].get('referencia','Salmo')}
            if 'segunda_leitura' in d: norm['readings']['second_reading'] = {'text': d['segunda_leitura'].get('texto',''), 'title': d['segunda_leitura'].get('referencia','2ª Leitura')}
            return norm
        add_log(f"Falha Railway: {r.status_code}", "WARNING")
    except Exception as e: add_log(f"Erro Railway: {e}", "ERROR")
    return None

# --- FONTE 3: SCRAPER ARAUTOS (NOVO) ---
def fetch_liturgia_arautos(date_obj):
    """Scraper robusto para datas futuras."""
    url = f"https://www.arautos.org/liturgia-diaria?date={date_obj.strftime('%Y-%m-%d')}"
    add_log(f"Tentando Backup 2 (Arautos): {url}")
    
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            add_log(f"Falha Arautos: {r.status_code}", "WARNING"); return None
            
        soup = BeautifulSoup(r.content, 'html.parser')
        # Arautos não tem classes fixas fáceis, vamos pegar o texto bruto e separar com Regex
        full_text = soup.get_text("\n")
        
        # Lógica de separação (similar ao CN mas adaptada)
        readings = {}
        
        # Regex flexível
        idx_1a = re.search(r'(Primeira Leitura|Leitura do Livro)', full_text, re.IGNORECASE)
        idx_salmo = re.search(r'(Salmo Responsorial|Salmo)', full_text, re.IGNORECASE)
        idx_2a = re.search(r'(Segunda Leitura)', full_text, re.IGNORECASE)
        idx_evang = re.search(r'(Evangelho|Proclamação do Evangelho)', full_text, re.IGNORECASE)
        
        def get_chunk(start, end, text):
            if not start: return ""
            s = start.end()
            e = end.start() if end else len(text)
            # Limita tamanho para evitar pegar rodapé
            chunk = text[s:e].strip()
            return chunk[:3500] 

        if idx_1a: readings['first_reading'] = {'text': get_chunk(idx_1a, idx_salmo, full_text), 'title': '1ª Leitura (Arautos)'}
        if idx_salmo: readings['psalm'] = {'text': get_chunk(idx_salmo, idx_2a if idx_2a else idx_evang, full_text), 'title': 'Salmo (Arautos)'}
        if idx_2a: readings['second_reading'] = {'text': get_chunk(idx_2a, idx_evang, full_text), 'title': '2ª Leitura (Arautos)'}
        if idx_evang: readings['gospel'] = {'text': full_text[idx_evang.end():].split("Outros santos")[0].strip()[:3500], 'title': 'Evangelho (Arautos)'} # Tenta cortar antes do rodapé

        if readings:
            add_log("Sucesso Arautos Scraper.")
            return {'readings': readings, 'source': 'Backup Arautos'}
        add_log("Arautos: Estrutura não reconhecida.", "WARNING")
    except Exception as e:
        add_log(f"Erro Arautos: {e}", "ERROR")
    return None

# --- FONTE 4: SCRAPER CANÇÃO NOVA ---
def fetch_liturgia_cn(date_obj):
    url = f"https://liturgia.cancaonova.com/pb/liturgia/{date_obj.strftime('%d-%m-%Y')}/"
    add_log(f"Tentando Backup 3 (CN): {url}")
    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
        if r.status_code == 200:
            soup = BeautifulSoup(r.content, 'html.parser')
            entry = soup.find('div', class_='entry-content')
            if entry:
                txt = entry.get_text("\n")
                # Retorna como 'gospel' genérico para o Groq separar se precisar
                return {'readings': {'gospel': {'text': txt[:4000], 'title': 'Leitura Completa (CN)'}}, 'source': 'Backup CN'}
        add_log(f"Falha CN: {r.status_code}", "WARNING")
    except: pass
    return None

def fetch_liturgia(date_obj):
    # Ordem de prioridade
    url_vercel = f"https://api-liturgia-diaria.vercel.app/?date={date_obj.strftime('%Y-%m-%d')}".strip()
    add_log(f"Tentando Principal (Vercel): {url_vercel}")
    try:
        r = requests.get(url_vercel, timeout=8)
        if r.status_code == 200: return r.json()
        add_log(f"Vercel falhou ({r.status_code}).")
    except: add_log("Vercel offline.")

    # Tentativas de Backup
    res = fetch_liturgia_railway(date_obj)
    if res: return res
    
    res = fetch_liturgia_arautos(date_obj)
    if res: return res
    
    return fetch_liturgia_cn(date_obj)

def send_to_gas(payload):
    gas_url = st.secrets.get("GAS_SCRIPT_URL") or os.getenv("GAS_SCRIPT_URL")
    if not gas_url: st.error("❌ Configure GAS_SCRIPT_URL."); return None
    try:
        add_log(f"Enviando GAS: {payload.get('meta_dados',{}).get('ref')}")
        r = requests.post(f"{gas_url}?action=generate_job", json=payload)
        if r.status_code == 200: return r.json()
        add_log(f"Erro GAS: {r.text}", "ERROR")
    except Exception as e: add_log(f"Exceção GAS: {e}", "ERROR")
    return None

# ==========================================
# LÓGICA IA
# ==========================================

def generate_script_and_identify_chars(reading_text, reading_type):
    client = get_groq_client()
    if reading_type == "1ª Leitura": regras = "1. INÍCIO: 'Leitura do Livro do [Nome]' (sem caps/vers). 2. FIM: 'Palavra do Senhor!'."
    elif reading_type == "2ª Leitura": regras = "1. INÍCIO: 'Leitura da [Nome da Carta]' (sem caps/vers). 2. FIM: 'Palavra do Senhor!'."
    elif reading_type == "Salmo": regras = "1. INÍCIO: 'Salmo Responsorial: '. 2. Sem números."
    elif reading_type == "Evangelho": regras = "1. INÍCIO: 'Proclamação do Evangelho de Jesus Cristo segundo [AUTOR]. Glória a Vós, Senhor!'. 2. FIM: 'Palavra da Salvação. Glória a Vós, Senhor!'. 3. NÃO duplicar."
    else: regras = "Texto LIMPO."

    prompt = f"""Assistente litúrgico. TAREFA: Roteiro curto ({reading_type}).
    ESTRUTURA: 
    1. hook (5-10s): Impactante. FIM OBRIGATÓRIO: CTA pedindo para comentar a cidade.
    2. leitura: {regras}
    3. reflexao (20-25s): Inicie com "Reflexão:".
    4. aplicacao (20-25s).
    5. oracao (15-20s): Inicie "Vamos orar". FIM "Amém!".
    EXTRA: Identifique PERSONAGENS (exceto Jesus/Deus). SAÍDA JSON: {{"roteiro": {{...}}, "personagens_identificados": [...]}}"""
    try:
        add_log(f"Gerando roteiro ({reading_type})...")
        chat = client.chat.completions.create(messages=[{"role": "system", "content": prompt}, {"role": "user", "content": f"Texto:\n{reading_text}"}], model="llama-3.3-70b-versatile", response_format={"type": "json_object"}, temperature=0.7)
        return json.loads(chat.choices[0].message.content)
    except Exception as e: add_log(f"Erro Groq: {e}", "ERROR"); return None

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
        "reflexao": f"Cena Moderna. Jesus conversando com Pessoa Moderna (café/sala). Jesus: {desc_j} Modern: {desc_m} {style}",
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

# ==========================================
# INTERFACE
# ==========================================

def main():
    st.sidebar.title("⚙️ Config")
    char_db = load_characters()
    history = load_history()
    render_calendar(history)
    
    st.sidebar.markdown("---")
    with st.sidebar.expander("📝 Logs do Sistema"):
        log_text = get_logs_as_text()
        st.text_area("Logs", value=log_text, height=200)
        if st.button("Limpar Logs"): st.session_state['system_logs'] = []; st.rerun()

    with st.sidebar.expander("🧹 Manutenção"):
        if st.button("Limpar Histórico"):
            if os.path.exists(HISTORY_FILE): os.remove(HISTORY_FILE); st.rerun()
        if st.button("Limpar Cache"): st.session_state.clear(); st.rerun()

    tab1, tab2 = st.tabs(["📜 Roteiros (Massa)", "👥 Personagens"])
    if 'daily' not in st.session_state: st.session_state['daily'] = []
    if 'scripts' not in st.session_state: st.session_state['scripts'] = []

    with tab1:
        st.header("1. Seleção de Datas")
        c1, c2 = st.columns(2)
        with c1: dt_ini = st.date_input("Data Inicial", value=date.today())
        with c2: dt_fim = st.date_input("Data Final", value=date.today())
        
        if st.button("Buscar Leituras"):
            if dt_fim < dt_ini: st.error("Data final menor que inicial"); st.stop()
            st.session_state['daily'] = []
            st.session_state['scripts'] = []
            st.session_state['system_logs'] = []
            
            with st.status("Baixando...", expanded=True) as status:
                curr = dt_ini
                count = 0
                while curr <= dt_fim:
                    st.write(f"📅 Processando: {curr.strftime('%d/%m/%Y')}")
                    data = fetch_liturgia(curr)
                    if data:
                        # Adaptação Universal de Estrutura
                        rds = {}
                        if 'readings' in data: 
                            if 'today' in data and 'readings' in data['today']: rds = data['today']['readings']
                            else: rds = data['readings']
                        else: # Estrutura plana (alguns scrapers)
                            rds = data

                        def add(k, t):
                            # Busca chaves comuns ou tenta mapear direto
                            obj = rds.get(k)
                            # Se não achar pela chave padrão, tenta achar no dicionário plano
                            if not obj and k == 'gospel' and 'evangelho' in rds: obj = rds['evangelho']
                            if not obj and k == 'first_reading' and 'primeira_leitura' in rds: obj = rds['primeira_leitura']
                            if not obj and k == 'psalm' and 'salmo' in rds: obj = rds['salmo']
                            
                            if obj:
                                txt_raw = obj.get('text') or obj.get('texto') or obj.get('conteudo')
                                ref = obj.get('title') or obj.get('referencia', t)
                                txt = extract({'text': txt_raw, 'content_psalm': obj.get('content_psalm'), 'response': obj.get('response')})
                                if txt and len(txt) > 20: # Filtra leituras vazias
                                    st.session_state['daily'].append({"type": t, "text": txt, "ref": ref, "d_show": curr.strftime("%d/%m/%Y"), "d_iso": curr.strftime("%Y-%m-%d")})
                        
                        add('first_reading', '1ª Leitura')
                        add('psalm', 'Salmo')
                        add('second_reading', '2ª Leitura')
                        add('gospel', 'Evangelho')
                        count += 1
                    else:
                        add_log(f"Falha total para {curr.strftime('%d/%m')}", "ERROR")
                    curr += timedelta(days=1)
                status.update(label=f"Fim! {len(st.session_state['daily'])} leituras encontradas.", state="complete")

        if st.session_state['daily']:
            st.divider(); st.write(f"📖 **{len(st.session_state['daily'])} Leituras**")
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
            
            if already_sent:
                st.warning(f"⚠️ Já enviados: {', '.join(already_sent)}")
                force = st.checkbox("Confirmar duplicidade")
            else: force = True

            st.write("▼ **Preview:**")
            for s in st.session_state['scripts']:
                m, r = s['meta'], s['roteiro']
                prompts = build_prompts(r, s['chars'], char_db, STYLE_SUFFIX)
                with st.expander(f"✅ {m['d_show']} - {m['type']}"):
                    c1, c2 = st.columns(2)
                    with c1: 
                        st.info(f"**Hook:** {r.get('hook')}")
                        st.text_area("Leitura", r.get('leitura'), height=100, key=f"l_{m['d_iso']}_{m['type']}")
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
