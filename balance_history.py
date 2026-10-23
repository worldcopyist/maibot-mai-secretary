"""Local, append-only history of successful DeepSeek balance queries."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class BalanceHistoryStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS balance_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    queried_at TEXT NOT NULL,
                    source TEXT NOT NULL,
                    alias TEXT NOT NULL,
                    account_fingerprint TEXT NOT NULL,
                    is_available INTEGER NOT NULL,
                    balance_infos TEXT NOT NULL
                )
            """)
            db.execute("""
                CREATE INDEX IF NOT EXISTS balance_snapshots_account_idx
                ON balance_snapshots (account_fingerprint, id DESC)
            """)

    def insert(self, snapshot: dict[str, Any]) -> None:
        with sqlite3.connect(self.path) as db:
            db.execute(
                """INSERT INTO balance_snapshots
                   (queried_at, source, alias, account_fingerprint, is_available, balance_infos)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    snapshot["queried_at"], snapshot["source"], snapshot["alias"],
                    snapshot["account_fingerprint"], int(snapshot["is_available"]),
                    json.dumps(snapshot["balance_infos"], ensure_ascii=False),
                ),
            )

    def latest(self, account_fingerprint: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.path) as db:
            row = db.execute(
                """SELECT queried_at, source, alias, is_available, balance_infos
                   FROM balance_snapshots WHERE account_fingerprint = ?
                   ORDER BY id DESC LIMIT 1""",
                (account_fingerprint,),
            ).fetchone()
        if row is None:
            return None
        return {
            "queried_at": row[0], "source": row[1], "alias": row[2],
            "account_fingerprint": account_fingerprint,
            "is_available": bool(row[3]), "balance_infos": json.loads(row[4]),
        }
