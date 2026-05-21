"""
Memória Persistente com SQLite
Armazena histórico de conversas e fatos importantes entre sessões
"""

import sqlite3
import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path("memory.db")


class Memory:
    def __init__(self, db_path: str = str(DB_PATH)):
        self.db_path = db_path
        self._init_db()
        logger.info(f"Memoria SQLite inicializada em: {db_path}")

    def _init_db(self):
        """Cria as tabelas se não existirem."""
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS messages (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     TEXT    NOT NULL,
                    role        TEXT    NOT NULL,
                    content     TEXT    NOT NULL,
                    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS facts (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     TEXT    NOT NULL,
                    key         TEXT    NOT NULL,
                    value       TEXT    NOT NULL,
                    updated_at  TEXT    NOT NULL DEFAULT (datetime('now')),
                    UNIQUE(user_id, key)
                );

                CREATE INDEX IF NOT EXISTS idx_messages_user
                    ON messages(user_id, created_at DESC);
            """)

    # ── Histórico de Mensagens ────────────────────────────────────────────────
    def save_message(self, user_id: str, role: str, content: str):
        """Persiste uma mensagem no banco."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO messages (user_id, role, content) VALUES (?, ?, ?)",
                (str(user_id), role, content)
            )

    def get_history(self, user_id: str, limit: int = 20) -> list[dict]:
        """Recupera as últimas N mensagens de um usuário."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """SELECT role, content FROM messages
                   WHERE user_id = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (str(user_id), limit)
            ).fetchall()
        # Retorna em ordem cronológica
        return [{"role": r, "parts": [c]} for r, c in reversed(rows)]

    def clear_history(self, user_id: str):
        """Apaga o histórico de um usuário."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM messages WHERE user_id = ?", (str(user_id),))
        logger.info(f"Historico limpo para user_id={user_id}")

    # ── Fatos Persistentes ───────────────────────────────────────────────────
    def save_fact(self, user_id: str, key: str, value: str):
        """Salva ou atualiza um fato sobre o usuário (ex: nome, preferências)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO facts (user_id, key, value, updated_at)
                   VALUES (?, ?, ?, datetime('now'))
                   ON CONFLICT(user_id, key) DO UPDATE SET
                       value = excluded.value,
                       updated_at = excluded.updated_at""",
                (str(user_id), key, value)
            )

    def get_facts(self, user_id: str) -> dict:
        """Retorna todos os fatos salvos sobre o usuário."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT key, value FROM facts WHERE user_id = ?",
                (str(user_id),)
            ).fetchall()
        return {k: v for k, v in rows}

    def message_count(self, user_id: str) -> int:
        """Retorna quantas mensagens o usuário já trocou."""
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM messages WHERE user_id = ?",
                (str(user_id),)
            ).fetchone()[0]