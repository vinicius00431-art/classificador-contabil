"""Teste manual de fumaça: roda o pipeline completo sobre os dados de exemplo."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import auth, db
from app.classification.engine import ClassificationSettings, classificar_extrato, generate_report
from app.importers.extrato import load_extrato
from app.importers.razao import load_razao

BASE = Path(__file__).resolve().parent.parent / "sample_data"


def main() -> None:
    db.init_db()
    usuario = auth.create_user("teste_smoke", "senha123", "Usuário de Teste")

    extrato = load_extrato(str(BASE / "extrato_exemplo.csv"), "extrato_exemplo.csv")
    razao = load_razao(str(BASE / "razao_exemplo.csv"), "razao_exemplo.csv")

    print(f"Extrato: {len(extrato)} lançamentos | Razão: {len(razao)} lançamentos\n")

    settings = ClassificationSettings(
        tolerancia_dias=3, limiar_fuzzy=80, limiar_confianca_minima=60,
        conta_adiantamentos_codigo="1.1.3.001",
        conta_adiantamentos_descricao="Adiantamentos a Fornecedores",
    )
    resultados = classificar_extrato(extrato, razao, settings, usuario.id)

    for r in resultados:
        print(
            f"{r.lancamento.data} | {r.lancamento.historico[:40]:40s} | "
            f"R$ {r.lancamento.valor:>10.2f} | -> {r.conta_codigo or '---':12s} "
            f"({r.conta_descricao or '---':25s}) | {r.confianca:5.1f}% | {r.origem.value:12s} | {r.detalhe}"
        )

    print("\nRelatório:")
    for k, v in generate_report(resultados, settings.limiar_confianca_minima).items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
