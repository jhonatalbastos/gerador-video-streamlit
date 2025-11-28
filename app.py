import streamlit as st
from datetime import date
import re
import requests
from groq import Groq
import json
from gtts import gTTS
from io import BytesIO
from pydub import AudioSegment
from pydub.silence import detect_silence

# =========================
# Configuração da página
# =========================
st.set_page_config(
    page_title="Studio Jhonata",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =========================
# Groq - cliente lazy
# =========================
_client = None


def inicializar_groq():
    global _client
    if _client is None:
        if "GROQ_API_KEY" not in st.secrets:
            st.error("❌ Configure GROQ_API_KEY em Settings → Secrets no Streamlit Cloud.")
            st.stop()
        _client = Groq(api_key=st.secrets["GROQ_API_KEY"])
    return _client


# =========================
# Inicializar banco de personagens
# =========================
@st.cache_data
def inicializar_personagens():
    return {
        "Jesus": (
            "homem de 33 anos, pele morena clara, cabelo castanho ondulado na altura dos ombros, "
            "barba bem aparada, olhos castanhos penetrantes e serenos, túnica branca tradicional "
            "com detalhes vermelhos, manto azul, expressão de autoridade amorosa, estilo renascentista clássico"
        ),
        "São Pedro": (
            "homem robusto de 50 anos, pele bronzeada, cabelo curto grisalho, barba espessa, olhos "
            "determinados, túnica de pescador bege com remendos, mãos calejadas, postura forte, estilo realista bíblico"
        ),
        "São João": (
            "jovem de 25 anos, magro, cabelo castanho longo liso, barba rala, olhos expressivos, túnica "
            "branca limpa, expressão contemplativa, estilo renascentista"
        ),
    }


# =========================
# Limpeza do texto bíblico
# =========================
def limpar_texto_evangelho(texto: str) -> str:
    if not texto:
        return ""
    texto_limpo = texto.replace("
", " ").strip()
    texto_limpo = re.sub(r"\b(d{1,3})(?=[A-Za-zÁ-Úá-ú])", "", texto_limpo)
    texto_limpo = re.sub(r"s{2,}", " ", texto_limpo)
    return texto_limpo.strip()


# =========================
# Geração de áudio com gTTS + respiro
# =========================
def gerar_audio_com_respiro(texto: str) -> BytesIO:
    """
    Gera áudio do texto usando gTTS (pt-BR) e adiciona 1.5s de silêncio no final (respiro).
    Retorna BytesIO pronto para st.audio ou download.
    """
    try:
        # Gerar áudio do texto
        tts = gTTS(text=texto, lang='pt', slow=False)
        audio_fp = BytesIO()
        tts.write_to_fp(audio_fp)
        audio_fp.seek(0)
        
        # Carregar como AudioSegment
        audio = AudioSegment.from_mp3(audio_fp)
        
        # Adicionar 1.5s de silêncio no final (respiro)
        silencio = AudioSegment.silent(duration=1500)  # 1500ms = 1.5s
        audio_com_respiro = audio + silencio
        
        # Exportar de volta para BytesIO
        output = BytesIO()
        audio_com_respiro.export(output, format="mp3")
        output.seek(0)
        
        return output
    except Exception as e:
        st.error(f"❌ Erro ao gerar áudio: {e}")
        return None


# =========================
# Extrair referência bíblica
# =========================
def extrair_referencia_biblica(titulo: str):
    if not titulo:
        return None
    m = re.search(
        r"segundos+Sãos+([A-Za-zÁ-Úá-ú]+)s+(d+),s*([d-–]+)",
        titulo,
        flags=re.IGNORECASE,
    )
    if not m:
        return None
    evangelista = m.group(1).strip()
    capitulo = m.group(2).strip()
    versiculos_raw = m.group(3).strip()
    versiculos = versiculos_raw.replace("-", " a ").replace("–", " a ")
    return {"evangelista": evangelista, "capitulo": capitulo, "versiculos": versiculos}


def formatar_referencia_curta(ref_biblica):
    if not ref_biblica:
        return ""
    return f"{ref_biblica['evangelista']}, Cap. {ref_biblica['capitulo']}, {ref_biblica['versiculos']}"


# =========================
# ANÁLISE DE PERSONAGENS + BANCO
# =========================
def analisar_personagens_groq(texto_evangelho: str, banco_personagens: dict):
    client = inicializar_groq()

    system_prompt = (
        "Você é especialista em análise bíblica.
"
        "Analise o texto e identifique TODOS os personagens bíblicos mencionados.

"
        "Formato EXATO da resposta:
"
        "PERSONAGENS: nome1; nome2; nome3
"
        "NOVOS: NomeNovo|descrição_detalhada_aparência_física_roupas_idade_estilo (apenas se não existir no banco)

"
        f"BANCO EXISTENTE: {'; '.join(banco_personagens.keys())}

"
        "Exemplo:
"
        "PERSONAGENS: Jesus; Pedro; fariseus
"
        "NOVOS: Mulher Samaritana|mulher de 35 anos, pele morena, véu colorido, jarro d'água, expressão curiosa, túnica tradicional"
    )

    try:
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"TEXTO: {texto_evangelho[:1500]}"},
            ],
            temperature=0.3,
            max_tokens=400,
        )

        resultado = resp.choices[0].message.content
        personagens_detectados = {}

        m = re.search(r"PERSONAGENS:s*(.+)", resultado)
        if m:
            nomes = [n.strip() for n in m.group(1).split(";") if n.strip()]
            for nome in nomes:
                if nome in banco_personagens:
                    personagens_detectados[nome] = banco_personagens[nome]

        m = re.search(r"NOVOS:s*(.+)", resultado)
        if m:
            novos = m.group(1).strip()
            for bloco in novos.split(","):
                if "|" in bloco:
                    nome, desc = bloco.split("|", 1)
                    nome = nome.strip()
                    desc = desc.strip()
                    if not nome:
                        continue
                    personagens_detectados[nome] = desc
                    banco_personagens[nome] = desc

        return personagens_detectados
    except Exception:
        return {}


