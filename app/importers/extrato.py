"""Importação e normalização do extrato bancário (CSV, XLSX, OFX, PDF)."""
from __future__ import annotations

import io
import logging
import re
from typing import Any, BinaryIO, Union

import pandas as pd

from app.importers.common import find_column, parse_date_flexible, parse_valor_flexible, safe_str
from app.models import LancamentoExtrato, TipoLancamento
from app.normalize import normalize_text

logger = logging.getLogger(__name__)

ALIASES_DATA = ["data lancamento", "data movimento", "dt lancamento", "data", "dt"]
ALIASES_HISTORICO = [
    "historico", "descricao", "complemento", "discriminacao", "lancamento", "detalhe",
]
ALIASES_DOCUMENTO = ["numero documento", "nr documento", "num documento", "documento", "doc"]
ALIASES_VALOR = ["valor lancamento", "valor movimento", "montante", "valor"]
ALIASES_TIPO = ["tipo lancamento", "natureza", "indicador", "tipo", "cd"]
ALIASES_CREDITO = ["valor credito", "credito", "entrada"]
ALIASES_DEBITO = ["valor debito", "debito", "saida"]

FileInput = Union[str, bytes, BinaryIO]


def load_extrato(file: FileInput, filename: str) -> list[LancamentoExtrato]:
    """Ponto de entrada único: detecta o formato pelo nome do arquivo e delega."""
    ext = filename.lower().rsplit(".", 1)[-1]
    if ext == "csv":
        df = _read_csv(file)
        return _dataframe_to_lancamentos(df, filename)
    if ext in ("xlsx", "xls"):
        df = pd.read_excel(file, dtype=str)
        return _dataframe_to_lancamentos(df, filename)
    if ext == "ofx":
        return _parse_ofx(file, filename)
    if ext == "pdf":
        return _parse_pdf(file, filename)
    raise ValueError(f"Formato de extrato não suportado: {ext}")


def _read_csv(file: FileInput) -> pd.DataFrame:
    try:
        return pd.read_csv(file, sep=None, engine="python", dtype=str)
    except Exception:
        if hasattr(file, "seek"):
            file.seek(0)
        return pd.read_csv(file, sep=";", dtype=str, encoding="latin-1")


def _dataframe_to_lancamentos(df: pd.DataFrame, filename: str) -> list[LancamentoExtrato]:
    df = df.dropna(how="all")
    columns = list(df.columns)

    # Resolve da coluna mais específica para a mais genérica, excluindo as já
    # atribuídas — evita colisões entre aliases parecidos (ex.: "descricao").
    usadas: set[str] = set()

    def _find(aliases: list[str]) -> str | None:
        col = find_column(columns, aliases, excluir=usadas)
        if col:
            usadas.add(col)
        return col

    col_data = _find(ALIASES_DATA)
    col_doc = _find(ALIASES_DOCUMENTO)
    col_credito = _find(ALIASES_CREDITO)
    col_debito = _find(ALIASES_DEBITO)
    col_valor = _find(ALIASES_VALOR)
    col_tipo = _find(ALIASES_TIPO)
    col_hist = _find(ALIASES_HISTORICO)

    if not col_data or not col_hist:
        raise ValueError(
            "Não foi possível identificar as colunas de Data e Histórico no extrato. "
            f"Colunas encontradas: {columns}"
        )

    lancamentos: list[LancamentoExtrato] = []
    for idx, row in df.iterrows():
        data_val = parse_date_flexible(row.get(col_data))
        if data_val is None:
            continue
        historico = safe_str(row.get(col_hist, ""))
        documento = safe_str(row.get(col_doc, "")) if col_doc else ""

        valor, tipo = _resolve_valor_tipo(row, col_valor, col_tipo, col_credito, col_debito)
        if valor is None:
            continue

        lancamentos.append(
            LancamentoExtrato(
                data=data_val,
                historico=historico,
                historico_normalizado=normalize_text(historico),
                documento=documento,
                valor=abs(valor),
                tipo=tipo,
                origem_arquivo=filename,
                linha_id=idx,
            )
        )
    logger.info("Extrato %s: %d lançamentos importados", filename, len(lancamentos))
    return lancamentos


