"""Valida que padrões, aprendizado e configurações de um usuário não vazam para outro."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import auth, db
from app.classification import patterns
from app.classification.engine import ClassificationSettings, classificar_lancamento
from app.classification.learning import record_correction
from app.importers.extrato import load_extrato
from app.importers.razao import load_razao
from app.models import OrigemClassificacao

BASE = Path(__file__).resolve().parent.parent / "sample_data"


def main() -> None:
    db.init_db()
    marido = auth.create_user("marido_teste", "senha123", "Marido")
    esposa = auth.create_user("esposa_teste", "senha456", "Esposa")

    extrato = load_extrato(str(BASE / "extrato_exemplo.csv"), "extrato_exemplo.csv")
    razao = load_razao(str(BASE / "razao_exemplo.csv"), "razao_exemplo.csv")
    settings = ClassificationSettings(
        tolerancia_dias=3, limiar_fuzzy=80, limiar_confianca_minima=60,
        conta_adiantamentos_codigo="1.1.3.001",
        conta_adiantamentos_descricao="Adiantamentos a Fornecedores",
    )

    # 1) Padrão cadastrado pelo marido não deve aparecer para a esposa.
    patterns.add_pattern(marido.id, "palavra_chave", "posto combustivel", "4.1.3.020", "Combustivel")
    assert len(patterns.list_patterns(marido.id)) == 1
    assert len(patterns.list_patterns(esposa.id)) == 0
    print("OK: padrão cadastrado pelo marido não aparece para a esposa.")

    # 2) Login com senha errada deve falhar.
    assert auth.verify_user("marido_teste", "senha_errada") is None
    assert auth.verify_user("marido_teste", "senha123") is not None
    print("OK: verificação de senha funcionando.")

    # 3) Correção aprendida pela esposa não deve valer para o marido.
    alvo = next(l for l in extrato if "XPTO" in l.historico)
    record_correction(esposa.id, alvo, None, "5.5.5.055", "Conta da Esposa")

    resultado_esposa = classificar_lancamento(alvo, razao, settings, esposa.id)
    resultado_marido = classificar_lancamento(alvo, razao, settings, marido.id)
    assert resultado_esposa.origem == OrigemClassificacao.APRENDIZADO
    assert resultado_esposa.conta_codigo == "5.5.5.055"
    assert resultado_marido.origem == OrigemClassificacao.ADIANTAMENTOS, (
        "aprendizado da esposa vazou para o marido!"
    )
    print("OK: aprendizado da esposa não vaza para o marido.")

    # 4) Configurações são independentes por usuário.
    db.set_setting(esposa.id, "conta_adiantamentos_codigo", "9.9.9.999")
    assert db.get_setting(esposa.id, "conta_adiantamentos_codigo") == "9.9.9.999"
    assert db.get_setting(marido.id, "conta_adiantamentos_codigo") == "1.1.3.001"
    print("OK: configurações isoladas por usuário.")

    print("\nTODOS OS TESTES DE ISOLAMENTO PASSARAM.")


if __name__ == "__main__":
    main()
