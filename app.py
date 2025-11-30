# app.py — Studio Jhonata (COMPLETO v20.2 - Pronto para Montagem de Drive)
# ... [Imports e Funções de Liturgia, Groq, Helpers, etc. permanecem inalteradas] ...

# =========================
# VARIÁVEIS DO NOVO FLUXO (Exemplo)
# =========================
# URL do endpoint do Google Apps Script que gerencia o Drive (POST/PULL)
# Você deve obter este URL após publicar seu GAS.
GAS_API_URL = "SEU_URL_APPS_SCRIPT_AQUI" 

# =========================
# FUNÇÕES DE COMUNICAÇÃO COM APPS SCRIPT/DRIVE
# (Estas são mockadas, dependem do GAS real)
# =========================

def fetch_job_metadata(job_id: str) -> Optional[Dict]:
    """
    Solicita ao Apps Script os metadados do Job ID e lista de URLs de arquivos.
    O GAS_API_URL deve ter um endpoint que retorne o JSON do roteiro e URLs.
    """
    st.info(f"🌐 Solicitando metadados do Job ID: {job_id}...")
    try:
        # Exemplo de requisição (Adapte para o seu GAS API)
        response = requests.post(
            f"{GAS_API_URL}?action=fetch_job",
            json={"job_id": job_id},
            timeout=30
        )
        response.raise_for_status()
        data = response.json()
        
        if data.get("status") == "success":
            return data.get("payload") # Deve conter: roteiro, ref_biblica, urls_arquivos, etc.
        else:
            st.error(f"Erro ao buscar Job ID: {data.get('message', 'Resposta inválida do GAS.')}")
            return None
    except Exception as e:
        st.error(f"Erro de comunicação com o Apps Script: {e}")
        return None

def download_files_from_urls(urls_arquivos: List[Dict]) -> Tuple[Dict, Dict]:
    """Baixa os arquivos de áudio e imagem de URLs temporárias do Drive."""
    images = {}
    audios = {}
    st.info(f"⬇️ Baixando {len(urls_arquivos)} arquivos do Google Drive...")
    
    for item in urls_arquivos:
        url = item["url"]
        block_id = item["block_id"] # hook, leitura, etc.
        file_type = item["type"] # image ou audio
        
        try:
            r = requests.get(url, timeout=60)
            r.raise_for_status()
            bio = BytesIO(r.content)
            bio.seek(0)

            if file_type == "image":
                images[block_id] = bio
            elif file_type == "audio":
                audios[block_id] = bio
            st.write(f"✅ Baixado: {block_id} ({file_type})")
        except Exception as e:
            st.error(f"❌ Falha ao baixar {block_id} ({file_type}): {e}")
            
    return images, audios

def finalize_job_on_drive(job_id: str, video_bytes: BytesIO, metadata_description: str):
    """
    Envia o vídeo final e os metadados para o Apps Script para upload e limpeza.
    Esta função usa codificação multipart/form-data.
    """
    st.info(f"⬆️ Finalizando Job {job_id} e limpando arquivos...")
    try:
        # Codificar o vídeo e metadados no formato que o GAS espera
        files = {
            'video_file': ('final_video.mp4', video_bytes, 'video/mp4'),
            'metadata_file': ('metadata.json', metadata_description.encode('utf-8'), 'application/json')
        }
        
        response = requests.post(
            f"{GAS_API_URL}?action=finalize_job&job_id={job_id}",
            files=files,
            timeout=120
        )
        response.raise_for_status()
        
        data = response.json()
        if data.get("status") == "success":
            st.success(f"Job {job_id} concluído com sucesso e arquivos temporários limpos no Drive!")
            st.markdown(f"**URL do Vídeo Final no Drive:** {data.get('final_url', 'N/A')}")
            return True
        else:
            st.error(f"Falha na finalização do Job no Drive: {data.get('message', 'Erro desconhecido.')}")
            return False
            
    except Exception as e:
        st.error(f"Erro ao finalizar Job no Apps Script: {e}")
        return False

# ... [Resto do código do app.py até a TAB 4] ...

# --------- TAB 4: FÁBRICA DE VÍDEO ----------
with tab4:
    st.header("🎥 Editor de Cenas")
    
    # === NOVO BLOCO: MONTAGEM REMOTA ===
    st.subheader("🌐 Modo 1: Montagem Automática (Google Drive)")
    job_id_input = st.text_input("Insira o JOB ID (Nome da Pasta do Drive):", key="job_id_input")
    
    if st.button("📥 Carregar Job ID do Drive", type="primary"):
        if job_id_input:
            with st.status(f"Carregando Job {job_id_input}...", expanded=True) as status:
                job_data = fetch_job_metadata(job_id_input)
                if job_data:
                    # 1. Carrega o roteiro
                    st.session_state["roteiro_gerado"] = job_data.get("roteiro")
                    st.session_state["leitura_montada"] = job_data.get("leitura_montada", "")
                    st.session_state["meta_dados"] = job_data.get("meta_dados", {})
                    st.session_state["job_id_ativo"] = job_id_input # Salva o ID do Job ativo

                    # 2. Baixa arquivos
                    images, audios = download_files_from_urls(job_data.get("urls_arquivos", []))
                    st.session_state["generated_images_blocks"] = images
                    st.session_state["generated_audios_blocks"] = audios
                    
                    status.update(label=f"Job {job_id_input} carregado com sucesso!", state="complete")
                    st.rerun()
                else:
                    status.update(label=f"Falha ao carregar Job {job_id_input}.", state="error")
        else:
            st.warning("Por favor, insira um Job ID.")

    st.markdown("---")
    st.subheader("⚙️ Modo 2: Edição Manual (Fallback)")
    # === FIM DO NOVO BLOCO ===
    
    if not st.session_state.get("roteiro_gerado"):
        st.warning("⚠️ Gere o roteiro na Aba 1 ou Carregue um Job ID acima.")
        st.stop()

    # O resto da lógica da TAB 4 (Visualização de cenas, geração manual, e renderização)
    # permanece o mesmo, mas agora ele pode usar dados do Drive ou dados gerados manualmente.
    
    # ... [O resto da TAB 4 (Visualização de Cenas, Geração em Lote) permanece inalterado] ...

    # --- NOVO FLUXO DE FINALIZAÇÃO (PÓS-RENDERIZAÇÃO) ---
    if st.session_state.get("video_final_bytes") and st.session_state.get("job_id_ativo"):
        job_id = st.session_state["job_id_ativo"]
        
        st.header("Upload e Finalização Automática")
        
        # Gera o JSON de metadados para redes sociais
        roteiro = st.session_state["roteiro_gerado"]
        meta_data_json = json.dumps({
            "job_id": job_id,
            "titulo_sugerido": "Evangelho do Dia",
            "descricao_completa": roteiro.get("hook", "") + "\n\n" + roteiro.get("reflexão", "") + "\n\n" + roteiro.get("aplicação", "") + "\n\n" + roteiro.get("oração", "")
        }, indent=4)
        
        st.code(meta_data_json, language="json", caption="Metadados Gerados (Descrição para Redes)")
        
        if st.button(f"🚀 Upload Finalizar & Limpar Drive ({job_id})", type="primary"):
            video_bytes = st.session_state["video_final_bytes"]
            
            # Chama o Apps Script para upload e limpeza
            if finalize_job_on_drive(job_id, video_bytes, meta_data_json):
                # Limpa o estado após o sucesso para começar um novo job
                st.session_state["job_id_ativo"] = None
                st.session_state["video_final_bytes"] = None
                st.rerun()


# ... [Resto do app.py (TAB 5, Rodapé) permanece inalterado] ...