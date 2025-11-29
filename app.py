# app.py — Gerador de Evangelho (COMPLETO v23.0)
# Features: REGEX BLINDADO PARA ROTEIRO, Legendas, Música, Efeitos, Upload, Editor Full
import os
import re
import json
import time
import tempfile
import traceback
import subprocess
import urllib.parse
import random
import textwrap
from io import BytesIO
from datetime import date
from typing import List, Optional, Tuple, Dict
import base64

import requests
from PIL import Image, ImageDraw, ImageFont
import streamlit as st

# Force ffmpeg path for imageio if needed (Streamlit Cloud)
os.environ.setdefault("IMAGEIO_FFMPEG_EXE", "/usr/bin/ffmpeg")

# Arquivos de configuração persistentes
CONFIG_FILE = "overlay_config.json"
SAVED_MUSIC_FILE = "saved_bg_music.mp3"

# =========================
# Page config
# =========================
st.set_page_config(
    page_title="Gerador de Evangelho",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =========================
# Configurações e Persistência
# =========================
def load_config():
    default_settings = {
        "line1_y": 40, "line1_size": 40, "line1_font": "Padrão (Sans)", "line1_anim": "Estático",
        "line2_y": 90, "line2_size": 28, "line2_font": "Padrão (Sans)", "line2_anim": "Estático",
        "line3_y": 130, "line3_size": 24, "line3_font": "Padrão (Sans)", "line3_anim": "Estático",
        "effect_type": "Zoom In (Ken Burns)", "effect_speed": 3,
        "trans_type": "Fade (Escurecer)", "trans_dur": 0.5,
        "music_vol": 0.15,
        "sub_enabled": False, "sub_font": "Padrão (Sans)", "sub_size": 45, "sub_y": 100,
        "sub_color": "#FFFFFF", "sub_outline_color": "#000000", "sub_karaoke": False, "sub_bg_box": False
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                saved = json.load(f)
                default_settings.update(saved)
                return default_settings
        except: pass
    return default_settings

def save_config(settings):
    try:
        with open(CONFIG_FILE, "w") as f: json.dump(settings, f)
        return True
    except Exception as e: st.error(f"Erro config: {e}"); return False

def save_music_file(file_bytes):
    try:
        with open(SAVED_MUSIC_FILE, "wb") as f: f.write(file_bytes)
        return True
    except: return False

def delete_music_file():
    try:
        if os.path.exists(SAVED_MUSIC_FILE): os.remove(SAVED_MUSIC_FILE)
        return True
    except: return False

# =========================
# Groq Init
# =========================
_client = None
def inicializar_groq():
    global _client
    if _client is None:
        try:
            from groq import Groq
            api_key = st.secrets.get("GROQ_API_KEY") or os.getenv("GROQ_API_KEY")
            if not api_key: st.error("Configure GROQ_API_KEY"); st.stop()
            _client = Groq(api_key=api_key)
        except Exception as e: st.error(f"Erro Groq: {e}"); st.stop()
    return _client

@st.cache_data
def inicializar_personagens():
    return {
        "Jesus": "homem de 33 anos, pele morena clara, traços judaicos, túnica branca, manto azul, sereno",
        "São Pedro": "homem robusto 50 anos, barba grisalha, túnica simples",
        "São João": "jovem 25 anos, sem barba, fisionomia suave"
    }

# =========================
# Lógica de Roteiro (NOVA & ROBUSTA)
# =========================
def extrair_conteudo_seguro(texto_completo, tag_alvo):
    """
    Extrai conteúdo de forma robusta, ignorando formatação markdown (**, ##)
    e parando na próxima tag conhecida.
    """
    # Lista de todas as tags possíveis para servir de "ponto de parada"
    todas_tags = [
        "HOOK", "REFLEXÃO", "REFLEXAO", "APLICAÇÃO", "APLICACAO", "ORAÇÃO", "ORACAO",
        "PROMPT_HOOK", "PROMPT_REFLEXÃO", "PROMPT_REFLEXAO", "PROMPT_APLICACAO", "PROMPT_APLICAÇÃO",
        "PROMPT_ORAÇÃO", "PROMPT_ORACAO", "PROMPT_LEITURA", "PROMPT_GERAL"
    ]
    
    # 1. Encontrar onde começa a tag alvo (ignorando case e chars especiais antes/depois)
    # Ex: aceita "HOOK:", "**HOOK**:", "### HOOK"
    padrao_inicio = re.compile(rf"(?:^|\n|#|\*)\s*{tag_alvo}\s*(?:\*|#)*\s*:?\s*", re.IGNORECASE)
    match_inicio = padrao_inicio.search(texto_completo)
    
    if not match_inicio:
        return ""
    
    inicio_conteudo = match_inicio.end()
    texto_restante = texto_completo[inicio_conteudo:]
    
    # 2. Encontrar onde termina (no início de qualquer outra tag da lista)
    menor_indice = len(texto_restante)
    
    for tag in todas_tags:
        # Não parar na própria tag se ela aparecer de novo (raro, mas previne erro)
        if tag == tag_alvo: continue
        
        # Procura a próxima tag no texto restante
        padrao_fim = re.compile(rf"(?:^|\n|#|\*)\s*{tag}", re.IGNORECASE)
        match_fim = padrao_fim.search(texto_restante)
        
        if match_fim:
            if match_fim.start() < menor_indice:
                menor_indice = match_fim.start()
    
    return texto_restante[:menor_indice].strip()

def gerar_roteiro_com_prompts_groq(texto_evangelho, referencia, personagens):
    client = inicializar_groq()
    p_str = json.dumps(personagens, ensure_ascii=False)
    
    # Prompt reforçado para estrutura
    sys_msg = f"""Você é um roteirista católico. Crie um roteiro devocional.
PERSONAGENS: {p_str}
ESTRUTURA OBRIGATÓRIA (Use exatamente estes rótulos):
HOOK: (Frase curta impactante)
PROMPT_HOOK: (Descrição visual)
REFLEXÃO: (Explicação teológica breve)
PROMPT_REFLEXÃO: (Descrição visual)
APLICAÇÃO: (Como viver isso hoje)
PROMPT_APLICACAO: (Descrição visual)
ORAÇÃO: (Prece curta)
PROMPT_ORACAO: (Descrição visual)
PROMPT_LEITURA: (Cena para o momento da leitura do evangelho)
PROMPT_GERAL: (Cena para capa/thumbnail)"""

    try:
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": f"Evangelho: {referencia}\n\n{texto_evangelho[:2500]}"}
            ],
            temperature=0.6,
            max_tokens=1500
        )
        raw = resp.choices[0].message.content
        
        # Extração usando a nova função robusta
        dados = {
            "hook": extrair_conteudo_seguro(raw, "HOOK"),
            "reflexão": extrair_conteudo_seguro(raw, "REFLEXÃO") or extrair_conteudo_seguro(raw, "REFLEXAO"),
            "aplicação": extrair_conteudo_seguro(raw, "APLICAÇÃO") or extrair_conteudo_seguro(raw, "APLICACAO"),
            "oração": extrair_conteudo_seguro(raw, "ORAÇÃO") or extrair_conteudo_seguro(raw, "ORACAO"),
            "prompt_hook": extrair_conteudo_seguro(raw, "PROMPT_HOOK"),
            "prompt_reflexão": extrair_conteudo_seguro(raw, "PROMPT_REFLEXÃO") or extrair_conteudo_seguro(raw, "PROMPT_REFLEXAO"),
            "prompt_aplicacao": extrair_conteudo_seguro(raw, "PROMPT_APLICACAO") or extrair_conteudo_seguro(raw, "PROMPT_APLICAÇÃO"),
            "prompt_oração": extrair_conteudo_seguro(raw, "PROMPT_ORACAO") or extrair_conteudo_seguro(raw, "PROMPT_ORAÇÃO"),
            "prompt_leitura": extrair_conteudo_seguro(raw, "PROMPT_LEITURA"),
            "prompt_geral": extrair_conteudo_seguro(raw, "PROMPT_GERAL")
        }
        
        # Validação simples
        if not dados["hook"]: return None
        return dados
        
    except Exception as e:
        st.error(f"Erro Roteiro: {e}")
        return None

