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
# CONFIGURAÇÃO DE LOGS (DEBUG VISUAL)
# ==========================================
if 'system_logs' not in st.session_state:
    st.session_state['system_logs'] = []

def add_log(message, level="INFO"):
    """Adiciona log na memória e printa no console."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    entry = f"[{timestamp}] [{level}] {message}"
    st.session_state['system_logs'].append(entry)
    # Mantém histórico limpo (últimos 500)
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
            add_log(f"Erro JSON {file_path}: {e}", "ERROR")
            return {} if "char" in file_path else []
    return {} if "char" in file_path else []

def save_json(file_path, data):
    try:
        with open(file_path, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        add_log(f"Erro salvar JSON: {e}", "ERROR")

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
    if not api_key:
        add_log("GROQ_API_KEY ausente.", "CRITICAL")
        st.error("Configure GROQ_API_KEY."); st.stop()
    return Groq(api_key=api_key)

# --- BACKUP 1: RAILWAY ---
def fetch_liturgia_railway(date_obj):
    url = f"https://liturgia.up.railway.app/v2/{date_obj.strftime('%Y-%m-%d')}"
    st.write(f"🔸 Tentando Backup 1 (Railway): `{url}`")
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            st.write("✅ Sucesso Railway!")
            d = r.json()
            norm = {'readings': {}}
            ev = d.get('evangelho') or d.get('evangelho_do_dia')
            if ev: norm['readings']['gospel'] = {'text': ev.get('texto',''), 'title': ev.get('referencia','Evangelho')}
            pl = d.get('primeira_leitura')
            if pl: norm['readings']['first_reading'] = {'text': pl.get('texto',''), 'title': pl.get('referencia','1ª Leitura')}
            sl = d.get('salmo')
            if sl: norm['readings']['psalm'] = {'text': sl.get('texto','') or sl.get('refrao',''), 'title': sl.get('referencia','Salmo')}
            sl2 = d.get('segunda_leitura')
            if sl2: norm['readings']['second_reading'] = {'text': sl2.get('texto',''), 'title': sl2.get('referencia','2ª Leitura')}
            return norm
    except Exception as e: st.write(f"⚠️ Erro Railway: {e}")
    return None

# --- BACKUP 2: ARAUTOS (Lógica de Corte Aprimorada) ---
def fetch_liturgia_arautos(date_obj):
    url = f"https://www.arautos.org/liturgia-diaria?date={date_obj.strftime('%Y-%m-%d')}"
    st.write(f"🔸 Tentando Backup 2 (Arautos): `{url}`")
    
    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
        if r.status_code != 200: return None
            
        soup = BeautifulSoup(r.content, 'html.parser')
        full_text = soup.get_text("\n")
        
        # Mapa de marcadores e suas chaves
        markers = [
            (r'Primeira Leitura', 'first_reading', '1ª Leitura'),
            (r'Salmo Responsorial|Salmo \d', 'psalm', 'Salmo'),
            (r'Segunda Leitura', 'second_reading', '2ª Leitura'),
            (r'Evangelho|Proclamação do Evangelho', 'gospel', 'Evangelho')
        ]
        
        # Encontra todas as posições
        found_sections = []
        for pattern, key, title in markers:
            match = re.search(pattern, full_text, re.IGNORECASE)
            if match:
                found_sections.append({'start': match.end(), 'key': key, 'title': title, 'pos': match.start()})
        
        # Ordena pela posição no texto
        found_sections.sort(key=lambda x: x['pos'])
        
        readings = {}
        for i, section in enumerate(found_sections):
            start = section['start']
            # O fim desta seção é o início da próxima (ou o fim do texto)
            end = found_sections[i+1]['pos'] if i+1 < len(found_sections) else len(full_text)
            
            # Extrai e limpa
            content = full_text[start:end].strip()
            
            # Limpeza extra para Arautos (remove rodapés comuns no último item)
            if i == len(found_sections) - 1:
                content = re.split(r'(Outros santos|Santo do dia|Comentário)', content, flags=re.IGNORECASE)[0]
            
            if len(content) > 20:
                readings[section['key']] = {'text': content[:4000], 'title': section['title']}
            else:
                st.write(f"⚠️ Aviso: Seção '{section['key']}' encontrada mas vazia (<20 chars).")

        if readings:
            st.write(f"✅ Arautos: {len(readings)} leituras extraídas.")
            return {'readings': readings, 'source': 'Backup Arautos'}
            
    except Exception as e: st.write(f"⚠️ Erro Arautos: {e}")
    return None

# --- BACKUP 3: CANÇÃO NOVA ---
def fetch_liturgia_cancaonova(date_obj):
    date_str = date_obj.strftime("%d-%m-%Y")
    url = f"https://liturgia.cancaonova.com/pb/liturgia/{date_str}/"
    st.write(f"🔸 Tentando Backup 3 (CN): `{url}`")
    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
        if r.status_code == 200:
            soup = BeautifulSoup(r.content, 'html.parser')
            entry = soup.find('div', class_='entry-content')
            if entry:
                txt = entry.get_text("\n")[:4000]
                return {'readings': {'gospel': {'text': txt, 'title': 'Leitura Completa (CN)'}}, 'source': 'Backup CN'}
    except: pass
    return None

def fetch_liturgia(date_obj):
    url_vercel = f"https://api-liturgia-diaria.vercel.app/?date={date_obj.strftime('%Y-%m-%d')}".strip()
    st.write(f"🔹 Tentando Principal (Vercel): `{url_vercel}`")
    try:
        r = requests.get(url_vercel, timeout=8)
        if r.status_code == 200:
            st.write("✅ Sucesso Vercel!")
            return r.json()
        st.write(f"⚠️ Vercel falhou: {r.status_code}")
    except: st.write("⚠️ Vercel offline.")

    res = fetch_liturgia_railway(date_obj)
    if res: return res
    res = fetch_liturgia_arautos(date_obj)
    if res: return res
    return fetch_liturgia_cancaonova(date_obj)

def send_to_gas(payload):
    gas_url = st.secrets.get("GAS_SCRIPT_URL") or os.getenv("GAS_SCRIPT_URL")
    if not gas_url: st.error("❌ Configure GAS_SCRIPT_URL."); return None
    try:
        st.write(f"📤 Enviando para GAS: {payload.get('meta_dados',{}).get('ref')}")
        r = requests.post(f"{gas_url}?action=generate_job", json=payload)
        if r.status_code == 200: st.write("✅ Envio confirmado."); return r.json()
        st.error(f"❌ Erro GAS: {r.text}")
    except Exception as e: st.error(f"❌ Exceção GAS: {e}")
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
    1. hook (5-10s): Frase impactante (20-30 palavras). FIM OBRIGATÓRIO: CTA "Comente sua cidade".
    2. leitura: {regras}
    3. reflexao (20-25s): Inicie "Reflexão:".
    4. aplicacao (20-25s).
    5. oracao (15-20s): Inicie "Vamos orar". FIM "Amém!".
    EXTRA: Identifique PERSONAGENS (exceto Jesus/Deus). SAÍDA JSON: {{"roteiro": {{...}}, "personagens_identificados": [...]}}"""
    try:
        st.write(f"🤖 Gerando roteiro Groq: {reading_type}...")
        chat = client.chat.completions.create(messages=[{"role": "system", "content": prompt}, {"role": "user", "content": f"Texto:\n{reading_text}"}], model="llama-3.3-70b-versatile", response_format={"type": "json_object"}, temperature=0.7)
        return json.loads(chat.choices[0].message.content)
    except Exception as e: st.error(f"❌ Erro Groq: {e}"); return None

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
        "hook": f"Cena Bíblica Cinematográfica realista: {roteiro.get('hook','')}. {desc_b} {style}",
        "leitura": f"Cena Bíblica Cinematográfica realista. Contexto: {roteiro.get('leitura','').strip()[:300]}... {desc_b} {style}",
        "reflexao": f"Cena Moderna. Jesus conversando com Pessoa Moderna (café/sala). Jesus: {desc_j} Modern: {desc_m} {style}",
        "aplicacao": f"Cena Moderna. Jesus e Pessoa Moderna caminhando/ensinando. Jesus: {desc_j} Modern: {desc_m} {style}",
        "oracao": f"Cena Moderna. Jesus e Pessoa Moderna orando juntos, paz. Jesus: {desc_j} Modern: {desc_m} {style}"
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
    html = f"<div style='font-size:12px; font-family:monospace; text-align:center; border:1px solid #ddd; padding:5px; border-radius:5px; background:white;'><strong>{calendar.month_name[today.month]} {today.year}</strong><br><div style='display:grid; grid-template-columns:repeat(7, 1fr); gap:2px;'>"
    for d in ["S","M","T","W","T","F","S"]: html += f"<div>{d}</div>"
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
# INTERFACE
# ==========================================

