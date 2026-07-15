"""Camada de acesso ao banco: usuários, configurações, padrões e aprendizado.

Todo dado de configuração/padrão/aprendizado é isolado por `usuario_id` —
nenhuma conta enxerga ou altera os dados de outra.

Por padrão usa um arquivo SQLite local (bom para rodar na sua máquina).
Se as credenciais do Turso (banco SQLite remoto e persistente) estiverem
configuradas via `st.secrets` ou variáveis de ambiente, usa o Turso no
lugar — isso é o que mantém as contas e dados vivos quando o app está
hospedado no Streamlit Community Cloud (cujo disco local não persiste
entre reinícios).
"""
from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator, Optional, Sequence

from app.config import DB_PATH

logger = logging.getLogger(__name__)

SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        nome_exibicao TEXT NOT NULL,
        criado_em TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS settings (
        usuario_id INTEGER NOT NULL,
        key TEXT NOT NULL,
        value TEXT NOT NULL,
        PRIMARY KEY (usuario_id, key),
        FOREIGN KEY (usuario_id) REFERENCES users(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS patterns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER NOT NULL,
        tipo TEXT NOT NULL,
        valor TEXT NOT NULL,
        conta_codigo TEXT NOT NULL,
        conta_descricao TEXT NOT NULL,
        ativo INTEGER NOT NULL DEFAULT 1,
        criado_em TEXT NOT NULL,
        FOREIGN KEY (usuario_id) REFERENCES users(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS learned_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER NOT NULL,
        chave TEXT NOT NULL,
        conta_codigo TEXT NOT NULL,
        conta_descricao TEXT NOT NULL,
        ocorrencias INTEGER NOT NULL DEFAULT 1,
        atualizado_em TEXT NOT NULL,
        UNIQUE (usuario_id, chave),
        FOREIGN KEY (usuario_id) REFERENCES users(id)
    )
    """,
    """
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
    )
    """,
]


def _turso_credentials() -> tuple[Optional[str], Optional[str]]:
    """Lê URL/token do Turso via st.secrets (Streamlit Cloud) ou variáveis de ambiente."""
    try:
        import streamlit as st

        if "turso" in st.secrets:
            return st.secrets["turso"].get("url"), st.secrets["turso"].get("auth_token")
    except Exception:
        pass
    return os.environ.get("TURSO_DATABASE_URL"), os.environ.get("TURSO_AUTH_TOKEN")


class _LibsqlCursorAdapter:
    """Faz um ResultSet do libsql se comportar como um cursor do sqlite3."""

    def __init__(self, result_set: Any) -> None:
        self._rs = result_set
        self.lastrowid = getattr(result_set, "last_insert_rowid", None)

    def fetchone(self) -> Any:
        return self._rs.rows[0] if self._rs.rows else None

    def fetchall(self) -> list[Any]:
        return list(self._rs.rows)


class _LibsqlConnAdapter:
    """Faz um client do libsql (Turso) se comportar como uma Connection do sqlite3."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def execute(self, sql: str, params: Sequence[Any] = ()) -> _LibsqlCursorAdapter:
        result_set = self._client.execute(sql, list(params) if params else None)
        return _LibsqlCursorAdapter(result_set)

    def executescript(self, sql: str) -> None:
        statements = [s.strip() for s in sql.split(";") if s.strip()]
        self._client.batch(statements)

    def commit(self) -> None:
        pass  # cada execute() já é commitado individualmente pelo servidor Turso

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        self._client.close()


@contextmanager
def get_connection() -> Iterator[Any]:
    url, token = _turso_credentials()
    if url:
        import libsql_client as libsql

        # O client usa WebSocket para "libsql://"/"wss://", que falhou no teste;
        # "https://" (Hrana sobre HTTP) funciona de forma mais confiável.
        if url.startswith("libsql://"):
            url = "https://" + url[len("libsql://"):]
        elif url.startswith("wss://"):
            url = "https://" + url[len("wss://"):]

        client = libsql.create_client_sync(url, auth_token=token or "")
        conn = _LibsqlConnAdapter(client)
        try:
            yield conn
        finally:
            conn.close()
        return

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
        for statement in SCHEMA_STATEMENTS:
            conn.execute(statement)
    logger.info("Banco de dados inicializado (%s)", "Turso" if _turso_credentials()[0] else DB_PATH)


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
