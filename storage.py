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

# Whitelist echter Spaltennamen fuer models_ranked_by_recent_metric() - der Spaltenname wird
# dort direkt in SQL interpoliert, daher nie ungeprueft aus einem Aufrufer-Parameter uebernehmen.
TIMELINE_METRIC_COLUMNS = {
    "tokens_per_s", "generation_s", "ttft_s", "latency_s", "tokens_out", "tokens_in", "cost_usd",
}

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

# Spalten, die nach dem ersten Release ergänzt wurden - ALTER TABLE statt neuer SCHEMA-Version,
# damit eine bestehende runs.db nicht neu angelegt werden muss.
MIGRATIONS = [
    ("ttft_s", "REAL"),
    ("generation_s", "REAL"),
    ("tokens_per_s", "REAL"),
    ("reasoning_tokens", "INTEGER"),
    ("sent_params", "TEXT"),
    ("stars", "INTEGER"),  # 1-5, NULL = nicht bewertet
    ("is_best", "INTEGER"),  # 1 = "Beste Antwort" für diesen Prompt in diesem Lauf, sonst 0/NULL
    ("prompt_text", "TEXT"),  # Wortlaut des Prompts zum Zeitpunkt des Laufs - NULL bei älteren Zeilen
    ("finish_reason", "TEXT"),  # z.B. "stop"/"length" - NULL bei älteren Zeilen
]


class RunStore:
    def __init__(self, db_path: str = "runs.db"):
        self.db_path = db_path
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(SCHEMA)
            existing = {row[1] for row in conn.execute("PRAGMA table_info(results)")}
            for column, sql_type in MIGRATIONS:
                if column not in existing:
                    conn.execute(f"ALTER TABLE results ADD COLUMN {column} {sql_type}")

    def save_results(self, results: list) -> int:
        """Speichert Ergebniszeilen; gleiche (run_id, model_id, prompt_id) werden überschrieben."""
        rows = [
            (
                r["run_id"], r["timestamp"], r["model_id"], r["prompt_id"], r.get("technique"),
                1 if r["ok"] else 0, r.get("response"), r.get("tokens_in"), r.get("tokens_out"),
                r.get("latency_s"), r.get("cost_usd"), 1 if r.get("injected_context") else 0,
                json.dumps(r.get("retrieved_sources", []), ensure_ascii=False),
                r.get("ttft_s"), r.get("generation_s"), r.get("tokens_per_s"), r.get("reasoning_tokens"),
                json.dumps(r.get("sent_params"), ensure_ascii=False) if r.get("sent_params") is not None else None,
                r.get("stars"), 1 if r.get("is_best") else 0, r.get("prompt_text"), r.get("finish_reason"),
            )
            for r in results
        ]
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO results VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows
            )
        return len(rows)

    def set_stars(self, run_id: str, model_id: str, prompt_id: str, stars: int) -> None:
        """1-5 Sterne für eine einzelne Antwort (run_id/model_id/prompt_id)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE results SET stars = ? WHERE run_id = ? AND model_id = ? AND prompt_id = ?",
                (stars, run_id, model_id, prompt_id),
            )

    def set_best_answer(self, run_id: str, prompt_id: str, model_id: str | None) -> None:
        """Markiert `model_id` als beste Antwort für diesen Prompt in diesem Lauf (None = keine)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE results SET is_best = 0 WHERE run_id = ? AND prompt_id = ?", (run_id, prompt_id))
            if model_id is not None:
                conn.execute(
                    "UPDATE results SET is_best = 1 WHERE run_id = ? AND prompt_id = ? AND model_id = ?",
                    (run_id, prompt_id, model_id),
                )

    def wins_per_model(self) -> pd.DataFrame:
        """{model_id, wins} über alle Läufe - Grundlage für "Siege pro Modell" in der Timeline."""
        with sqlite3.connect(self.db_path) as conn:
            return pd.read_sql_query(
                "SELECT model_id, COUNT(*) AS wins FROM results WHERE is_best = 1 "
                "GROUP BY model_id ORDER BY wins DESC",
                conn,
            )

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

    def models_ranked_by_recent_metric(self, model_ids: list, metric: str, limit: int | None = None) -> list:
        """Modelle aus model_ids mit mindestens einem Wert für `metric`, sortiert nach dem

        Zeitstempel ihres jüngsten solchen Laufs (neuester Lauf zuerst) - Grundlage für die
        Timeline-Standardauswahl (ein Modell ohne jeden Wert für die aktuell gewählte Metrik
        taugt dort als Linie nichts, ein zuletzt aktiv genutztes Modell mit Werten schon).
        """
        if metric not in TIMELINE_METRIC_COLUMNS:
            raise ValueError(f"Unbekannte Timeline-Metrik: {metric!r}")
        if not model_ids:
            return []
        marks = ",".join("?" for _ in model_ids)
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT model_id, MAX(timestamp) AS last_ts FROM results "
                f"WHERE model_id IN ({marks}) AND ok = 1 AND {metric} IS NOT NULL "
                f"GROUP BY model_id ORDER BY last_ts DESC",
                model_ids,
            ).fetchall()
        ranked = [r[0] for r in rows]
        return ranked[:limit] if limit is not None else ranked

    def known_models(self) -> list:
        """Modelle mit mindestens einem erfolgreichen Lauf - reine Fehlschläge taugen nicht als

        Timeline-Auswahl (es gibt dafür ja keine Latenz/Tokens/Kosten zum Anzeigen).
        """
        with sqlite3.connect(self.db_path) as conn:
            return [
                r[0] for r in conn.execute(
                    "SELECT DISTINCT model_id FROM results WHERE ok = 1 ORDER BY model_id"
                )
            ]

    def run_count(self) -> int:
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute("SELECT COUNT(DISTINCT run_id) FROM results").fetchone()[0]
