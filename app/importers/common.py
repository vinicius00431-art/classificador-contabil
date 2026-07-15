"""Utilidades compartilhadas pelos importadores (detecção de colunas, datas, valores)."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any, Optional

from dateutil import parser as date_parser

from app.normalize import normalize_text

logger = logging.getLogger(__name__)

_VALOR_RE = re.compile(r"-?\d{1,3}(?:\.\d{3})*(?:,\d{2})|-?\d+(?:\.\d{2})?")


def safe_str(value: Any) -> str:
    """Converte para string tratando None/NaN como string vazia (evita 'nan' literal)."""
    if value is None:
        return ""
    if isinstance(value, float) and value != value:  # NaN
        return ""
    return str(value).strip()


def find_column(
    columns: list[str], aliases: list[str], excluir: Optional[set[str]] = None
) -> Optional[str]:
    """Encontra a coluna cujo nome normalizado melhor casa com algum alias.

    Prioriza (1) igualdade exata e (2) aliases mais específicos (mais longos)
    para evitar que colunas como "Descrição Conta" sejam confundidas com
    "Histórico" apenas porque ambas contêm a palavra "descricao". Colunas já
    atribuídas a outro campo (`excluir`) são ignoradas, então o chamador deve
    resolver primeiro as colunas mais específicas (ex.: conta contábil) e
    excluí-las antes de procurar as mais genéricas (ex.: histórico).
    """
    excluir = excluir or set()
    normalized = {col: normalize_text(col) for col in columns if col not in excluir}

    for alias in aliases:
        for col, norm in normalized.items():
            if norm == alias:
                return col

    for alias in sorted(aliases, key=len, reverse=True):
        for col, norm in normalized.items():
            if alias in norm:
                return col
    return None


def parse_date_flexible(value: Any) -> Optional[date]:
    if value is None or (isinstance(value, float) and value != value):  # NaN
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return date_parser.parse(text, dayfirst=True, fuzzy=True).date()
    except (ValueError, OverflowError):
        logger.warning("Não foi possível interpretar a data: %r", value)
        return None


def parse_valor_flexible(value: Any) -> Optional[float]:
    """Converte valores em formatos BR (1.234,56) ou US (1234.56) para float."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    negativo = text.startswith("-") or text.endswith("-") or "(" in text
    text = re.sub(r"[^\d,.\-]", "", text)
    if not text:
        return None
    if "," in text and "." in text:
        # Formato BR: 1.234,56 -> remove milhar, troca vírgula por ponto
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        num = float(text.replace("-", ""))
    except ValueError:
        logger.warning("Não foi possível interpretar o valor: %r", value)
        return None
    return -num if negativo else num
