"""Camada de acesso ao SQLite: usuários, configurações, padrões e aprendizado.

Todo dado de configuração/padrão/aprendizado é isolado por `usuario_id` —
nenhuma conta enxerga ou altera os dados de outra.
"""
from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator, Optional

from app.config import DB_PATH

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    nome_exibicao TEXT NOT NULL,
    criado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    usuario_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (usuario_id, key),
    FOREIGN KEY (usuario_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER NOT NULL,
    tipo TEXT NOT NULL,                 -- 'palavra_chave' | 'expressao' | 'favorecido'
    valor TEXT NOT NULL,                -- termo/expressão a procurar (normalizado)
    conta_codigo TEXT NOT NULL,
    conta_descricao TEXT NOT NULL,
    ativo INTEGER NOT NULL DEFAULT 1,
    criado_em TEXT NOT NULL,
    FOREIGN KEY (usuario_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS learned_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER NOT NULL,
    chave TEXT NOT NULL,                -- histórico normalizado (ou favorecido) usado como chave de aprendizado
    conta_codigo TEXT NOT NULL,
    conta_descricao TEXT NOT NULL,
    ocorrencias INTEGER NOT NULL DEFAULT 1,
    atualizado_em TEXT NOT NULL,
    UNIQUE (usuario_id, chave),
    FOREIGN KEY (usuario_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS correction_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER NOT NULL,
    data_lancamento TEXT,
    historico TEXT,
    valor REAL,
    conta_sugerida TEXT,
    conta_corrigida TEXT,
    conta_corrigida_descricao TEXT,
    criado_em TEXT NOT NULL,
    FOREIGN KEY (usuario_id) REFERENCES users(id)
);
"""


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Cria as tabelas caso não existam."""
    with get_connection() as conn:
        conn.executescript(SCHEMA)
    logger.info("Banco de dados inicializado em %s", DB_PATH)


def get_setting(usuario_id: int, key: str, default: Optional[str] = None) -> Optional[str]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE usuario_id = ? AND key = ?", (usuario_id, key)
        ).fetchone()
        return row["value"] if row else default


def set_setting(usuario_id: int, key: str, value: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO settings (usuario_id, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(usuario_id, key) DO UPDATE SET value = excluded.value",
            (usuario_id, key, value),
        )


def get_all_settings(usuario_id: int) -> dict[str, str]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT key, value FROM settings WHERE usuario_id = ?", (usuario_id,)
        ).fetchall()
        return {row["key"]: row["value"] for row in rows}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")
