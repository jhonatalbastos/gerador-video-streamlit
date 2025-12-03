import streamlit as st
import os
import json

# Configuração da Página Inicial
st.set_page_config(
    page_title="Monetiza Studio - Hub",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Estilos CSS para deixar o Hub bonito
st.markdown("""
<style>
    .main-header {
        font-size: 3rem;
        color: #4F46E5;
        text-align: center;
        margin-bottom: 1rem;
    }
    .sub-header {
        font-size: 1.2rem;
        color: #6B7280;
        text-align: center;
        margin-bottom: 3rem;
    }
    .card {
        background-color: #ffffff;
        padding: 2rem;
        border-radius: 1rem;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
        border: 1px solid #E5E7EB;
        text-align: center;
        height: 100%;
        transition: transform 0.2s;
    }
    .card:hover {
        transform: translateY(-5px);
        border-color: #4F46E5;
    }
    .step-number {
        font-size: 4rem;
        font-weight: bold;
        color: #E0E7FF;
        line-height: 1;
    }
    .step-title {
        font-size: 1.5rem;
        font-weight: bold;
        color: #1F2937;
        margin-top: -1rem;
        margin-bottom: 1rem;
    }
    .step-desc {
        color: #4B5563;
        font-size: 0.9rem;
    }
</style>
""", unsafe_allow_html=True)

# Cabeçalho
st.markdown('<h1 class="main-header">Monetiza Studio</h1>', unsafe_allow_html=True)
st.markdown('<p class="sub-header">Central de Automação de Vídeos Litúrgicos</p>', unsafe_allow_html=True)

# Métricas Rápidas (Lendo dos arquivos JSON da raiz)
col_m1, col_m2 = st.columns(2)

total_chars = 0
last_history = "Nenhum"

if os.path.exists("characters_db.json"):
    try:
        with open("characters_db.json", "r") as f:
            chars = json.load(f)
            total_chars = len(chars) + 2 # +2 fixos
    except: pass

if os.path.exists("history_db.json"):
    try:
        with open("history_db.json", "r") as f:
            hist = json.load(f)
            if hist: last_history = hist[-1]
    except: pass

with col_m1:
    st.metric("Personagens no Banco", total_chars)
with col_m2:
    st.metric("Último Job Enviado", last_history)

st.divider()

# Cards de Navegação
c1, c2, c3 = st.columns(3)

with c1:
    st.markdown("""
    <div class="card">
        <div class="step-number">1</div>
        <div class="step-title">Roteiro & IA</div>
        <p class="step-desc">Busca liturgia, gera textos com Groq e define prompts visuais. Envia o Job para o Drive.</p>
    </div>
    """, unsafe_allow_html=True)
    if st.button("Ir para Roteiros ➔", key="btn1", use_container_width=True):
        st.switch_page("pages/1_📝_Roteiro.py")

with c2:
    st.markdown("""
    <div class="card">
        <div class="step-number">2</div>
        <div class="step-title">Produção (AI Studio)</div>
        <p class="step-desc">Interface visual para gerar imagens e áudios usando Gemini. Finaliza os assets do Job.</p>
    </div>
    """, unsafe_allow_html=True)
    if st.button("Ir para Produção ➔", key="btn2", use_container_width=True):
        st.switch_page("pages/2_🎨_Producao.py")

with c3:
    st.markdown("""
    <div class="card">
        <div class="step-number">3</div>
        <div class="step-title">Montagem Final</div>
        <p class="step-desc">Junta assets, aplica overlay, efeitos Ken Burns e música. Renderiza o vídeo final.</p>
    </div>
    """, unsafe_allow_html=True)
    if st.button("Ir para Montagem ➔", key="btn3", use_container_width=True):
        st.switch_page("pages/3_🎥_Montagem.py")

st.divider()
st.info("👈 Use a barra lateral para navegar entre os módulos do aplicativo.")
