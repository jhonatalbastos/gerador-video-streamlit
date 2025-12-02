import streamlit as st
import requests
import json
import os
import re
import calendar
from datetime import date, timedelta
from groq import Groq
from bs4 import BeautifulSoup

# ==========================================
# CONFIGURAÇÕES E CONSTANTES
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
# FUNÇÕES DE PERSISTÊNCIA
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
    custom = load_json(CHARACTERS_FILE)
    all_chars = FIXED_CHARACTERS.copy()
    all_chars.update(custom)
    return all_chars

def save_characters(data): save_json(CHARACTERS_FILE, data)

def load_history(): return load_json(HISTORY_FILE)

def update_history_bulk(dates_list):
    hist = load_history()
    updated = False
    for d in dates_list:
        if d not in hist:
            hist.append(d)
            updated = True
    if updated:
        hist.sort()
        save_json(HISTORY_FILE, hist)

# ==========================================
# SERVIÇOS EXTERNOS (GROQ, API, SCRAPER)
# ==========================================

def get_groq_client():
    api_key = st.secrets.get("GROQ_API_KEY") or os.getenv("GROQ_API_KEY")
    if not api_key: st.error("❌ GROQ_API_KEY não encontrada."); st.stop()
    return Groq(api_key=api_key)

def fetch_liturgia_cancaonova(date_obj):
    """Fallback: Busca liturgia no site da Canção Nova se a API principal falhar."""
    date_str = date_obj.strftime("%d-%m-%Y") # Formato da URL CN
    url = f"https://liturgia.cancaonova.com/pb/liturgia/{date_str}/"
    
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code != 200:
            return None

        soup = BeautifulSoup(response.content, 'html.parser')
        entry_content = soup.find('div', class_='entry-content')
        
        if not entry_content:
            return None

        # Estrutura de retorno compatível com a API Vercel
        full_text = entry_content.get_text("\n")
        
        # Tentativa simples de separação por palavras-chave
        readings = {}
        
        # Regex para encontrar blocos (Lógica aproximada)
        # Tenta achar onde começa cada parte
        idx_1a = re.search(r'(1ª Leitura|Primeira Leitura)', full_text, re.IGNORECASE)
        idx_salmo = re.search(r'(Salmo|Salmo Responsorial)', full_text, re.IGNORECASE)
        idx_2a = re.search(r'(2ª Leitura|Segunda Leitura)', full_text, re.IGNORECASE)
        idx_evang = re.search(r'(Evangelho)', full_text, re.IGNORECASE)

        # Helper para extrair texto entre índices
        def get_chunk(start_match, end_match, text):
            if not start_match: return ""
            start = start_match.end()
            end = end_match.start() if end_match else len(text)
            return text[start:end].strip()

        # Monta o objeto readings
        if idx_1a:
            readings['first_reading'] = {'text': get_chunk(idx_1a, idx_salmo, full_text), 'title': '1ª Leitura (Backup)'}
        
        if idx_salmo:
            # O salmo vai até a 2ª leitura ou Evangelho
            end_salmo = idx_2a if idx_2a else idx_evang
            readings['psalm'] = {'text': get_chunk(idx_salmo, end_salmo, full_text), 'title': 'Salmo (Backup)'}
            
        if idx_2a:
            readings['second_reading'] = {'text': get_chunk(idx_2a, idx_evang, full_text), 'title': '2ª Leitura (Backup)'}
            
        if idx_evang:
            readings['gospel'] = {'text': full_text[idx_evang.end():].strip(), 'title': 'Evangelho (Backup)'}

        if not readings:
            # Se falhar a separação, retorna tudo no Evangelho para não perder o dia
            readings['gospel'] = {'text': full_text[:2000], 'title': 'Leitura Completa (Backup - Falha na Separação)'}

        return {'readings': readings, 'source': 'Backup Canção Nova'}

    except Exception as e:
        print(f"Erro no backup Canção Nova: {e}")
        return None

def fetch_liturgia(date_obj):
    # 1. Tenta API Principal (Vercel)
    url_vercel = f"https://api-liturgia-diaria.vercel.app/?date={date_obj.strftime('%Y-%m-%d')}".strip()
    try:
        resp = requests.get(url_vercel, timeout=10)
        if resp.status_code == 200:
            return resp.json()
        else:
            print(f"Erro API Vercel ({resp.status_code}). Tentando backup...")
    except Exception as e:
        print(f"Exceção API Vercel: {e}. Tentando backup...")

    # 2. Tenta Backup (Canção Nova)
    st.toast(f"Usando fonte de backup para {date_obj.strftime('%d/%m')}...", icon="⚠️")
    return fetch_liturgia_cancaonova(date_obj)

def send_to_gas(payload):
    gas_url = st.secrets.get("GAS_SCRIPT_URL") or os.getenv("GAS_SCRIPT_URL")
    if not gas_url: st.error("❌ GAS_SCRIPT_URL não encontrada."); return None
    try:
        resp = requests.post(f"{gas_url}?action=generate_job", json=payload)
        return resp.json() if resp.status_code == 200 else None
    except Exception as e: st.error(f"Erro GAS: {e}"); return None

