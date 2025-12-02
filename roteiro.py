import streamlit as st
import requests
import json
import os
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
    
    # Lógica de regras condicionais para a Leitura
    if reading_type == "1ª Leitura":
        # Regra específica para 1ª Leitura
        regras_leitura_bloco = """O texto bíblico completo. 
        1. INÍCIO OBRIGATÓRIO: Inicie com a fórmula litúrgica do livro (ex: 'Leitura do Livro do Profeta Isaías', 'Leitura do Livro do Gênesis') sem mencionar capítulos e versículos numéricos.
        2. FINAL OBRIGATÓRIO: Termine o texto com a frase exata: 'Palavra do Senhor!'."""
    else:
        # Regra padrão para outros tipos
        regras_leitura_bloco = "O texto bíblico fornecido, LIMPO (sem versículos/cabeçalhos)."

    system_prompt = f"""Você é um assistente litúrgico católico.
    TAREFA: Crie um roteiro de vídeo curto baseado na leitura bíblica ({reading_type}).
    
    ESTRUTURA OBRIGATÓRIA (5 BLOCOS):
    1. hook (5-10s): Frase impactante e curiosa (20-30 palavras).
    2. leitura: {regras_leitura_bloco}
    3. reflexao (20-25s): Ensinamento prático. INÍCIO OBRIGATÓRIO com a palavra "Reflexão:".
    4. aplicacao (20-25s): Dica de ação prática.
    5. oracao (15-20s): Oração curta. INÍCIO OBRIGATÓRIO com: "Vamos orar", "Oremos" ou "Ore comigo".
    
    EXTRA: Identifique PERSONAGENS BÍBLICOS na cena (exceto Jesus/Deus).
    SAÍDA JSON: {{"roteiro": {{"hook": "...", "leitura": "...", "reflexao": "...", "aplicacao": "...", "oracao": "..."}}, "personagens_identificados": ["Nome1"]}}"""
    
    try:
        chat_completion = client.chat.completions.create(
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": f"Texto Base:\n\n{reading_text}"}],
            model="llama-3.3-70b-versatile", response_format={"type": "json_object"}, temperature=0.7)
        return json.loads(chat_completion.choices[0].message.content)
    except Exception as e: st.error(f"Erro Groq ({reading_type}): {e}"); return None

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
    prompts["hook"] = f"Cena Bíblica Cinematográfica realista baseada na leitura: {roteiro_data.get('hook','')}. {desc_biblicos} {style_choice}"
    prompts["leitura"] = f"Cena Bíblica Cinematográfica realista baseada na leitura. Contexto: {roteiro_data.get('leitura','').strip()[:300]}... {desc_biblicos} {style_choice}"
    prompts["reflexao"] = f"Cena Moderna. Jesus conversando amigavelmente com a Pessoa Moderna em um café ou sala de estar. Jesus description: {desc_jesus} Modern Person description: {desc_moderna} {style_choice}"
    prompts["aplicacao"] = f"Cena Moderna. Jesus e a Pessoa Moderna caminhando na cidade/trabalho. Jesus ensinando. Jesus description: {desc_jesus} Modern Person description: {desc_moderna} {style_choice}"
    prompts["oracao"] = f"Cena Moderna. Jesus e a Pessoa Moderna orando juntos, olhos fechados, paz. Jesus description: {desc_jesus} Modern Person description: {desc_moderna} {style_choice}"
    return prompts

def extract_text(obj):
    if not obj: return ""
    if "content_psalm" in obj:
        c = obj["content_psalm"]
        text_part = "\n".join(c) if isinstance(c, list) else str(c)
        refrain = obj.get("response", "")
        return f"{refrain}\n{text_part}"
    return obj.get("text") or obj.get("texto") or ""

