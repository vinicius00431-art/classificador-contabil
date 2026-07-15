"""Modelos de dados (dataclasses) compartilhados entre os módulos."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional


class TipoLancamento(str, Enum):
    CREDITO = "credito"
    DEBITO = "debito"


class OrigemClassificacao(str, Enum):
    RAZAO = "Razão"
    PADRAO = "Padrão"
    APRENDIZADO = "Aprendizado"
    ADIANTAMENTOS = "Adiantamentos"
    SEM_CONFIANCA = "Sem confiança"


@dataclass
class LancamentoExtrato:
    """Um lançamento do extrato bancário, já normalizado."""

    data: date
    historico: str
    historico_normalizado: str
    documento: str
    valor: float
    tipo: TipoLancamento
    origem_arquivo: str = ""
    linha_id: int = 0

    @property
    def valor_assinado(self) -> float:
        return self.valor if self.tipo == TipoLancamento.CREDITO else -self.valor


@dataclass
class LancamentoRazao:
    """Um lançamento do razão contábil."""

    data: date
    conta_codigo: str
    conta_descricao: str
    historico: str
    historico_normalizado: str
    documento: str
    valor: float


@dataclass
class ContaBalancete:
    """Uma linha do balancete (saldo por conta)."""

    conta_codigo: str
    conta_descricao: str
    saldo_anterior: float
    debito: float
    credito: float
    saldo_atual: float


@dataclass
class ClassificacaoResultado:
    """Resultado da classificação de um lançamento do extrato."""

    lancamento: LancamentoExtrato
    conta_codigo: Optional[str]
    conta_descricao: Optional[str]
    confianca: float  # 0-100
    origem: OrigemClassificacao
    detalhe: str = ""
    editado_manualmente: bool = False