# =========================
# APIs Liturgia
# =========================
def buscar_liturgia_api1(data_str: str):
    url = f"https://api-liturgia-diaria.vercel.app/?date={data_str}"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        dados = resp.json()
        today = dados.get("today", {})
        readings = today.get("readings", {})
        gospel = readings.get("gospel")
        if not gospel:
            return None
        referencia_liturgica = today.get("entry_title", "").strip() or "Evangelho do dia"
        titulo = (
            gospel.get("head_title", "")
            or gospel.get("title", "")
            or "Evangelho de Jesus Cristo"
        ).strip()
        texto = gospel.get("text", "").strip()
        if not texto:
            return None
        texto_limpo = limpar_texto_evangelho(texto)
        ref_biblica = extrair_referencia_biblica(titulo)
        return {
            "fonte": "api-liturgia-diaria.vercel.app",
            "titulo": titulo,
            "referencia_liturgica": referencia_liturgica,
            "texto": texto_limpo,
            "ref_biblica": ref_biblica,
        }
    except Exception:
        return None


def buscar_liturgia_api2(data_str: str):
    url = f"https://liturgia.up.railway.app/v2/{data_str}"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        dados = resp.json()
        lit = dados.get("liturgia", {})
        ev = lit.get("evangelho") or lit.get("evangelho_do_dia") or {}
        if not ev:
            return None
        texto = ev.get("texto", "") or ev.get("conteudo", "")
        if not texto:
            return None
        texto_limpo = limpar_texto_evangelho(texto)
        return {
            "fonte": "liturgia.up.railway.app",
            "titulo": "Evangelho do dia",
            "referencia_liturgica": "Evangelho do dia",
            "texto": texto_limpo,
            "ref_biblica": None,
        }
    except Exception:
        return None


def obter_evangelho_com_fallback(data_str: str):
    ev = buscar_liturgia_api1(data_str)
    if ev:
        st.info("📡 Usando api-liturgia-diaria.vercel.app")
        return ev
    ev = buscar_liturgia_api2(data_str)
    if ev:
        st.info("📡 Usando liturgia.up.railway.app")
        return ev
    st.error("❌ Não foi possível obter o Evangelho")
    return None


# =========================
# Roteiro + Prompts Visuais
# =========================
def extrair_bloco(rotulo: str, texto: str) -> str:
    padrao = rf"{rotulo}:s*(.*?)(?=
