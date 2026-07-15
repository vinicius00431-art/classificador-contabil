"""Importação e normalização do balancete (Excel, CSV, PDF)."""
from __future__ import annotations

import logging
from typing import BinaryIO, Union

import pandas as pd

from app.importers.common import find_column, parse_valor_flexible, safe_str
from app.importers.razao import ALIASES_CONTA_CODIGO, ALIASES_CONTA_DESCRICAO, split_conta
from app.models import ContaBalancete

logger = logging.getLogger(__name__)

ALIASES_SALDO_ANTERIOR = ["saldo anterior", "saldo inicial"]
ALIASES_DEBITO = ["total debito", "movimento debito", "debito"]
ALIASES_CREDITO = ["total credito", "movimento credito", "credito"]
ALIASES_SALDO_ATUAL = ["saldo atual", "saldo final", "saldo"]

FileInput = Union[str, bytes, BinaryIO]


def load_balancete(file: FileInput, filename: str) -> list[ContaBalancete]:
    ext = filename.lower().rsplit(".", 1)[-1]
    if ext == "csv":
        try:
            df = pd.read_csv(file, sep=None, engine="python", dtype=str)
        except Exception:
            if hasattr(file, "seek"):
                file.seek(0)
            df = pd.read_csv(file, sep=";", dtype=str, encoding="latin-1")
    elif ext in ("xlsx", "xls"):
        df = pd.read_excel(file, dtype=str)
    elif ext == "pdf":
        return _parse_pdf(file, filename)
    else:
        raise ValueError(f"Formato de balancete não suportado: {ext}")
    return _dataframe_to_balancete(df, filename)


def _dataframe_to_balancete(df: pd.DataFrame, filename: str) -> list[ContaBalancete]:
    df = df.dropna(how="all")
    columns = list(df.columns)

    usadas: set[str] = set()

    def _find(aliases: list[str]) -> str | None:
        col = find_column(columns, aliases, excluir=usadas)
        if col:
            usadas.add(col)
        return col

    col_conta_codigo = _find(ALIASES_CONTA_CODIGO)
    col_conta_descricao = _find(ALIASES_CONTA_DESCRICAO)
    col_saldo_anterior = _find(ALIASES_SALDO_ANTERIOR)
    col_debito = _find(ALIASES_DEBITO)
    col_credito = _find(ALIASES_CREDITO)
    col_saldo_atual = _find(ALIASES_SALDO_ATUAL)

    if not col_conta_codigo:
        raise ValueError(
            f"Não foi possível identificar a coluna de Conta Contábil no balancete. Colunas: {columns}"
        )

    contas: list[ContaBalancete] = []
    for _, row in df.iterrows():
        conta_bruta = safe_str(row.get(col_conta_codigo, ""))
        if not conta_bruta:
            continue
        if col_conta_descricao:
            conta_codigo = conta_bruta
            conta_descricao = safe_str(row.get(col_conta_descricao, ""))
        else:
            conta_codigo, conta_descricao = split_conta(conta_bruta)
        if not conta_codigo:
            continue

        contas.append(
            ContaBalancete(
                conta_codigo=conta_codigo,
                conta_descricao=conta_descricao,
                saldo_anterior=parse_valor_flexible(row.get(col_saldo_anterior)) or 0.0 if col_saldo_anterior else 0.0,
                debito=parse_valor_flexible(row.get(col_debito)) or 0.0 if col_debito else 0.0,
                credito=parse_valor_flexible(row.get(col_credito)) or 0.0 if col_credito else 0.0,
                saldo_atual=parse_valor_flexible(row.get(col_saldo_atual)) or 0.0 if col_saldo_atual else 0.0,
            )
        )
    logger.info("Balancete %s: %d contas importadas", filename, len(contas))
    return contas


def _parse_pdf(file: FileInput, filename: str) -> list[ContaBalancete]:
    import pdfplumber

    contas: list[ContaBalancete] = []
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                if not table or len(table) < 2:
                    continue
                header, *rows = table
                df = pd.DataFrame(rows, columns=[str(h or "") for h in header])
                try:
                    contas.extend(_dataframe_to_balancete(df, filename))
                except ValueError:
                    continue
    logger.info("Balancete PDF %s: %d contas importadas", filename, len(contas))
    return contas
