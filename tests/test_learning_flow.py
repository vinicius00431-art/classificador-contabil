"""Valida que uma correção manual é aprendida e aplicada em nova classificação."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db
from app.classification.engine import ClassificationSettings, classificar_lancamento
from app.classification.learning import record_correction
from app.importers.extrato import load_extrato
from app.importers.razao import load_razao
from app.models import OrigemClassificacao

BASE = Path(__file__).resolve().parent.parent / "sample_data"


def main() -> None:
    db.init_db()
    extrato = load_extrato(str(BASE / "extrato_exemplo.csv"), "extrato_exemplo.csv")
    razao = load_razao(str(BASE / "razao_exemplo.csv"), "razao_exemplo.csv")
    settings = ClassificationSettings(
        tolerancia_dias=3, limiar_fuzzy=80, limiar_confianca_minima=60,
        conta_adiantamentos_codigo="1.1.3.001",
        conta_adiantamentos_descricao="Adiantamentos a Fornecedores",
    )

    alvo = next(l for l in extrato if "XPTO" in l.historico)
    antes = classificar_lancamento(alvo, razao, settings)
    print(f"Antes da correção: origem={antes.origem.value} conta={antes.conta_codigo} confianca={antes.confianca}")
    assert antes.origem == OrigemClassificacao.ADIANTAMENTOS, "esperado cair em Adiantamentos antes da correção"

    record_correction(alvo, antes.conta_codigo, "5.9.9.099", "Despesas Diversas XPTO")

    depois = classificar_lancamento(alvo, razao, settings)
    print(f"Depois da correção: origem={depois.origem.value} conta={depois.conta_codigo} confianca={depois.confianca}")
    assert depois.origem == OrigemClassificacao.APRENDIZADO, "esperado origem Aprendizado após correção"
    assert depois.conta_codigo == "5.9.9.099"

    print("\nOK: aprendizado funcionando corretamente.")


if __name__ == "__main__":
    main()