[A-ZÁÉÍÓÚÃÕÇ]{{3,}}:s*|
PROMPT_|$)"
    m = re.search(padrao, texto, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else ""


def extrair_prompt(rotulo: str, texto: str) -> str:
    padrao = rf"{rotulo}:s*(.*?)(?=
[A-ZÁÉÍÓÚÃÕÇ]{{3,}}:s*|
PROMPT_|$)"
    m = re.search(padrao, texto, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else ""


def gerar_roteiro_com_prompts_groq(
    texto_evangelho: str, referencia_liturgica: str, personagens: dict
):
    client = inicializar_groq()
    texto_limpo = limpar_texto_evangelho(texto_evangelho)

    personagens_str = json.dumps(personagens, ensure_ascii=False)

    system_prompt = f"""Crie roteiro + 6 prompts visuais CATÓLICOS para vídeo devocional.

PERSONAGENS FIXOS: {personagens_str}

IMPORTANTE:
- 4 PARTES EXATAS: HOOK, REFLEXÃO, APLICAÇÃO, ORAÇÃO
- PROMPT_LEITURA separado (momento da leitura do Evangelho, mais calmo e reverente)
- PROMPT_GERAL para thumbnail
- USE SEMPRE as descrições exatas dos personagens
- Estilo: artístico renascentista católico, luz suave, cores quentes

Formato EXATO:

HOOK: [texto 5-8s]
PROMPT_HOOK: [prompt visual com personagens fixos]

REFLEXÃO: [texto 20-25s]
PROMPT_REFLEXÃO: [prompt visual com personagens fixos]

APLICAÇÃO: [texto 20-25s]
PROMPT_APLICACAO: [prompt visual com personagens fixos]

ORAÇÃO: [texto 20-25s]
PROMPT_ORACAO: [prompt visual com personagens fixos]

PROMPT_LEITURA: [prompt visual específico para a leitura do Evangelho, mais calmo e reverente]

PROMPT_GERAL: [prompt para thumbnail/capa]"""

    try:
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": f"Evangelho: {referencia_liturgica}

{texto_limpo[:2000]}",
                },
            ],
            temperature=0.7,
            max_tokens=1200,
        )

        texto_gerado = resp.choices[0].message.content

        partes: dict[str, str] = {}

        # Textos
        partes["hook"] = extrair_bloco("HOOK", texto_gerado)
        partes["reflexão"] = extrair_bloco("REFLEXÃO", texto_gerado)
        partes["aplicação"] = extrair_bloco("APLICAÇÃO", texto_gerado)
        partes["oração"] = extrair_bloco("ORAÇÃO", texto_gerado)

        # Prompts
        partes["prompt_hook"] = extrair_prompt("PROMPT_HOOK", texto_gerado)
        partes["prompt_reflexão"] = extrair_prompt("PROMPT_REFLEXÃO", texto_gerado)
        partes["prompt_aplicacao"] = extrair_prompt("PROMPT_APLICACAO", texto_gerado)
        partes["prompt_oração"] = extrair_prompt("PROMPT_ORACAO", texto_gerado)
        partes["prompt_leitura"] = extrair_prompt("PROMPT_LEITURA", texto_gerado)

        m_geral = re.search(
            r"PROMPT_GERAL:s*(.+)", texto_gerado, re.DOTALL | re.IGNORECASE
        )
        partes["prompt_geral"] = m_geral.group(1).strip() if m_geral else ""

        return partes
    except Exception as e:
        st.error(f"❌ Erro Groq: {e}")
        return None


def montar_leitura_com_formula(texto_evangelho: str, ref_biblica):
    if ref_biblica:
        abertura = (
            f"Proclamação do Evangelho de Jesus Cristo, segundo São "
            f"{ref_biblica['evangelista']}, "
            f"Capítulo {ref_biblica['capitulo']}, "
            f"versículos {ref_biblica['versiculos']}. "
            "Glória a vós, Senhor!"
        )
    else:
        abertura = (
            "Proclamação do Evangelho de Jesus Cristo, segundo São Lucas. "
            "Glória a vós, Senhor!"
        )
    fechamento = "Palavra da Salvação. Glória a vós, Senhor!"
    return f"{abertura} {texto_evangelho} {fechamento}"


# =========================
# Interface Principal
# =========================
st.title("✨ Studio Jhonata - Automação Litúrgica")
st.markdown("---")

