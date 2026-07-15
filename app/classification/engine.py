"""Motor de classificação: aplica as regras de prioridade a cada lançamento do extrato."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.classification import learning, matcher, patterns
from app.models import ClassificacaoResultado, LancamentoExtrato, LancamentoRazao, OrigemClassificacao

logger = logging.getLogger(__name__)

CONFIANCA_DOCUMENTO_EXATO = 98
CONFIANCA_FAVORECIDO_EXATO = 95
LIMIAR_HISTORICO_JA_CONTABILIZADO = 90
CONFIANCA_VALOR_DATA_BASE = 90
CONFIANCA_VALOR_DATA_PENALIDADE_POR_DIA = 8
CONFIANCA_VALOR_DATA_MINIMA = 50


@dataclass
class ClassificationSettings:
    tolerancia_dias: int
    limiar_fuzzy: float
    limiar_confianca_minima: float
    conta_adiantamentos_codigo: str
    conta_adiantamentos_descricao: str


def classificar_lancamento(
    lancamento: LancamentoExtrato,
    razao: list[LancamentoRazao],
    settings: ClassificationSettings,
) -> ClassificacaoResultado:
    """Aplica, em ordem, as regras de prioridade descritas na especificação."""

    # Padrões manuais cadastrados têm precedência absoluta (regra explícita do usuário).
    pattern = patterns.match_pattern(lancamento)
    if pattern:
        return ClassificacaoResultado(
            lancamento=lancamento,
            conta_codigo=pattern.conta_codigo,
            conta_descricao=pattern.conta_descricao,
            confianca=100.0,
            origem=OrigemClassificacao.PADRAO,
            detalhe=f"Padrão cadastrado ({pattern.tipo}: '{pattern.valor}')",
        )

    # Aprendizado de correções anteriores do usuário.
    learned = learning.find_learned_rule(lancamento)
    if learned:
        return ClassificacaoResultado(
            lancamento=lancamento,
            conta_codigo=learned.conta_codigo,
            conta_descricao=learned.conta_descricao,
            confianca=learned.confianca,
            origem=OrigemClassificacao.APRENDIZADO,
            detalhe=f"Aprendido a partir de {learned.ocorrencias} correção(ões) anterior(es)",
        )

    # Documento idêntico é o sinal mais forte de que é o mesmo lançamento no razão.
    doc_matches = matcher.buscar_por_documento(lancamento, razao)
    if doc_matches:
        alvo = doc_matches[0]
        return _resultado_razao(
            lancamento, alvo, CONFIANCA_DOCUMENTO_EXATO, "Documento idêntico encontrado no razão"
        )

    # Prioridade 1: mesmo fornecedor/favorecido exatamente igual ao do razão.
    favorecido_match = matcher.favorecido_exato_match(lancamento, razao)
    if favorecido_match:
        return _resultado_razao(
            lancamento, favorecido_match, CONFIANCA_FAVORECIDO_EXATO,
            "Fornecedor/favorecido já existente no razão",
        )

    # Prioridade 2: histórico muito semelhante a um já contabilizado (limiar alto).
    candidato, score = matcher.melhor_match_fuzzy(
        lancamento, razao, limiar=LIMIAR_HISTORICO_JA_CONTABILIZADO
    )
    if candidato:
        return _resultado_razao(
            lancamento, candidato, score, f"Histórico semelhante já contabilizado ({score:.0f}%)"
        )

    # Prioridade 3: mesmo valor e data próxima (dentro da tolerância configurada).
    candidatos_valor_data = matcher.buscar_por_valor_data(lancamento, razao, settings.tolerancia_dias)
    if candidatos_valor_data:
        alvo = min(candidatos_valor_data, key=lambda r: abs((r.data - lancamento.data).days))
        dias = abs((alvo.data - lancamento.data).days)
        confianca = max(
            CONFIANCA_VALOR_DATA_MINIMA,
            CONFIANCA_VALOR_DATA_BASE - dias * CONFIANCA_VALOR_DATA_PENALIDADE_POR_DIA,
        )
        return _resultado_razao(
            lancamento, alvo, confianca, f"Mesmo valor e data próxima (Δ {dias} dia(s))"
        )

    # Prioridade 4: fuzzy matching geral, limiar configurável (mais permissivo).
    candidato, score = matcher.melhor_match_fuzzy(lancamento, razao, limiar=settings.limiar_fuzzy)
    if candidato:
        return _resultado_razao(
            lancamento, candidato, score * 0.9, f"Correspondência por similaridade textual ({score:.0f}%)"
        )

    # Prioridade 5: nenhuma regra encontrou conta válida -> conta configurável de fallback.
    return ClassificacaoResultado(
        lancamento=lancamento,
        conta_codigo=settings.conta_adiantamentos_codigo,
        conta_descricao=settings.conta_adiantamentos_descricao,
        confianca=0.0,
        origem=OrigemClassificacao.ADIANTAMENTOS,
        detalhe="Nenhuma correspondência encontrada no razão, padrões ou aprendizado",
    )


def _resultado_razao(
    lancamento: LancamentoExtrato, alvo: LancamentoRazao, confianca: float, detalhe: str
) -> ClassificacaoResultado:
    return ClassificacaoResultado(
        lancamento=lancamento,
        conta_codigo=alvo.conta_codigo,
        conta_descricao=alvo.conta_descricao,
        confianca=round(confianca, 1),
        origem=OrigemClassificacao.RAZAO,
        detalhe=detalhe,
    )


def classificar_extrato(
    lancamentos: list[LancamentoExtrato],
    razao: list[LancamentoRazao],
    settings: ClassificationSettings,
) -> list[ClassificacaoResultado]:
    resultados = [classificar_lancamento(l, razao, settings) for l in lancamentos]
    logger.info("Classificados %d lançamentos do extrato", len(resultados))
    return resultados


def generate_report(
    resultados: list[ClassificacaoResultado], limiar_confianca_minima: float
) -> dict[str, int | float]:
    total = len(resultados)
    por_origem = {origem.value: 0 for origem in OrigemClassificacao if origem != OrigemClassificacao.SEM_CONFIANCA}
    baixa_confianca = 0
    for r in resultados:
        por_origem[r.origem.value] = por_origem.get(r.origem.value, 0) + 1
        if r.confianca < limiar_confianca_minima and r.origem != OrigemClassificacao.ADIANTAMENTOS:
            baixa_confianca += 1

    return {
        "total_lancamentos": total,
        "classificados_razao": por_origem.get(OrigemClassificacao.RAZAO.value, 0),
        "classificados_padrao": por_origem.get(OrigemClassificacao.PADRAO.value, 0),
        "classificados_aprendizado": por_origem.get(OrigemClassificacao.APRENDIZADO.value, 0),
        "enviados_adiantamentos": por_origem.get(OrigemClassificacao.ADIANTAMENTOS.value, 0),
        "sem_confianca_suficiente": baixa_confianca,
        "confianca_media": round(sum(r.confianca for r in resultados) / total, 1) if total else 0.0,
    }