# ==========================================
# LÓGICA DE IA (GROQ) E PROCESSAMENTO
# ==========================================

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
    ESTRUTURA: 
    1. hook (5-10s): Frase impactante (20-30 palavras). FINAL OBRIGATÓRIO: Adicione um breve CTA pedindo para comentar de qual cidade a pessoa está assistindo.
    2. leitura: {regras}
    3. reflexao (20-25s): Inicie com "Reflexão:".
    4. aplicacao (20-25s).
    5. oracao (15-20s): Inicie com "Vamos orar"/"Oremos"/"Ore comigo". FIM: "Amém!".
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

# ==========================================
# INTERFACE GRÁFICA
# ==========================================

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
    st.sidebar.title("⚙️ Config")
    char_db = load_characters()
    history = load_history()
    render_calendar(history)
    
    st.sidebar.markdown("---")
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
        
        if st.button("Buscar Leituras (Intervalo)"):
            if dt_fim < dt_ini: st.error("Data final menor que inicial"); st.stop()
            st.session_state['daily'] = []
            st.session_state['scripts'] = []
            
            with st.status("Baixando liturgias...", expanded=True) as status:
                curr = dt_ini
                count = 0
                while curr <= dt_fim:
                    st.write(f"Baixando: {curr.strftime('%d/%m/%Y')}")
                    # Chama função que tem o fallback embutido
                    data = fetch_liturgia(curr)
                    if data:
                        # Adaptação para estrutura da API Vercel OU do Backup Canção Nova
                        rds = data.get('today', {}).get('readings', {}) or data.get('readings', {})
                        
                        def add(k, t):
                            if k in rds:
                                txt, ref = extract(rds[k]), rds[k].get('title', t)
                                if txt.strip(): st.session_state['daily'].append({"type": t, "text": txt, "ref": ref, "d_show": curr.strftime("%d/%m/%Y"), "d_iso": curr.strftime("%Y-%m-%d")})
                        
                        add('first_reading', '1ª Leitura')
                        add('psalm', 'Salmo')
                        add('second_reading', '2ª Leitura')
                        add('gospel', 'Evangelho')
                        count += 1
                    else:
                        st.error(f"Falha ao obter liturgia para {curr.strftime('%d/%m')}.")
                    curr += timedelta(days=1)
                status.update(label=f"Concluído! {len(st.session_state['daily'])} leituras em {count} dias.", state="complete")

        if st.session_state['daily']:
            st.divider(); st.write(f"📖 **{len(st.session_state['daily'])} Leituras Encontradas**")
            with st.expander("Ver lista de leituras"):
                for r in st.session_state['daily']: st.text(f"{r['d_show']} - {r['type']}: {r['ref']}")
            
            st.divider(); st.header("2. Gerar Roteiros")
            if st.button("✨ Gerar Tudo (Massa)"):
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
                st.warning(f"⚠️ Datas já enviadas: {', '.join(already_sent)}")
                force = st.checkbox("Confirmar envio duplicado")
            else: force = True

            st.write("▼ **Pré-visualização e Prompts:**")
            
            for s in st.session_state['scripts']:
                m, r = s['meta'], s['roteiro']
                prompts_preview = build_prompts(r, s['chars'], char_db, STYLE_SUFFIX)
                
                with st.expander(f"✅ {m['d_show']} - {m['type']} ({m['ref']})"):
                    c1, c2 = st.columns(2)
                    with c1: 
                        st.info(f"**Hook:** {r.get('hook')}")
                        st.text_area("Leitura", r.get('leitura'), height=150, key=f"lei_{m['d_iso']}_{m['type']}")
                    with c2:
                        st.write(f"**Reflexão:** {r.get('reflexao')}")
                        st.write(f"**Aplicação:** {r.get('aplicacao')}")
                        st.write(f"**Oração:** {r.get('oracao')}")
                    
                    st.markdown("---")
                    st.caption("🎨 Prompts de Imagem Gerados:")
                    st.code(f"HOOK: {prompts_preview.get('hook')}", language="text")
                    st.code(f"LEITURA: {prompts_preview.get('leitura')}", language="text")
                    st.code(f"REFLEXÃO: {prompts_preview.get('reflexao')}", language="text")
                    st.code(f"APLICAÇÃO: {prompts_preview.get('aplicacao')}", language="text")
                    st.code(f"ORAÇÃO: {prompts_preview.get('oracao')}", language="text")

            if st.button("🚀 Enviar Lote para Drive", disabled=not force):
                prog, cnt = st.progress(0), 0
                sent_dates = set()
                for i, s in enumerate(st.session_state['scripts']):
                    m, r = s['meta'], s['roteiro']
                    prompts = build_prompts(r, s['chars'], char_db, STYLE_SUFFIX)
                    pld = {
                        "meta_dados": {"data": m['d_show'], "ref": f"{m['type']} - {m['ref']}"},
                        "roteiro": {k: {"text": r.get(k,''), "prompt": prompts.get(k,'')} for k in ["hook", "leitura", "reflexao", "aplicacao", "oracao"]},
                        "assets": []
                    }
                    if send_to_gas(pld): 
                        cnt += 1
                        sent_dates.add(m['d_iso'])
                    prog.progress((i+1)/len(st.session_state['scripts']))
                
                if cnt > 0:
                    update_history_bulk(list(sent_dates))
                    st.balloons(); st.success(f"{cnt} jobs enviados! Histórico atualizado."); st.rerun()
                else: st.error("Nenhum job enviado.")

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