def _resolve_valor_tipo(
    row: pd.Series, col_valor: str | None, col_tipo: str | None,
    col_credito: str | None, col_debito: str | None,
) -> tuple[float | None, TipoLancamento]:
    if col_credito or col_debito:
        credito = parse_valor_flexible(row.get(col_credito)) if col_credito else None
        debito = parse_valor_flexible(row.get(col_debito)) if col_debito else None
        if credito:
            return credito, TipoLancamento.CREDITO
        if debito:
            return debito, TipoLancamento.DEBITO
        return None, TipoLancamento.CREDITO

    if col_valor:
        valor = parse_valor_flexible(row.get(col_valor))
        if valor is None:
            return None, TipoLancamento.CREDITO
        if col_tipo:
            tipo_texto = normalize_text(str(row.get(col_tipo, "")))
            if any(t in tipo_texto for t in ("d", "debito", "saida")) and "credito" not in tipo_texto:
                return abs(valor), TipoLancamento.DEBITO
            return abs(valor), TipoLancamento.CREDITO
        return abs(valor), TipoLancamento.CREDITO if valor >= 0 else TipoLancamento.DEBITO

    return None, TipoLancamento.CREDITO


def _parse_ofx(file: FileInput, filename: str) -> list[LancamentoExtrato]:
    from ofxparse import OfxParser  # import tardio: dependência pesada, só quando necessário

    if isinstance(file, (bytes, str)):
        buffer = io.BytesIO(file.encode() if isinstance(file, str) else file)
    else:
        buffer = file
    ofx = OfxParser.parse(buffer)

    lancamentos: list[LancamentoExtrato] = []
    linha_id = 0
    for account in ofx.accounts:
        for txn in account.statement.transactions:
            historico = (txn.memo or txn.payee or "").strip()
            valor = float(txn.amount)
            documento = str(getattr(txn, "checknum", "") or getattr(txn, "id", "") or "").strip()
            lancamentos.append(
                LancamentoExtrato(
                    data=txn.date.date() if hasattr(txn.date, "date") else txn.date,
                    historico=historico,
                    historico_normalizado=normalize_text(historico),
                    documento=documento,
                    valor=abs(valor),
                    tipo=TipoLancamento.CREDITO if valor >= 0 else TipoLancamento.DEBITO,
                    origem_arquivo=filename,
                    linha_id=linha_id,
                )
            )
            linha_id += 1
    logger.info("Extrato OFX %s: %d lançamentos importados", filename, len(lancamentos))
    return lancamentos


_PDF_LINE_RE = re.compile(
    r"(?P<data>\d{2}[/.]\d{2}[/.]\d{2,4})\s+(?P<historico>.+?)\s+(?P<valor>-?\d{1,3}(?:\.\d{3})*,\d{2})\s*(?P<sinal>[DC]?)$"
)


def _parse_pdf(file: FileInput, filename: str) -> list[LancamentoExtrato]:
    import pdfplumber

    lancamentos: list[LancamentoExtrato] = []
    linha_id = 0
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            if tables:
                for table in tables:
                    if not table or len(table) < 2:
                        continue
                    header, *rows = table
                    df = pd.DataFrame(rows, columns=[str(h or "") for h in header])
                    try:
                        parsed = _dataframe_to_lancamentos(df, filename)
                        lancamentos.extend(parsed)
                        continue
                    except ValueError:
                        pass  # tabela não parecia um extrato, tenta via texto abaixo

            text = page.extract_text() or ""
            for line in text.splitlines():
                match = _PDF_LINE_RE.match(line.strip())
                if not match:
                    continue
                data_val = parse_date_flexible(match.group("data"))
                valor = parse_valor_flexible(match.group("valor"))
                if data_val is None or valor is None:
                    continue
                sinal = match.group("sinal")
                tipo = TipoLancamento.DEBITO if sinal == "D" or valor < 0 else TipoLancamento.CREDITO
                historico = match.group("historico").strip()
                lancamentos.append(
                    LancamentoExtrato(
                        data=data_val,
                        historico=historico,
                        historico_normalizado=normalize_text(historico),
                        documento="",
                        valor=abs(valor),
                        tipo=tipo,
                        origem_arquivo=filename,
                        linha_id=linha_id,
                    )
                )
                linha_id += 1
    logger.info("Extrato PDF %s: %d lançamentos importados", filename, len(lancamentos))
    return lancamentos
