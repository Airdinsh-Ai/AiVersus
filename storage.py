# -*- coding: utf-8 -*-
#
# AiVersus – Lauf-Speicherung (Evo V0.3)
# © 2026 Airdinsh (Erdinç Arslan) · MIT License · Masterschool AI Engineering Track
# Signlab@gmx.de · https://Airdinsh.com
#

"""
Speichert jede Ergebniszeile dauerhaft in einer lokalen SQLite-Datei (runs.db).
Grundlage für die Timeline: ohne das gäbe es nach einem Neustart keine alten Läufe.
"""

import json
import sqlite3

import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS results (
    run_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    model_id TEXT NOT NULL,
    prompt_id TEXT NOT NULL,
    technique TEXT,
    ok INTEGER NOT NULL,
    response TEXT,
    tokens_in INTEGER,
    tokens_out INTEGER,
    latency_s REAL,
    cost_usd REAL,
    injected_context INTEGER,
    retrieved_sources TEXT,
    PRIMARY KEY (run_id, model_id, prompt_id)
);
"""


class RunStore:
    def __init__(self, db_path: str = "runs.db"):
        self.db_path = db_path
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(SCHEMA)

    def save_results(self, results: list) -> int:
        """Speichert Ergebniszeilen; gleiche (run_id, model_id, prompt_id) werden überschrieben."""
        rows = [
            (
                r["run_id"], r["timestamp"], r["model_id"], r["prompt_id"], r.get("technique"),
                1 if r["ok"] else 0, r.get("response"), r.get("tokens_in"), r.get("tokens_out"),
                r.get("latency_s"), r.get("cost_usd"), 1 if r.get("injected_context") else 0,
                json.dumps(r.get("retrieved_sources", []), ensure_ascii=False),
            )
            for r in results
        ]
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany("INSERT OR REPLACE INTO results VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        return len(rows)

    def load_for_models(self, model_ids: list) -> pd.DataFrame:
        """Erfolgreiche Zeilen (ok=1) der gewählten Modelle, älteste zuerst.

        Fehlgeschlagene Calls verzerren Latenz/Tokens/Kosten-Mittelwerte und
        gehören nicht in die Timeline - die steht nur in der Ergebnistabelle.
        """
        if not model_ids:
            return pd.DataFrame()
        marks = ",".join("?" for _ in model_ids)
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql_query(
                f"SELECT * FROM results WHERE model_id IN ({marks}) AND ok = 1 ORDER BY timestamp",
                conn, params=model_ids,
            )
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df

    def known_models(self) -> list:
        with sqlite3.connect(self.db_path) as conn:
            return [r[0] for r in conn.execute("SELECT DISTINCT model_id FROM results ORDER BY model_id")]

    def run_count(self) -> int:
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute("SELECT COUNT(DISTINCT run_id) FROM results").fetchone()[0]