# =========================
# Helpers Diversos
# =========================
def limpar_texto_evangelho(t): return re.sub(r"\d+", "", t.replace("\n", " ")).strip() if t else ""

def extrair_referencia_biblica(t):
    if not t: return None
    t_lower = t.lower()
    nomes = {"mateus": "Mateus", "marcos": "Marcos", "lucas": "Lucas", "joão": "João", "joao": "João"}
    ev = None
    for k, v in nomes.items():
        if k in t_lower: ev = v; break
    if not ev:
        m = re.search(r"(?:São|S\.|Santo)\s*([A-Za-zÁ-Ú]+)", t, re.IGNORECASE)
        if m and len(m.group(1))>2: ev = m.group(1)
    
    m_num = re.search(r"(\d{1,3})[^\d]*(\d+(?:[-–]\d+)?)", t)
    if m_num: return {"evangelista": ev, "capitulo": m_num.group(1), "versiculos": m_num.group(2)}
    return None

def formatar_referencia_curta(ref): return f"{ref['evangelista']} {ref['capitulo']},{ref['versiculos']}" if ref else ""

def montar_leitura(texto, ref):
    if ref: return f"Evangelho de Jesus Cristo segundo {ref['evangelista']}. {texto} Palavra da Salvação."
    return f"Proclamação do Evangelho. {texto} Palavra da Salvação."

