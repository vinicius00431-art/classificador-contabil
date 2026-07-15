"""Autenticação simples por usuário/senha (sem dependências externas).

Cada usuário tem seu próprio cadastro de padrões, aprendizado e configurações
— nada é compartilhado entre contas diferentes.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
from dataclasses import dataclass
from typing import Optional

from app.config import DEFAULT_SETTINGS
from app.db import get_connection, now_iso

logger = logging.getLogger(__name__)

_PBKDF2_ITERATIONS = 200_000
_ALGORITHM = "sha256"


@dataclass
class Usuario:
    id: int
    username: str
    nome_exibicao: str


def _hash_password(password: str, salt: bytes) -> str:
    derived = hashlib.pbkdf2_hmac(_ALGORITHM, password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return derived.hex()


def _make_password_hash(password: str) -> str:
    salt = os.urandom(16)
    return f"{salt.hex()}${_hash_password(password, salt)}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, hash_hex = stored.split("$", 1)
    except ValueError:
        return False
    salt = bytes.fromhex(salt_hex)
    candidate = _hash_password(password, salt)
    return hmac.compare_digest(candidate, hash_hex)


def username_exists(username: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM users WHERE username = ?", (username.strip().lower(),)
        ).fetchone()
        return row is not None


def create_user(username: str, password: str, nome_exibicao: str) -> Usuario:
    username = username.strip().lower()
    if not username or not password:
        raise ValueError("Usuário e senha são obrigatórios.")
    if username_exists(username):
        raise ValueError("Esse nome de usuário já está em uso.")

    password_hash = _make_password_hash(password)
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO users (username, password_hash, nome_exibicao, criado_em) VALUES (?, ?, ?, ?)",
            (username, password_hash, nome_exibicao.strip() or username, now_iso()),
        )
        usuario_id = cursor.lastrowid
        for key, value in DEFAULT_SETTINGS.items():
            conn.execute(
                "INSERT INTO settings (usuario_id, key, value) VALUES (?, ?, ?)",
                (usuario_id, key, value),
            )
    logger.info("Novo usuário criado: %s (id=%s)", username, usuario_id)
    return Usuario(id=usuario_id, username=username, nome_exibicao=nome_exibicao.strip() or username)


def verify_user(username: str, password: str) -> Optional[Usuario]:
    username = username.strip().lower()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash, nome_exibicao FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    if row is None:
        return None
    if not _verify_password(password, row["password_hash"]):
        return None
    return Usuario(id=row["id"], username=row["username"], nome_exibicao=row["nome_exibicao"])
