"""Configuração central da aplicação."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "contabil.db"

# Chaves de configuração persistidas na tabela `settings` (ver app/db.py).
# Os valores abaixo são apenas os defaults usados na primeira execução.
DEFAULT_SETTINGS = {
    "conta_adiantamentos_codigo": "1.1.3.001",
    "conta_adiantamentos_descricao": "Adiantamentos a Fornecedores",
    "conta_banco_codigo": "1.1.1.01.001",
    "conta_banco_descricao": "Banco Conta Movimento",
    "tolerancia_dias_data": "3",
    "limiar_fuzzy_historico": "80",
    "limiar_confianca_minima": "60",
    "layout_exportacao": "dominio_padrao",
}

# Pesos usados no cálculo de confiança da classificação (somam 100).
PESO_FORNECEDOR_EXATO = 40
PESO_HISTORICO_SIMILAR = 25
PESO_VALOR_DATA = 20
PESO_FUZZY = 15