# =========================
# APIs Externas
# =========================
def buscar_liturgia_api1(d):
    try:
        r = requests.get(f"https://api-liturgia-diaria.vercel.app/?date={d}", timeout=5)
        r.raise_for_status(); j = r.json()
        g = j.get("today", {}).get("readings", {}).get("gospel", {})
        return {"texto": limpar_texto_evangelho(g.get("text","")), "ref_biblica": extrair_referencia_biblica(g.get("title",""))} if g else None
    except: return None

def obter_evangelho(d):
    res = buscar_liturgia_api1(d)
    if res: return res
    # Fallback simples se precisar
    st.error("Erro ao buscar liturgia"); return None

# =========================
# Multimídia
# =========================
def gerar_audio_gtts(texto):
    if not texto: return None
    try:
        from gtts import gTTS
        bio = BytesIO(); gTTS(texto, lang="pt").write_to_fp(bio); bio.seek(0)
        return bio
    except: return None

def get_res_params(c):
    if "9:16" in c: return 720, 1280
    if "16:9" in c: return 1280, 720
    return 1024, 1024

def gerar_imagem_pollinations(prompt, w, h, model="flux"):
    p = urllib.parse.quote(prompt[:800])
    s = random.randint(0, 9999)
    u = f"https://image.pollinations.ai/prompt/{p}?model={model}&width={w}&height={h}&seed={s}&nologo=true"
    try:
        r = requests.get(u, timeout=30); r.raise_for_status()
        return BytesIO(r.content)
    except: return None

def gerar_imagem_google(prompt, ratio):
    k = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not k: return None
    u = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-001:predict?key={k}"
    try:
        r = requests.post(u, json={"instances":[{"prompt":prompt}], "parameters":{"sampleCount":1, "aspectRatio":ratio}}, headers={"Content-Type":"application/json"}, timeout=30)
        r.raise_for_status()
        return BytesIO(base64.b64decode(r.json()["predictions"][0]["bytesBase64Encoded"]))
    except: return None

def despachar_imagem(prompt, motor, res_str):
    w, h = get_res_params(res_str)
    ratio = "9:16" if "9:16" in res_str else "16:9" if "16:9" in res_str else "1:1"
    if "Google" in motor: return gerar_imagem_google(prompt, ratio)
    return gerar_imagem_pollinations(prompt, w, h, "flux" if "Flux" in motor else "turbo")

