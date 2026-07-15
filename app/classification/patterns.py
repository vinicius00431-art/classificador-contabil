"""Cadastro de padrões manuais (palavra-chave, expressão ou favorecido -> conta)."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

from app.db import get_connection, now_iso
from app.models import LancamentoExtrato
from app.normalize import extract_possible_favorecido, normalize_text

logger = logging.getLogger(__name__)

TIPOS_VALIDOS = ("palavra_chave", "expressao", "favorecido")


@dataclass
class Pattern:
    id: int
    tipo: str
    valor: str
    conta_codigo: str
    conta_descricao: str
    ativo: bool


def add_pattern(usuario_id: int, tipo: str, valor: str, conta_codigo: str, conta_descricao: str) -> int:
    if tipo not in TIPOS_VALIDOS:
        raise ValueError(f"Tipo de padrão inválido: {tipo}. Use um de {TIPOS_VALIDOS}")
    valor_normalizado = normalize_text(valor) if tipo != "expressao" else valor.strip()
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO patterns (usuario_id, tipo, valor, conta_codigo, conta_descricao, ativo, criado_em) "
            "VALUES (?, ?, ?, ?, ?, 1, ?)",
            (usuario_id, tipo, valor_normalizado, conta_codigo.strip(), conta_descricao.strip(), now_iso()),
        )
        return cursor.lastrowid


def list_patterns(usuario_id: int, apenas_ativos: bool = False) -> list[Pattern]:
    query = "SELECT * FROM patterns WHERE usuario_id = ?"
    if apenas_ativos:
        query += " AND ativo = 1"
    query += " ORDER BY id DESC"
    with get_connection() as conn:
        rows = conn.execute(query, (usuario_id,)).fetchall()
    return [
        Pattern(
            id=row["id"], tipo=row["tipo"], valor=row["valor"],
            conta_codigo=row["conta_codigo"], conta_descricao=row["conta_descricao"],
            ativo=bool(row["ativo"]),
        )
        for row in rows
    ]


def update_pattern(pattern_id: int, usuario_id: int, **fields) -> None:
    if not fields:
        return
    allowed = {"tipo", "valor", "conta_codigo", "conta_descricao", "ativo"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    with get_connection() as conn:
        conn.execute(
            f"UPDATE patterns SET {set_clause} WHERE id = ? AND usuario_id = ?",
            (*updates.values(), pattern_id, usuario_id),
        )


def delete_pattern(pattern_id: int, usuario_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM patterns WHERE id = ? AND usuario_id = ?", (pattern_id, usuario_id)
        )


def match_pattern(lancamento: LancamentoExtrato, usuario_id: int) -> Optional[Pattern]:
    """Retorna o padrão cadastrado (do usuário) mais específico que casar com o lançamento."""
    candidatos: list[Pattern] = []
    for pattern in list_patterns(usuario_id, apenas_ativos=True):
        if _pattern_matches(pattern, lancamento):
            candidatos.append(pattern)
    if not candidatos:
        return None
    return max(candidatos, key=lambda p: len(p.valor))


def _pattern_matches(pattern: Pattern, lancamento: LancamentoExtrato) -> bool:
    historico_norm = lancamento.historico_normalizado
    if pattern.tipo == "palavra_chave":
        # Comparação por substring (não apenas token exato) para suportar
        # palavras-chave compostas por mais de uma palavra (ex.: "posto combustivel").
        return bool(pattern.valor) and pattern.valor in historico_norm
    if pattern.tipo == "favorecido":
        favorecido = extract_possible_favorecido(historico_norm)
        return bool(pattern.valor) and pattern.valor in favorecido
    if pattern.tipo == "expressao":
        try:
            return bool(re.search(pattern.valor, lancamento.historico, re.IGNORECASE))
        except re.error:
            logger.warning("Expressão regular inválida no padrão %s: %r", pattern.id, pattern.valor)
            return False
    return False