def main():
    st.sidebar.title("⚙️ Config")
    char_db = load_characters()
    history = load_history()
    render_calendar(history)
    
    st.sidebar.markdown("---")
    with st.sidebar.expander("📝 Logs do Sistema"):
        st.text_area("Logs", value=get_logs_as_text(), height=200)
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
            
            with st.status("🔍 Buscando...", expanded=True) as status:
                curr = dt_ini
                count = 0
                while curr <= dt_fim:
                    st.write(f"**🗓️ {curr.strftime('%d/%m/%Y')}**")
                    data = fetch_liturgia(curr)
                    if data:
                        rds = {}
                        if 'readings' in data: 
                            if 'today' in data and 'readings' in data['today']: rds = data['today']['readings']
                            else: rds = data['readings']
                        else: rds = data

                        def add(k, t):
                            obj = rds.get(k)
                            if not obj and k == 'gospel': obj = rds.get('evangelho')
                            if not obj and k == 'first_reading': obj = rds.get('primeira_leitura') or rds.get('leitura_1')
                            if not obj and k == 'psalm': obj = rds.get('salmo') or rds.get('salmo_responsorial')
                            if not obj and k == 'second_reading': obj = rds.get('segunda_leitura') or rds.get('leitura_2')
                            
                            if obj:
                                txt_raw = obj.get('text') or obj.get('texto') or obj.get('conteudo') or obj.get('refrao')
                                ref = obj.get('title') or obj.get('referencia', t)
                                txt = extract({'text': txt_raw, 'content_psalm': obj.get('content_psalm'), 'response': obj.get('response')})
                                if txt and len(txt) > 20: 
                                    st.session_state['daily'].append({"type": t, "text": txt, "ref": ref, "d_show": curr.strftime("%d/%m/%Y"), "d_iso": curr.strftime("%Y-%m-%d")})
                                else:
                                    st.write(f"⚠️ Texto vazio para {t}")
                        
                        add('first_reading', '1ª Leitura')
                        add('psalm', 'Salmo')
                        add('second_reading', '2ª Leitura')
                        add('gospel', 'Evangelho')
                        count += 1
                    else:
                        st.error(f"❌ Falha total para {curr.strftime('%d/%m')}")
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
                        st.text_area("Leitura", r.get('leitura'), height=150, key=f"lei_{m['d_iso']}_{m['type']}")
                    with c2:
                        st.write(f"**Reflexão:** {r.get('reflexao')}")
                        st.write(f"**Aplicação:** {r.get('aplicacao')}")
                        st.write(f"**Oração:** {r.get('oracao')}")
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