# =========================
# FFmpeg & System
# =========================
import shutil
def has_ffmpeg(): return shutil.which("ffmpeg") is not None
def run_ffmpeg(cmd): subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def get_duration(path):
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path], stdout=subprocess.PIPE)
        return float(r.stdout.decode().strip())
    except: return 5.0

def resolve_font(name, upload):
    if name == "Upload Personalizada" and upload:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ttf") as t: t.write(upload.getvalue()); return t.name
    sys_fonts = {
        "Padrão (Sans)": ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "arial.ttf"],
        "Serif": ["/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf", "times.ttf"],
        "Monospace": ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", "courier.ttf"]
    }
    for f in sys_fonts.get(name, sys_fonts["Padrão (Sans)"]):
        if os.path.exists(f): return f
    return None

def wrap_text(text, font_path, size, width):
    try: font = ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default()
    except: font = ImageFont.load_default()
    return "\n".join(textwrap.TextWrapper(width=int(width/(size*0.5))).wrap(text))

def sanitize(t): return t.replace(":", "\\:").replace("'", "").replace("\n", " ") if t else ""

# =========================
# UI e Preview
# =========================
def preview_overlay(w, h, texts, font_up, sub_cfg=None):
    img = Image.new("RGB", (w, h), "black")
    d = ImageDraw.Draw(img)
    
    # Overlay Texts
    for t in texts:
        f_path = resolve_font(t["font"], font_up)
        try: font = ImageFont.truetype(f_path, t["size"]) if f_path else ImageFont.load_default()
        except: font = ImageFont.load_default()
        try: tw = d.textlength(t["text"], font)
        except: tw = len(t["text"])*t["size"]*0.5
        d.text(((w-tw)/2, t["y"]), t["text"], font=font, fill=t["color"])
        
    # Subtitles
    if sub_cfg and sub_cfg["enabled"]:
        f_path = resolve_font(sub_cfg["font"], font_up)
        try: font = ImageFont.truetype(f_path, sub_cfg["size"]) if f_path else ImageFont.load_default()
        except: font = ImageFont.load_default()
        lines = ["Legenda de exemplo", "quebra automática"]
        y_base = h - sub_cfg["y"] - (len(lines)*sub_cfg["size"])
        for i, l in enumerate(lines):
            try: tw = d.textlength(l, font)
            except: tw = len(l)*sub_cfg["size"]*0.5
            d.text(((w-tw)/2, y_base + i*sub_cfg["size"]), l, font=font, fill=sub_cfg["color"], stroke_width=2, stroke_fill=sub_cfg["outline"])
            
    b = BytesIO(); img.save(b, "PNG"); b.seek(0)
    return b

# =========================
# APP MAIN
# =========================
st.markdown("<h3 style='text-align: center;'>Gerador de Evangelho</h3>", unsafe_allow_html=True)
st.markdown("---")

# Sidebar
st.sidebar.title("⚙️ Configurações")
eng = st.sidebar.selectbox("Motor Imagem", ["Pollinations Flux (Padrão)", "Pollinations Turbo", "Google Imagen"])
res = st.sidebar.selectbox("Resolução", ["9:16 (Vertical)", "16:9 (Horizontal)", "1:1 (Quadrado)"])
st.sidebar.markdown("---")
f_choice = st.sidebar.selectbox("Fonte Padrão", ["Padrão (Sans)", "Serif", "Monospace", "Upload Personalizada"])
f_up = st.sidebar.file_uploader("Arquivo .ttf", type="ttf") if f_choice == "Upload Personalizada" else None

# Session
if "roteiro_gerado" not in st.session_state: st.session_state.update({"roteiro_gerado": None, "leitura_montada": "", "generated_images": {}, "generated_audios": {}, "final_video": None, "meta": {}, "overlay": load_config()})

