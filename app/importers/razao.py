"""Importação e normalização do razão contábil (Excel, CSV, PDF)."""
from __future__ import annotations

import logging
import re
from typing import Union, BinaryIO, Optional

import pandas as pd

from app.importers.common import find_column, parse_date_flexible, parse_valor_flexible, safe_str
from app.importers.extrato import ALIASES_DATA, ALIASES_DOCUMENTO, ALIASES_HISTORICO
from app.models import LancamentoRazao
from app.normalize import normalize_text

logger = logging.getLogger(__name__)

ALIASES_CONTA_CODIGO = ["codigo conta", "conta contabil", "cod conta", "conta"]
ALIASES_CONTA_DESCRICAO = ["descricao conta", "nome conta", "denominacao conta", "descricao"]
ALIASES_VALOR = ["valor lancamento", "valor movimento", "valor"]
ALIASES_CREDITO = ["valor credito", "credito"]
ALIASES_DEBITO = ["valor debito", "debito"]

FileInput = Union[str, bytes, BinaryIO]

_CONTA_SPLIT_RE = re.compile(r"^\s*([\d.\-/]{3,})\s*[-–—]?\s*(.*)$")


def load_razao(file: FileInput, filename: str) -> list[LancamentoRazao]:
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
        raise ValueError(f"Formato de razão não suportado: {ext}")
    return _dataframe_to_razao(df, filename)


def _dataframe_to_razao(df: pd.DataFrame, filename: str) -> list[LancamentoRazao]:
    df = df.dropna(how="all")
    columns = list(df.columns)

    # Resolve da coluna mais específica para a mais genérica, excluindo as já
    # atribuídas — evita que "Descrição Conta" seja confundida com "Histórico".
    usadas: set[str] = set()

    def _find(aliases: list[str]) -> Optional[str]:
        col = find_column(columns, aliases, excluir=usadas)
        if col:
            usadas.add(col)
        return col

    col_data = _find(ALIASES_DATA)
    col_conta_codigo = _find(ALIASES_CONTA_CODIGO)
    col_conta_descricao = _find(ALIASES_CONTA_DESCRICAO)
    col_doc = _find(ALIASES_DOCUMENTO)
    col_credito = _find(ALIASES_CREDITO)
    col_debito = _find(ALIASES_DEBITO)
    col_valor = _find(ALIASES_VALOR)
    col_hist = _find(ALIASES_HISTORICO)

    if not col_data or not col_conta_codigo:
        raise ValueError(
            "Não foi possível identificar as colunas de Data e Conta Contábil no razão. "
            f"Colunas encontradas: {columns}"
        )

    lancamentos: list[LancamentoRazao] = []
    for _, row in df.iterrows():
        data_val = parse_date_flexible(row.get(col_data))
        if data_val is None:
            continue

        conta_bruta = safe_str(row.get(col_conta_codigo, ""))
        if col_conta_descricao:
            conta_codigo = conta_bruta
            conta_descricao = safe_str(row.get(col_conta_descricao, ""))
        else:
            conta_codigo, conta_descricao = split_conta(conta_bruta)

        if not conta_codigo:
            continue

        historico = safe_str(row.get(col_hist, "")) if col_hist else ""
        documento = safe_str(row.get(col_doc, "")) if col_doc else ""

        valor = None
        if col_credito or col_debito:
            credito = parse_valor_flexible(row.get(col_credito)) if col_credito else None
            debito = parse_valor_flexible(row.get(col_debito)) if col_debito else None
            valor = (credito or 0) - (debito or 0) if (credito or debito) else None
        elif col_valor:
            valor = parse_valor_flexible(row.get(col_valor))
        if valor is None:
            continue

        lancamentos.append(
            LancamentoRazao(
                data=data_val,
                conta_codigo=conta_codigo,
                conta_descricao=conta_descricao,
                historico=historico,
                historico_normalizado=normalize_text(historico),
                documento=documento,
                valor=valor,
            )
        )
    logger.info("Razão %s: %d lançamentos importados", filename, len(lancamentos))
    return lancamentos


def split_conta(texto: str) -> tuple[str, str]:
    match = _CONTA_SPLIT_RE.match(texto)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return texto, ""


def _parse_pdf(file: FileInput, filename: str) -> list[LancamentoRazao]:
    import pdfplumber

    lancamentos: list[LancamentoRazao] = []
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                if not table or len(table) < 2:
                    continue
                header, *rows = table
                df = pd.DataFrame(rows, columns=[str(h or "") for h in header])
                try:
                    lancamentos.extend(_dataframe_to_razao(df, filename))
                except ValueError:
                    continue
    logger.info("Razão PDF %s: %d lançamentos importados", filename, len(lancamentos))
    return lancamentos
