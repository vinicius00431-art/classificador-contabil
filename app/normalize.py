"""Funções de normalização de texto e valores usadas em todo o pipeline."""
from __future__ import annotations

import re

from unidecode import unidecode

_WHITESPACE_RE = re.compile(r"\s+")
_SPECIAL_CHARS_RE = re.compile(r"[^a-z0-9 ]")


def normalize_text(value: str | None) -> str:
    """Remove acentos, caixa, caracteres especiais e espaços extras.

    Usado como chave de comparação/fuzzy matching — nunca para exibição.
    """
    if not value:
        return ""
    text = unidecode(str(value)).lower()
    text = _SPECIAL_CHARS_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def normalize_document(value: str | None) -> str:
    """Normaliza número de documento mantendo apenas dígitos e letras."""
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def extract_possible_favorecido(historico_normalizado: str) -> str:
    """Heurística simples: remove tokens comuns de lançamentos bancários
    (prefixos de operação) para isolar o nome do favorecido/fornecedor.
    """
    tokens_ignorados = {
        "pix", "ted", "doc", "transferencia", "pagamento", "recebimento",
        "boleto", "compra", "cartao", "debito", "credito", "tarifa",
        "enviado", "recebido", "de", "para", "a", "o", "em", "referente",
        "ref", "nr", "n", "deposito", "saque",
    }
    tokens = [t for t in historico_normalizado.split() if t not in tokens_ignorados]
    return " ".join(tokens).strip()