t1, t2, t3, t4, t5 = st.tabs(["📖 Roteiro", "🎨 Personagens", "🎚️ Visual", "🎥 Produção", "📊 Histórico"])

# --- ROTEIRO ---
with t1:
    col1, col2 = st.columns(2)
    with col1: d_sel = st.date_input("Data:", date.today())
    with col2: 
        if st.button("🚀 Gerar Roteiro", type="primary"):
            d_str = d_sel.strftime("%Y-%m-%d")
            with st.status("Gerando...", expanded=True) as s:
                lit = obter_evangelho(d_str)
                if not lit: s.update(label="Erro API Liturgia", state="error"); st.stop()
                
                chars = inicializar_personagens()
                # Analisar personagens (opcional, pode pular se quiser economizar tokens, mas mantendo para qualidade)
                chars.update(analisar_personagens_groq(lit["texto"], chars))
                
                rot = gerar_roteiro_com_prompts_groq(lit["texto"], lit.get("ref_biblica",""), chars)
                
                if rot:
                    st.session_state["roteiro_gerado"] = rot
                    st.session_state["leitura_montada"] = montar_leitura(lit["texto"], lit.get("ref_biblica"))
                    st.session_state["meta"] = {
                        "data": d_sel.strftime("%d.%m.%Y"),
                        "ref": formatar_referencia_curta(lit.get("ref_biblica"))
                    }
                    s.update(label="Sucesso!", state="complete")
                    st.rerun()
                else:
                    s.update(label="Erro na IA (Roteiro Vazio)", state="error")

    if st.session_state["roteiro_gerado"]:
        r = st.session_state["roteiro_gerado"]
        c1, c2 = st.columns(2)
        with c1: st.markdown("### Hook"); st.info(r.get("hook"))
        with c2: st.markdown("### Leitura"); st.info(st.session_state["leitura_montada"][:150]+"...")

# --- VISUAL ---
with t3:
    col_s, col_p = st.columns(2)
    sets = st.session_state["overlay"]
    
    with col_s:
        st.subheader("Ajustes")
        with st.expander("Legendas", expanded=True):
            sets["sub_enabled"] = st.toggle("Ativar Legendas", sets.get("sub_enabled"))
            if sets["sub_enabled"]:
                sets["sub_size"] = st.slider("Tam", 20, 100, sets.get("sub_size", 45))
                sets["sub_y"] = st.slider("Posição Y", 0, 500, sets.get("sub_y", 100))
                sets["sub_color"] = st.color_picker("Cor", sets.get("sub_color", "#FFFFFF"))
                sets["sub_bg_box"] = st.checkbox("Fundo Box", sets.get("sub_bg_box", False))
        
        with st.expander("Cabeçalho", expanded=False):
            sets["line1_size"] = st.slider("Tam Título", 10, 100, sets.get("line1_size", 40))
            sets["line1_y"] = st.slider("Y Título", 0, 800, sets.get("line1_y", 40))
            
        with st.expander("Efeitos", expanded=False):
            effs = ["Zoom In (Ken Burns)", "Zoom Out", "Estático"]
            idx = effs.index(sets.get("effect_type")) if sets.get("effect_type") in effs else 0
            sets["effect_type"] = st.selectbox("Movimento", effs, index=idx)
            
        if st.button("Salvar Config"): save_config(sets); st.success("Salvo!")

    with col_p:
        st.subheader("Preview")
        w, h = get_res_params(res)
        preview = criar_preview_overlay(
            int(w*0.4), int(h*0.4), 
            [{"text":"EVANGELHO", "size":int(sets["line1_size"]*0.4), "y":int(sets["line1_y"]*0.4), "color":"white", "font":f_choice}],
            f_up, 
            {"enabled": sets["sub_enabled"], "size":int(sets["sub_size"]*0.4), "y":int(sets["sub_y"]*0.4), "color":sets["sub_color"], "outline":"black", "font":f_choice}
        )
        st.image(preview)