def main():
    st.sidebar.title("⚙️ Configurações")
    char_db = load_characters()
    tab_roteiro, tab_personagens = st.tabs(["📜 Roteiros (Multi)", "👥 Personagens"])
    
    if 'daily_readings' not in st.session_state: st.session_state['daily_readings'] = []
    if 'generated_scripts' not in st.session_state: st.session_state['generated_scripts'] = []

    with tab_roteiro:
        st.header("1. Buscar Liturgia")
        date_sel = st.date_input("Data", value=date.today())
        
        if st.button("Buscar Leituras"):
            with st.spinner("Conectando à Vercel..."):
                data = fetch_liturgia(date_sel)
                if data:
                    st.session_state['daily_readings'] = []
                    st.session_state['generated_scripts'] = []
                    
                    today_data = data.get('today', {})
                    readings = today_data.get('readings', {}) or data.get('readings', {})
                    
                    def add_reading(key, type_name):
                        if key in readings:
                            txt = extract_text(readings[key])
                            ref = readings[key].get('title', type_name)
                            if txt.strip():
                                st.session_state['daily_readings'].append({"type": type_name, "text": txt, "ref": ref, "date_display": date_sel.strftime("%d/%m/%Y")})

                    add_reading('first_reading', '1ª Leitura')
                    add_reading('psalm', 'Salmo')
                    add_reading('second_reading', '2ª Leitura')
                    add_reading('gospel', 'Evangelho')
                    
                    if st.session_state['daily_readings']: st.success(f"{len(st.session_state['daily_readings'])} leituras encontradas!")
                    else: st.warning("Nenhuma leitura extraída.")

        if st.session_state['daily_readings']:
            st.markdown("---")
            st.write("📖 **Leituras Disponíveis:**")
            for r in st.session_state['daily_readings']:
                with st.expander(f"{r['type']}: {r['ref']}"): st.text(r['text'])

            st.markdown("---")
            st.header("2. Gerar Roteiros (Batch)")
            
            if st.button("✨ Gerar Roteiro para TODAS as Leituras"):
                st.session_state['generated_scripts'] = []
                progress_bar = st.progress(0)
                total = len(st.session_state['daily_readings'])
                
                with st.status("Gerando roteiros...", expanded=True) as status:
                    for idx, reading in enumerate(st.session_state['daily_readings']):
                        st.write(f"Processando: {reading['type']}...")
                        ai_result = generate_script_and_identify_chars(reading['text'], reading['type'])
                        
                        if ai_result:
                            identified = ai_result.get('personagens_identificados', [])
                            new_chars_found = False
                            for char_name in identified:
                                if char_name not in char_db:
                                    st.write(f"🎨 Criando personagem: {char_name}")
                                    char_db[char_name] = generate_character_description(char_name)
                                    new_chars_found = True
                            if new_chars_found: save_characters(char_db)

                            st.session_state['generated_scripts'].append({
                                "meta": reading,
                                "roteiro": ai_result.get('roteiro', {}),
                                "chars": identified
                            })
                        progress_bar.progress((idx + 1) / total)
                    status.update(label="Geração Concluída!", state="complete", expanded=False)

        if st.session_state['generated_scripts']:
            st.markdown("---")
            st.header("3. Enviar Jobs (Drive)")
            
            for script_obj in st.session_state['generated_scripts']:
                meta = script_obj['meta']
                rot = script_obj['roteiro']
                with st.expander(f"✅ Roteiro Pronto: {meta['type']} ({meta['ref']})"):
                    c1, c2 = st.columns(2)
                    with c1:
                        st.info(f"**Hook:** {rot.get('hook', '❌ FALTOU')}")
                        st.text_area("Leitura", rot.get('leitura', '❌ FALTOU'), height=100, key=f"lei_{meta['type']}")
                    with c2:
                        st.write(f"**Reflexão:** {rot.get('reflexao', '❌ FALTOU')}")
                        st.write(f"**Aplicação:** {rot.get('aplicacao', '❌ FALTOU')}")
                        st.write(f"**Oração:** {rot.get('oracao', '❌ FALTOU')}")
            
            if st.button("🚀 Enviar TODOS para o Drive"):
                progress_bar_send = st.progress(0)
                total_send = len(st.session_state['generated_scripts'])
                success_count = 0
                
                for idx, script_obj in enumerate(st.session_state['generated_scripts']):
                    meta = script_obj['meta']
                    rot = script_obj['roteiro']
                    prompts_finais = build_scene_prompts(rot, script_obj['chars'], char_db, STYLE_SUFFIX)
                    ref_final = f"{meta['type']} - {meta['ref']}"
                    
                    payload = {
                        "meta_dados": {"data": meta['date_display'], "ref": ref_final},
                        "roteiro": {k: {"text": rot.get(k, ''), "prompt": prompts_finais.get(k, '')} for k in ["hook", "leitura", "reflexao", "aplicacao", "oracao"]},
                        "assets": []
                    }
                    
                    res = send_to_gas(payload)
                    if res and res.get('status') == 'success': success_count += 1
                    progress_bar_send.progress((idx + 1) / total_send)
                
                if success_count == total_send: st.balloons(); st.success(f"{success_count} jobs enviados com sucesso!")
                else: st.warning(f"{success_count}/{total_send} jobs enviados. Verifique logs.")

    with tab_personagens:
        st.header("Personagens")
        for name, desc in char_db.items():
            with st.expander(f"👤 {name}", expanded=False):
                new_desc = st.text_area(f"Desc ({name})", value=desc, height=100)
                if st.button(f"Salvar {name}"): char_db[name] = new_desc; save_characters(char_db); st.success("Ok!")
                if name not in FIXED_CHARACTERS:
                    if st.button(f"Excluir {name}"): del char_db[name]; save_characters(char_db); st.rerun()
        st.divider()
        n = st.text_input("Nome"); d = st.text_area("Descrição")
        if st.button("Criar") and n: char_db[n] = d; save_characters(char_db); st.success("Criado!"); st.rerun()

if __name__ == "__main__": main()
