"""Funções de similaridade e busca de candidatos no razão (fuzzy matching)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from rapidfuzz import fuzz, process

from app.models import LancamentoExtrato, LancamentoRazao
from app.normalize import extract_possible_favorecido, normalize_document


def historico_similarity(a: str, b: str) -> float:
    """Similaridade 0-100 entre dois textos já normalizados."""
    if not a or not b:
        return 0.0
    return fuzz.token_sort_ratio(a, b)


def buscar_por_valor_data(
    lancamento: LancamentoExtrato, razao: list[LancamentoRazao], tolerancia_dias: int
) -> list[LancamentoRazao]:
    """Candidatos com o mesmo valor absoluto e data dentro da tolerância."""
    candidatos = []
    for r in razao:
        if abs(abs(r.valor) - lancamento.valor) <= 0.01:
            if abs((r.data - lancamento.data).days) <= tolerancia_dias:
                candidatos.append(r)
    return candidatos


def buscar_por_documento(
    lancamento: LancamentoExtrato, razao: list[LancamentoRazao]
) -> list[LancamentoRazao]:
    doc_norm = normalize_document(lancamento.documento)
    if not doc_norm:
        return []
    return [r for r in razao if r.documento and normalize_document(r.documento) == doc_norm]


def favorecido_exato_match(
    lancamento: LancamentoExtrato, razao: list[LancamentoRazao]
) -> Optional[LancamentoRazao]:
    """Prioridade 1: mesmo favorecido/fornecedor já lançado no razão."""
    favorecido = extract_possible_favorecido(lancamento.historico_normalizado)
    if not favorecido:
        return None
    for r in razao:
        favorecido_r = extract_possible_favorecido(r.historico_normalizado)
        if favorecido_r and favorecido_r == favorecido:
            return r
    return None


def melhor_match_fuzzy(
    lancamento: LancamentoExtrato, razao: list[LancamentoRazao], limiar: float
) -> tuple[Optional[LancamentoRazao], float]:
    """Melhor correspondência de histórico por fuzzy matching (token_sort_ratio)."""
    choices = {i: r.historico_normalizado for i, r in enumerate(razao) if r.historico_normalizado}
    if not choices or not lancamento.historico_normalizado:
        return None, 0.0
    result = process.extractOne(
        lancamento.historico_normalizado, choices, scorer=fuzz.token_sort_ratio
    )
    if result is None:
        return None, 0.0
    _match_text, score, idx = result
    if score < limiar:
        return None, score
    return razao[idx], score


@dataclass
class MatchCandidate:
    razao: LancamentoRazao
    score: float
    criterio: str
