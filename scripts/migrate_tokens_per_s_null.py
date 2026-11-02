# -*- coding: utf-8 -*-
#
# AiVersus - Migration: tokens_per_s auf NULL setzen, wo generation_s < 0.05s
# (c) 2026 Airdinsh (Erdinc Arslan) . MIT License . Masterschool AI Engineering Track
# Signlab@gmx.de . https://Airdinsh.com
#

"""
Einmalige Datenmigration fuer bestehende runs.db-Zeilen, die VOR dem "tokens_per_s als '-'
bei generation_s < 0.05s"-Fix (app.py, _tokens_per_s()) entstanden sind und daher noch eine
irrefuehrend hohe Tokens/s-Zahl aus einer Mikro-Dauer tragen (Messrauschen, kein echter Wert).

Ohne --apply nur ein Dry-Run: zaehlt und listet betroffene Zeilen, aendert nichts.
Mit --apply: setzt tokens_per_s = NULL fuer diese Zeilen. Die Gesamtzeilenzahl der Tabelle
aendert sich dabei nie (UPDATE, kein DELETE) - das Skript prueft das selbst vor/nachher.

Aufruf (immer zuerst gegen eine Kopie testen, siehe PROTOKOLL.md/Backlog):
  uv run python scripts/migrate_tokens_per_s_null.py <pfad-zur-runs.db> [--apply]
"""

import sqlite3
import sys

MIN_GENERATION_S_FOR_TOKPS = 0.05  # muss mit app.py:_tokens_per_s() uebereinstimmen


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print("Aufruf: uv run python scripts/migrate_tokens_per_s_null.py <pfad-zur-runs.db> [--apply]")
        return 1
    apply = "--apply" in args
    db_path = next(a for a in args if a != "--apply")

    conn = sqlite3.connect(db_path)
    try:
        total_before = conn.execute("SELECT COUNT(*) FROM results").fetchone()[0]
        affected = conn.execute(
            "SELECT run_id, model_id, prompt_id, generation_s, tokens_per_s FROM results "
            "WHERE generation_s < ? AND tokens_per_s IS NOT NULL",
            (MIN_GENERATION_S_FOR_TOKPS,),
        ).fetchall()

        print(f"Gesamtzeilen: {total_before}")
        print(f"Betroffen (generation_s < {MIN_GENERATION_S_FOR_TOKPS}s, tokens_per_s gesetzt): {len(affected)}")
        for run_id, model_id, prompt_id, generation_s, tokens_per_s in affected:
            print(f"  {run_id} {model_id} {prompt_id}: generation_s={generation_s} tokens_per_s={tokens_per_s}")

        if not apply:
            print("Dry-Run (kein --apply) - nichts geaendert.")
            return 0

        conn.execute(
            "UPDATE results SET tokens_per_s = NULL WHERE generation_s < ? AND tokens_per_s IS NOT NULL",
            (MIN_GENERATION_S_FOR_TOKPS,),
        )
        conn.commit()
        total_after = conn.execute("SELECT COUNT(*) FROM results").fetchone()[0]
        still_affected = conn.execute(
            "SELECT COUNT(*) FROM results WHERE generation_s < ? AND tokens_per_s IS NOT NULL",
            (MIN_GENERATION_S_FOR_TOKPS,),
        ).fetchone()[0]

        if total_after != total_before:
            print(f"FEHLER: Gesamtzeilenzahl geaendert ({total_before} -> {total_after})!")
            return 1
        if still_affected:
            print(f"FEHLER: {still_affected} Zeile(n) immer noch betroffen!")
            return 1

        print(f"Angewendet: {len(affected)} Zeile(n) auf tokens_per_s=NULL gesetzt, Gesamtzeilen unveraendert ({total_after}).")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
