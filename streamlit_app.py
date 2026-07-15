"""Ponto de entrada da interface Streamlit.

Executar com: streamlit run streamlit_app.py
"""
from __future__ import annotations

import logging

import pandas as pd
import streamlit as st

from app import db
from app.classification import patterns as patterns_module
from app.classification.engine import ClassificationSettings, classificar_extrato, generate_report
from app.classification.learning import record_correction
from app.export.excel_export import build_export_dataframe, export_to_excel_bytes
from app.importers.balancete import load_balancete
from app.importers.extrato import load_extrato
from app.importers.razao import load_razao
from app.models import ClassificacaoResultado, OrigemClassificacao

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("streamlit_app")

st.set_page_config(page_title="Classificador Contábil de Extratos", layout="wide")
db.init_db()


def _init_session_state() -> None:
    defaults = {
        "extrato_lancamentos": [],
        "razao_lancamentos": [],
        "balancete_contas": [],
        "resultados": [],
        "processado": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


_init_session_state()


def _load_settings() -> ClassificationSettings:
    settings = db.get_all_settings()
    return ClassificationSettings(
        tolerancia_dias=int(settings.get("tolerancia_dias_data", 3)),
        limiar_fuzzy=float(settings.get("limiar_fuzzy_historico", 80)),
        limiar_confianca_minima=float(settings.get("limiar_confianca_minima", 60)),
        conta_adiantamentos_codigo=settings.get("conta_adiantamentos_codigo", ""),
        conta_adiantamentos_descricao=settings.get("conta_adiantamentos_descricao", ""),
    )


def _resultados_to_dataframe(resultados: list[ClassificacaoResultado]) -> pd.DataFrame:
    linhas = []
    for r in resultados:
        linhas.append({
            "Data": r.lancamento.data.strftime("%d/%m/%Y"),
            "Histórico": r.lancamento.historico,
            "Documento": r.lancamento.documento,
            "Valor": r.lancamento.valor,
            "Tipo": "Crédito" if r.lancamento.tipo.value == "credito" else "Débito",
            "Conta Encontrada": r.conta_codigo or "",
            "Descrição da Conta": r.conta_descricao or "",
            "Confiança (%)": r.confianca,
            "Origem": r.origem.value,
            "Detalhe": r.detalhe,
        })
    return pd.DataFrame(linhas)


st.title("📑 Classificador Contábil de Extratos Bancários")
st.caption(
    "Importe o extrato, o razão e o balancete do período para classificar automaticamente "
    "cada lançamento na conta contábil correta."
)

tab_importar, tab_resultados, tab_padroes, tab_config = st.tabs(
    ["📥 Importar & Processar", "📊 Resultados", "🧩 Cadastro de Padrões", "⚙️ Configurações"]
)

# --------------------------------------------------------------------------- #
# Tab: Importar & Processar
# --------------------------------------------------------------------------- #
with tab_importar:
    col1, col2, col3 = st.columns(3)

    with col1:
        st.subheader("Importar Extrato")
        arquivo_extrato = st.file_uploader(
            "Extrato bancário", type=["csv", "xlsx", "xls", "ofx", "pdf"], key="upload_extrato"
        )

    with col2:
        st.subheader("Importar Razão")
        arquivo_razao = st.file_uploader(
            "Razão contábil", type=["csv", "xlsx", "xls", "pdf"], key="upload_razao"
        )

    with col3:
        st.subheader("Importar Balancete")
        arquivo_balancete = st.file_uploader(
            "Balancete do período (opcional)", type=["csv", "xlsx", "xls", "pdf"], key="upload_balancete"
        )

    st.divider()

    if st.button("▶️ Processar", type="primary", width="stretch"):
        if not arquivo_extrato or not arquivo_razao:
            st.error("É necessário importar ao menos o Extrato e o Razão para processar.")
        else:
            try:
                with st.spinner("Lendo e normalizando arquivos..."):
                    extrato_lancamentos = load_extrato(arquivo_extrato, arquivo_extrato.name)
                    razao_lancamentos = load_razao(arquivo_razao, arquivo_razao.name)
                    balancete_contas = (
                        load_balancete(arquivo_balancete, arquivo_balancete.name)
                        if arquivo_balancete else []
                    )

                if not extrato_lancamentos:
                    st.warning("Nenhum lançamento foi encontrado no extrato importado.")
                else:
                    with st.spinner("Classificando lançamentos..."):
                        settings = _load_settings()
                        resultados = classificar_extrato(extrato_lancamentos, razao_lancamentos, settings)

                    st.session_state.extrato_lancamentos = extrato_lancamentos
                    st.session_state.razao_lancamentos = razao_lancamentos
                    st.session_state.balancete_contas = balancete_contas
                    st.session_state.resultados = resultados
                    st.session_state.processado = True
                    st.success(
                        f"Processamento concluído: {len(extrato_lancamentos)} lançamentos do extrato, "
                        f"{len(razao_lancamentos)} do razão e {len(balancete_contas)} contas do balancete."
                    )
            except Exception as exc:  # noqa: BLE001 — exibir qualquer erro de leitura ao usuário
                logger.exception("Falha ao processar arquivos")
                st.error(f"Erro ao processar arquivos: {exc}")

    if st.session_state.processado:
        st.info(
            f"Último processamento: {len(st.session_state.extrato_lancamentos)} lançamentos prontos. "
            "Veja a aba **Resultados** para revisar e exportar."
        )

# --------------------------------------------------------------------------- #
# Tab: Resultados
# --------------------------------------------------------------------------- #
with tab_resultados:
    if not st.session_state.processado:
        st.info("Importe os arquivos e clique em **Processar** na primeira aba.")
    else:
        settings = _load_settings()
        resultados: list[ClassificacaoResultado] = st.session_state.resultados
        relatorio = generate_report(resultados, settings.limiar_confianca_minima)

        st.subheader("Relatório de Conferência")
        m1, m2, m3, m4, m5, m6 = st.columns(6)
        m1.metric("Total analisados", relatorio["total_lancamentos"])
        m2.metric("Classificados (Razão)", relatorio["classificados_razao"])
        m3.metric("Via Padrão", relatorio["classificados_padrao"])
        m4.metric("Via Aprendizado", relatorio["classificados_aprendizado"])
        m5.metric("Adiantamentos", relatorio["enviados_adiantamentos"])
        m6.metric("Sem confiança suficiente", relatorio["sem_confianca_suficiente"])

        st.divider()
        st.subheader("Lançamentos Classificados")
        st.caption("Edite 'Conta Encontrada' e 'Descrição da Conta' diretamente na grade, se necessário.")

        df = _resultados_to_dataframe(resultados)
        df_editado = st.data_editor(
            df,
            column_config={
                "Confiança (%)": st.column_config.ProgressColumn(
                    "Confiança (%)", min_value=0, max_value=100, format="%.0f%%"
                ),
            },
            disabled=["Data", "Histórico", "Documento", "Valor", "Tipo", "Origem", "Detalhe"],
            width="stretch",
            hide_index=True,
            key="grid_resultados",
        )

        col_salvar, col_export = st.columns([1, 1])
        with col_salvar:
            if st.button("💾 Salvar edições e aprender correções", width="stretch"):
                alteracoes = 0
                for i, (original, editado) in enumerate(zip(df["Conta Encontrada"], df_editado["Conta Encontrada"])):
                    resultado = resultados[i]
                    nova_conta = df_editado.loc[i, "Conta Encontrada"]
                    nova_descricao = df_editado.loc[i, "Descrição da Conta"]
                    if nova_conta != original or nova_descricao != df.loc[i, "Descrição da Conta"]:
                        record_correction(
                            resultado.lancamento, resultado.conta_codigo, nova_conta, nova_descricao
                        )
                        resultado.conta_codigo = nova_conta
                        resultado.conta_descricao = nova_descricao
                        resultado.editado_manualmente = True
                        resultado.confianca = 100.0
                        alteracoes += 1
                if alteracoes:
                    st.success(f"{alteracoes} correção(ões) salva(s) e aprendida(s) para futuras importações.")
                    st.rerun()
                else:
                    st.info("Nenhuma alteração detectada.")

        with col_export:
            centro_custo = st.text_input("Centro de Custo (opcional, aplicado a todas as linhas)", "")
            filial = st.text_input("Filial (opcional, aplicada a todas as linhas)", "")
            settings_db = db.get_all_settings()
            export_df = build_export_dataframe(
                resultados, settings_db.get("conta_banco_codigo", ""), centro_custo, filial
            )
            excel_bytes = export_to_excel_bytes(export_df)
            st.download_button(
                "⬇️ Exportar Excel para Domínio Sistemas",
                data=excel_bytes,
                file_name="importacao_dominio.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width="stretch",
            )

# --------------------------------------------------------------------------- #
# Tab: Cadastro de Padrões
# --------------------------------------------------------------------------- #
with tab_padroes:
    st.subheader("Cadastro de Padrões")
    st.caption(
        "Sempre que um destes padrões aparecer no histórico do extrato, a conta correspondente "
        "será usada automaticamente (maior prioridade de classificação)."
    )

    with st.form("form_novo_padrao", clear_on_submit=True):
        c1, c2, c3, c4 = st.columns([1, 2, 1, 2])
        tipo = c1.selectbox("Tipo", ["palavra_chave", "expressao", "favorecido"])
        valor = c2.text_input("Palavra-chave / Expressão / Favorecido")
        conta_codigo = c3.text_input("Código da Conta")
        conta_descricao = c4.text_input("Descrição da Conta")
        if st.form_submit_button("➕ Adicionar Padrão"):
            if valor and conta_codigo and conta_descricao:
                patterns_module.add_pattern(tipo, valor, conta_codigo, conta_descricao)
                st.success("Padrão adicionado.")
                st.rerun()
            else:
                st.error("Preencha todos os campos.")

    st.divider()
    lista_padroes = patterns_module.list_patterns()
    if lista_padroes:
        for p in lista_padroes:
            c1, c2, c3, c4, c5 = st.columns([1, 2, 1, 2, 1])
            c1.write(p.tipo)
            c2.write(p.valor)
            c3.write(p.conta_codigo)
            c4.write(p.conta_descricao)
            if c5.button("🗑️ Remover", key=f"del_pattern_{p.id}"):
                patterns_module.delete_pattern(p.id)
                st.rerun()
    else:
        st.info("Nenhum padrão cadastrado ainda.")

# --------------------------------------------------------------------------- #
# Tab: Configurações
# --------------------------------------------------------------------------- #
with tab_config:
    st.subheader("Configurações do Motor de Classificação")
    settings_db = db.get_all_settings()

    with st.form("form_configuracoes"):
        conta_adiantamentos_codigo = st.text_input(
            "Código da conta de Adiantamentos a Fornecedores",
            settings_db.get("conta_adiantamentos_codigo", ""),
        )
        conta_adiantamentos_descricao = st.text_input(
            "Descrição da conta de Adiantamentos a Fornecedores",
            settings_db.get("conta_adiantamentos_descricao", ""),
        )
        conta_banco_codigo = st.text_input(
            "Código da conta contábil do Banco (usada na exportação)",
            settings_db.get("conta_banco_codigo", ""),
        )
        conta_banco_descricao = st.text_input(
            "Descrição da conta contábil do Banco",
            settings_db.get("conta_banco_descricao", ""),
        )
        tolerancia_dias = st.number_input(
            "Tolerância de dias entre extrato e razão (Prioridade 3)",
            min_value=0, max_value=30, value=int(settings_db.get("tolerancia_dias_data", 3)),
        )
        limiar_fuzzy = st.slider(
            "Limiar mínimo de similaridade textual (Prioridade 4, fuzzy matching geral)",
            min_value=50, max_value=100, value=int(float(settings_db.get("limiar_fuzzy_historico", 80))),
        )
        limiar_confianca_minima = st.slider(
            "Confiança mínima para considerar uma classificação confiável",
            min_value=0, max_value=100, value=int(float(settings_db.get("limiar_confianca_minima", 60))),
        )
        if st.form_submit_button("💾 Salvar Configurações"):
            db.set_setting("conta_adiantamentos_codigo", conta_adiantamentos_codigo)
            db.set_setting("conta_adiantamentos_descricao", conta_adiantamentos_descricao)
            db.set_setting("conta_banco_codigo", conta_banco_codigo)
            db.set_setting("conta_banco_descricao", conta_banco_descricao)
            db.set_setting("tolerancia_dias_data", str(tolerancia_dias))
            db.set_setting("limiar_fuzzy_historico", str(limiar_fuzzy))
            db.set_setting("limiar_confianca_minima", str(limiar_confianca_minima))
            st.success("Configurações salvas. Reprocesse o extrato para aplicar as mudanças.")
