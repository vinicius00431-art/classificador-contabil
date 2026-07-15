"""Aprendizado de padrões a partir de correções manuais do usuário."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from app.db import get_connection, now_iso
from app.models import LancamentoExtrato
from app.normalize import extract_possible_favorecido

logger = logging.getLogger(__name__)

CONFIANCA_BASE_APRENDIZADO = 70
CONFIANCA_MAXIMA_APRENDIZADO = 95
INCREMENTO_POR_OCORRENCIA = 5


@dataclass
class LearnedRule:
    conta_codigo: str
    conta_descricao: str
    ocorrencias: int

    @property
    def confianca(self) -> float:
        return min(
            CONFIANCA_MAXIMA_APRENDIZADO,
            CONFIANCA_BASE_APRENDIZADO + self.ocorrencias * INCREMENTO_POR_OCORRENCIA,
        )


def _chave_aprendizado(lancamento: LancamentoExtrato) -> str:
    favorecido = extract_possible_favorecido(lancamento.historico_normalizado)
    return favorecido if len(favorecido) >= 3 else lancamento.historico_normalizado


def record_correction(
    lancamento: LancamentoExtrato,
    conta_sugerida: str | None,
    conta_corrigida: str,
    conta_corrigida_descricao: str,
) -> None:
    """Grava a correção feita pelo usuário e reforça a regra de aprendizado."""
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO correction_log "
            "(data_lancamento, historico, valor, conta_sugerida, conta_corrigida, "
            " conta_corrigida_descricao, criado_em) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                lancamento.data.isoformat(), lancamento.historico, lancamento.valor,
                conta_sugerida, conta_corrigida, conta_corrigida_descricao, now_iso(),
            ),
        )

        chave = _chave_aprendizado(lancamento)
        if not chave:
            return
        row = conn.execute("SELECT * FROM learned_rules WHERE chave = ?", (chave,)).fetchone()
        if row:
            conn.execute(
                "UPDATE learned_rules SET conta_codigo = ?, conta_descricao = ?, "
                "ocorrencias = ocorrencias + 1, atualizado_em = ? WHERE chave = ?",
                (conta_corrigida, conta_corrigida_descricao, now_iso(), chave),
            )
        else:
            conn.execute(
                "INSERT INTO learned_rules (chave, conta_codigo, conta_descricao, ocorrencias, atualizado_em) "
                "VALUES (?, ?, ?, 1, ?)",
                (chave, conta_corrigida, conta_corrigida_descricao, now_iso()),
            )
    logger.info("Correção registrada para chave=%r -> conta=%s", chave, conta_corrigida)


def find_learned_rule(lancamento: LancamentoExtrato) -> Optional[LearnedRule]:
    """Prioridade 2/4: procura regra aprendida a partir de correções anteriores."""
    favorecido = extract_possible_favorecido(lancamento.historico_normalizado)
    candidatos_chave = [k for k in (favorecido, lancamento.historico_normalizado) if k]

    with get_connection() as conn:
        for chave in candidatos_chave:
            row = conn.execute(
                "SELECT conta_codigo, conta_descricao, ocorrencias FROM learned_rules WHERE chave = ?",
                (chave,),
            ).fetchone()
            if row:
                return LearnedRule(
                    conta_codigo=row["conta_codigo"],
                    conta_descricao=row["conta_descricao"],
                    ocorrencias=row["ocorrencias"],
                )
    return None