# --- PRODUÇÃO ---
with t4:
    if not st.session_state["roteiro_gerado"]: st.warning("Gere o roteiro primeiro."); st.stop()
    rot = st.session_state["roteiro_gerado"]
    
    # Ordem corrigida
    blocos = [
        {"id": "hook", "lbl": "Hook", "txt": rot["hook"], "p": rot["prompt_hook"]},
        {"id": "leitura", "lbl": "Leitura", "txt": st.session_state["leitura_montada"], "p": rot["prompt_leitura"]},
        {"id": "reflexão", "lbl": "Reflexão", "txt": rot["reflexão"], "p": rot["prompt_reflexão"]},
        {"id": "aplicação", "lbl": "Aplicação", "txt": rot["aplicação"], "p": rot["prompt_aplicacao"]},
        {"id": "oração", "lbl": "Oração", "txt": rot["oração"], "p": rot["prompt_oração"]},
        {"id": "thumbnail", "lbl": "Thumb", "txt": None, "p": rot["prompt_geral"]}
    ]
    
    # Bulk Buttons
    b1, b2 = st.columns(2)
    if b1.button("🔊 Gerar Todos Áudios"):
        with st.status("Gerando...") as s:
            for b in blocos:
                if b["txt"]: st.session_state["generated_audios"][b["id"]] = gerar_audio_gtts(b["txt"])
            s.update(label="Pronto!", state="complete"); st.rerun()
            
    if b2.button("✨ Gerar Todas Imagens"):
        with st.status("Gerando...") as s:
            for b in blocos:
                if b["p"]: st.session_state["generated_images"][b["id"]] = despachar_imagem(b["p"], eng, res)
            s.update(label="Pronto!", state="complete"); st.rerun()

    # Cards Editor
    for b in blocos:
        with st.container(border=True):
            c_txt, c_img = st.columns([1, 1])
            with c_txt:
                st.subheader(b["lbl"])
                if b["txt"]: st.caption(b["txt"][:100]+"...")
                if st.button("Gerar Áudio", key=f"au_{b['id']}"):
                    st.session_state["generated_audios"][b["id"]] = gerar_audio_gtts(b["txt"]); st.rerun()
                if b["id"] in st.session_state["generated_audios"]: st.audio(st.session_state["generated_audios"][b["id"]])
            
            with c_img:
                if st.button("Gerar Imagem", key=f"im_{b['id']}"):
                    st.session_state["generated_images"][b["id"]] = despachar_imagem(b["p"], eng, res); st.rerun()
                
                up = st.file_uploader("Upload", key=f"up_{b['id']}")
                if up: st.session_state["generated_images"][b["id"]] = up
                
                if b["id"] in st.session_state["generated_images"]:
                    st.image(st.session_state["generated_images"][b["id"]], width=100)

    # Render
    st.divider()
    mus_up = st.file_uploader("Música Fundo", type="mp3")
    if mus_up and st.button("Salvar Padrão"): save_music_file(mus_up.getvalue()); st.success("Salvo!")
    
    if st.button("🎬 RENDERIZAR VÍDEO FINAL", type="primary"):
        if not has_ffmpeg(): st.error("FFmpeg não encontrado"); st.stop()
        
        with st.status("Processando...", expanded=True) as status:
            tmp = tempfile.mkdtemp()
            w, h = get_res_params(res)
            font_p = resolve_font(f_choice, f_up)
            clips = []
            
            # Títulos mapeados
            titles = {"hook": "EVANGELHO", "leitura": "EVANGELHO", "reflexão": "REFLEXÃO", "aplicação": "APLICAÇÃO", "oração": "ORAÇÃO"}
            
            for b in blocos:
                if b["id"] == "thumbnail": continue
                img = st.session_state["generated_images"].get(b["id"])
                aud = st.session_state["generated_audios"].get(b["id"])
                
                if not img or not aud: continue
                
                # Paths
                ip = os.path.join(tmp, f"{b['id']}.png"); ap = os.path.join(tmp, f"{b['id']}.mp3"); op = os.path.join(tmp, f"{b['id']}.mp4")
                
                # Write files
                if isinstance(img, BytesIO): img.seek(0);  open(ip, "wb").write(img.read())
                else: open(ip, "wb").write(img.getvalue())
                aud.seek(0); open(ap, "wb").write(aud.read())
                
                dur = get_duration(ap)
                
                # Filters
                vf = []
                # Zoom
                vf.append(f"zoompan=z='min(zoom+0.0015,1.5)':d={int(dur*25)}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}")
                # Fade
                vf.append(f"fade=t=in:st=0:d=0.5,fade=t=out:st={dur-0.5}:d=0.5")
                
                # Overlay Header
                t_tit = titles.get(b["id"], "")
                t_dt = st.session_state["meta"].get("data","")
                t_ref = st.session_state["meta"].get("ref","")
                if font_p:
                    vf.append(f"drawtext=fontfile='{font_p}':text='{sanitize(t_tit)}':fontcolor=white:fontsize={sets['line1_size']}:x=(w-text_w)/2:y={sets['line1_y']}")
                    vf.append(f"drawtext=fontfile='{font_p}':text='{sanitize(t_dt)}':fontcolor=white:fontsize={sets['line2_size']}:x=(w-text_w)/2:y={sets['line2_y']}")
                    vf.append(f"drawtext=fontfile='{font_p}':text='{sanitize(t_ref)}':fontcolor=white:fontsize={sets['line3_size']}:x=(w-text_w)/2:y={sets['line3_y']}")
                
                # Subtitles
                if sets["sub_enabled"] and font_p and b["txt"]:
                    wrapped = wrap_text(b["txt"], font_p, sets["sub_size"], w*0.9)
                    clean_sub = sanitize(wrapped)
                    box = ":box=1:boxcolor=black@0.6:boxborderw=10" if sets["sub_bg_box"] else ""
                    y_inv = h - sets["sub_y"]
                    vf.append(f"drawtext=fontfile='{font_p}':text='{clean_sub}':fontcolor={sets['sub_color']}:fontsize={sets['sub_size']}:x=(w-text_w)/2:y={y_inv}{box}")

                run_ffmpeg(["ffmpeg", "-y", "-loop", "1", "-i", ip, "-i", ap, "-vf", ",".join(vf), "-c:v", "libx264", "-t", str(dur), "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", op])
                clips.append(op)
            
            if clips:
                # Concat
                lst = os.path.join(tmp, "list.txt")
                with open(lst, "w") as f: 
                    for c in clips: f.write(f"file '{c}'\n")
                
                v_raw = os.path.join(tmp, "raw.mp4"); v_final = os.path.join(tmp, "final.mp4")
                run_ffmpeg(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", v_raw])
                
                # Music Mix
                mus = None
                if mus_up: mus_p = os.path.join(tmp, "bg.mp3"); open(mus_p, "wb").write(mus_up.getvalue()); mus=mus_p
                elif os.path.exists(SAVED_MUSIC_FILE): mus = SAVED_MUSIC_FILE
                
                if mus:
                    run_ffmpeg(["ffmpeg", "-y", "-i", v_raw, "-stream_loop", "-1", "-i", mus, "-filter_complex", f"[1:a]volume={sets['music_vol']}[bg];[0:a][bg]amix=inputs=2:duration=first[a]", "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-shortest", v_final])
                else:
                    os.rename(v_raw, v_final)
                
                with open(v_final, "rb") as f: st.session_state["video_final_bytes"] = BytesIO(f.read())
                status.update(label="Vídeo Pronto!", state="complete")
            else:
                status.update(label="Falta conteúdo (imagens/audio)", state="error")

    if st.session_state.get("video_final_bytes"):
        st.video(st.session_state["video_final_bytes"])
        st.download_button("Baixar MP4", st.session_state["video_final_bytes"], "video.mp4", "video/mp4")