st.sidebar.title("⚙️ Configurações")
st.sidebar.info("1️⃣ api-liturgia-diaria
2️⃣ liturgia.railway
3️⃣ Groq fallback")
st.sidebar.success("✅ Groq ativo")

if "personagens_biblicos" not in st.session_state:
    st.session_state.personagens_biblicos = inicializar_personagens()

if "audios" not in st.session_state:
    st.session_state.audios = {}

tab1, tab2, tab3, tab4 = st.tabs(
    ["📖 Gerar Roteiro", "🎨 Personagens", "🎥 Fábrica Vídeo", "📊 Histórico"]
)

# --------- TAB 1: ROTEIRO ----------
with tab1:
    st.header("🚀 Gerador de Roteiro + Imagens")

    col1, col2 = st.columns([2, 1])
    with col1:
        data_selecionada = st.date_input(
            "📅 Data da liturgia:", value=date.today(), min_value=date(2023, 1, 1)
        )
    with col2:
        st.info("Status: ✅ pronto para gerar")

    if st.button("🚀 Gerar Roteiro Completo", type="primary"):
        data_str = data_selecionada.strftime("%Y-%m-%d")

        with st.spinner("🔍 Buscando Evangelho..."):
            liturgia = obter_evangelho_com_fallback(data_str)
        if not liturgia:
            st.stop()

        st.success(
            f"✅ Evangelho: {liturgia['referencia_liturgica']} ({liturgia['fonte']})"
        )

        with st.spinner("🤖 Analisando personagens..."):
            personagens_detectados = analisar_personagens_groq(
                liturgia["texto"], st.session_state.personagens_biblicos
            )

        with st.spinner("✨ Gerando roteiro e prompts visuais..."):
            roteiro = gerar_roteiro_com_prompts_groq(
                liturgia["texto"],
                liturgia["referencia_liturgica"],
                {**st.session_state.personagens_biblicos, **personagens_detectados},
            )

        if not roteiro:
            st.stop()

        leitura_montada = montar_leitura_com_formula(
            liturgia["texto"], liturgia.get("ref_biblica")
        )
        ref_curta = formatar_referencia_curta(liturgia.get("ref_biblica"))

        # Salvar roteiro e leitura em sessão
        st.session_state.roteiro_atual = roteiro
        st.session_state.leitura_atual = leitura_montada

        st.markdown("## 📖 Roteiro pronto para gravar")
        if ref_curta:
            st.markdown(f"**Leitura:** {ref_curta}")
        st.markdown("---")

        if personagens_detectados:
            st.markdown("### 👥 Personagens nesta leitura")
            for nome, desc in personagens_detectados.items():
                st.markdown(f"**{nome}:** {desc}")
            st.markdown("---")

        col_esq, col_dir = st.columns(2)

        with col_esq:
            st.markdown("### 🎣 HOOK")
            st.markdown(roteiro.get("hook", ""))
            if st.button("🎙️ Gerar áudio Hook", key="btn_hook"):
                with st.spinner("Gerando áudio..."):
                    audio = gerar_audio_com_respiro(roteiro.get("hook", ""))
                    if audio:
                        st.session_state.audios["hook"] = audio
                        st.success("✅ Áudio gerado")
            
            if "hook" in st.session_state.audios:
                st.audio(st.session_state.audios["hook"], format="audio/mp3")
                st.download_button(
                    "⬇️ Download Hook.mp3",
                    data=st.session_state.audios["hook"],
                    file_name="hook.mp3",
                    mime="audio/mp3"
                )
            
            st.markdown("**📸 Prompt:**")
            st.code(roteiro.get("prompt_hook", ""))

            st.markdown("### 💭 REFLEXÃO")
            st.markdown(roteiro.get("reflexão", ""))
            if st.button("🎙️ Gerar áudio Reflexão", key="btn_reflexao"):
                with st.spinner("Gerando áudio..."):
                    audio = gerar_audio_com_respiro(roteiro.get("reflexão", ""))
                    if audio:
                        st.session_state.audios["reflexao"] = audio
                        st.success("✅ Áudio gerado")
            
            if "reflexao" in st.session_state.audios:
                st.audio(st.session_state.audios["reflexao"], format="audio/mp3")
                st.download_button(
                    "⬇️ Download Reflexão.mp3",
                    data=st.session_state.audios["reflexao"],
                    file_name="reflexao.mp3",
                    mime="audio/mp3",
                    key="dl_reflexao"
                )
            
            st.markdown("**📸 Prompt:**")
            st.code(roteiro.get("prompt_reflexão", ""))

        with col_dir:
            st.markdown("### 📖 LEITURA")
            st.markdown(leitura_montada)
            if st.button("🎙️ Gerar áudio Leitura", key="btn_leitura"):
                with st.spinner("Gerando áudio..."):
                    audio = gerar_audio_com_respiro(leitura_montada)
                    if audio:
                        st.session_state.audios["leitura"] = audio
                        st.success("✅ Áudio gerado")
            
            if "leitura" in st.session_state.audios:
                st.audio(st.session_state.audios["leitura"], format="audio/mp3")
                st.download_button(
                    "⬇️ Download Leitura.mp3",
                    data=st.session_state.audios["leitura"],
                    file_name="leitura.mp3",
                    mime="audio/mp3",
                    key="dl_leitura"
                )
            
            st.markdown("**📸 Prompt:**")
            st.code(roteiro.get("prompt_leitura", ""))

            st.markdown("### 🌟 APLICAÇÃO")
            st.markdown(roteiro.get("aplicação", ""))
            if st.button("🎙️ Gerar áudio Aplicação", key="btn_aplicacao"):
                with st.spinner("Gerando áudio..."):
                    audio = gerar_audio_com_respiro(roteiro.get("aplicação", ""))
                    if audio:
                        st.session_state.audios["aplicacao"] = audio
                        st.success("✅ Áudio gerado")
            
            if "aplicacao" in st.session_state.audios:
                st.audio(st.session_state.audios["aplicacao"], format="audio/mp3")
                st.download_button(
                    "⬇️ Download Aplicação.mp3",
                    data=st.session_state.audios["aplicacao"],
                    file_name="aplicacao.mp3",
                    mime="audio/mp3",
                    key="dl_aplicacao"
                )
            
            st.markdown("**📸 Prompt:**")
            st.code(roteiro.get("prompt_aplicacao", ""))

        st.markdown("### 🙏 ORAÇÃO")
        st.markdown(roteiro.get("oração", ""))
        if st.button("🎙️ Gerar áudio Oração", key="btn_oracao"):
            with st.spinner("Gerando áudio..."):
                audio = gerar_audio_com_respiro(roteiro.get("oração", ""))
                if audio:
                    st.session_state.audios["oracao"] = audio
                    st.success("✅ Áudio gerado")
        
        if "oracao" in st.session_state.audios:
            st.audio(st.session_state.audios["oracao"], format="audio/mp3")
            st.download_button(
                "⬇️ Download Oração.mp3",
                data=st.session_state.audios["oracao"],
                file_name="oracao.mp3",
                mime="audio/mp3",
                key="dl_oracao"
            )
        
        st.markdown("**📸 Prompt:**")
        st.code(roteiro.get("prompt_oração", ""))

        st.markdown("### 🖼️ THUMBNAIL")
        st.code(roteiro.get("prompt_geral", ""))
        st.markdown("---")

# --------- TAB 2: PERSONAGENS ----------
with tab2:
    st.header("🎨 Banco de Personagens Bíblicos")

    banco = st.session_state.personagens_biblicos.copy()

    col1, col2 = st.columns([1, 1])

    with col1:
        st.markdown("### 📋 Todos os personagens")
        for i, (nome, desc) in enumerate(banco.items()):
            with st.expander(f"✏️ {nome}"):
                novo_nome = st.text_input(f"Nome {i}", value=nome, key=f"nome_{i}")
                nova_desc = st.text_area(
                    f"Descrição {i}", value=desc, height=100, key=f"desc_{i}"
                )
                col_a, col_b = st.columns(2)
                with col_a:
                    if st.button("💾 Salvar", key=f"salvar_{i}"):
                        if novo_nome and nova_desc:
                            if (
                                novo_nome != nome
                                and novo_nome
                                in st.session_state.personagens_biblicos
                            ):
                                del st.session_state.personagens_biblicos[novo_nome]
                            del st.session_state.personagens_biblicos[nome]
                            st.session_state.personagens_biblicos[novo_nome] = nova_desc
                            st.rerun()
                with col_b:
                    if st.button("🗑️ Apagar", key=f"apagar_{i}"):
                        del st.session_state.personagens_biblicos[nome]
                        st.rerun()

    with col2:
        st.markdown("### ➕ Novo Personagem")
        novo_nome = st.text_input("Nome do personagem", key="novo_nome")
        nova_desc = st.text_area(
            "Descrição detalhada (aparência, roupas, idade, estilo)",
            height=120,
            key="nova_desc",
        )
        if st.button("➕ Adicionar") and novo_nome and nova_desc:
            st.session_state.personagens_biblicos[novo_nome] = nova_desc
            st.rerun()

# --------- TAB 3: FÁBRICA DE VÍDEO ----------
with tab3:
    st.header("🎥 Fábrica de Vídeo")
    st.info("Em desenvolvimento: montagem do vídeo completo com MoviePy.")

# --------- TAB 4: HISTÓRICO ----------
with tab4:
    st.header("📊 Histórico")
    st.info("Em breve.")

st.markdown("---")
st.markdown("Feito com ❤️ para evangelização - Studio Jhonata")
