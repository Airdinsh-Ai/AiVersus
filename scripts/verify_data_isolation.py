# -*- coding: utf-8 -*-
#
# AiVersus - Beweis-Skript fuer Testisolation (siehe CLAUDE.md)
# (c) 2026 Airdinsh (Erdinc Arslan) . MIT License . Masterschool AI Engineering Track
# Signlab@gmx.de . https://Airdinsh.com
#

"""
Beweist, dass ein vollstaendiger Benchmark-Lauf die echten Projektdaten (data/runs.db)
nicht beruehrt, wenn AIVERSUS_DATA_DIR und AIVERSUS_BASE_URL wie in CLAUDE.md
vorgeschrieben gesetzt sind, bevor app.py ausgefuehrt wird.

Ablauf: startet einen winzigen lokalen Mock-Server im OpenAI-API-Format, zeigt
AIVERSUS_BASE_URL darauf, AIVERSUS_DATA_DIR auf ein frisches Temp-Verzeichnis, fuehrt
per AppTest einen kompletten Benchmark-Lauf aus (ein Mock-Modell, ein Prompt) und
vergleicht die Zeilenzahl der ECHTEN data/runs.db vorher/nachher - sie darf sich
nicht aendern.

Aufruf: uv run python scripts/verify_data_isolation.py
"""

import json
import os
import sqlite3
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REAL_RUNS_DB = PROJECT_ROOT / "data" / "runs.db"
MODEL_ID = "mock/verify-echo"


class _MockHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args) -> None:
        pass  # ruhig - nur ein Beweis-Lauf, kein Debug-Tool

    def handle_one_request(self) -> None:
        # Der openai-Client schliesst die Keep-Alive-Verbindung nach dem letzten Call aktiv -
        # das naechste readline() darauf ist ein erwarteter ConnectionResetError, kein Fehler.
        try:
            super().handle_one_request()
        except (ConnectionError, OSError):
            self.close_connection = True

    def _write_chunk(self, text: str) -> None:
        # Der openai-Client schliesst die Verbindung, sobald er "[DONE]" gesehen hat - der
        # letzte (leere) Chunk danach darf also auf einen schon geschlossenen Socket treffen.
        try:
            data = text.encode("utf-8")
            self.wfile.write(f"{len(data):x}\r\n".encode("ascii"))
            self.wfile.write(data)
            self.wfile.write(b"\r\n")
            self.wfile.flush()
        except (ConnectionError, OSError):
            pass

    def do_GET(self) -> None:
        if not self.path.startswith("/v1/models"):
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps({
            "object": "list",
            "data": [{"id": MODEL_ID, "object": "model", "created": 1700000000, "owned_by": "mock"}],
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            req = json.loads(raw.decode("utf-8"))
        except Exception:
            req = {}
        if not self.path.startswith("/v1/chat/completions"):
            self.send_response(404)
            self.end_headers()
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        want_usage = bool((req.get("stream_options") or {}).get("include_usage"))
        base = {"id": "chatcmpl-verify", "object": "chat.completion.chunk", "created": 1700000000, "model": MODEL_ID}
        self._write_chunk(f"data: {json.dumps({**base, 'choices': [{'index': 0, 'delta': {'content': 'ok'}, 'finish_reason': None}]})}\n\n")
        self._write_chunk(f"data: {json.dumps({**base, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})}\n\n")
        if want_usage:
            usage_chunk = {**base, "choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4}}
            self._write_chunk(f"data: {json.dumps(usage_chunk)}\n\n")
        self._write_chunk("data: [DONE]\n\n")
        self._write_chunk("")


def _start_mock_server() -> tuple:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MockHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    return server, f"http://127.0.0.1:{port}/v1"


def _row_count(db_path: Path) -> int:
    if not db_path.exists():
        return 0
    con = sqlite3.connect(db_path)
    try:
        return con.execute("SELECT COUNT(*) FROM results").fetchone()[0]
    finally:
        con.close()


def main() -> int:
    rows_before = _row_count(REAL_RUNS_DB)
    print(f"Zeilen in {REAL_RUNS_DB} vor dem Mock-Lauf: {rows_before}")

    server, mock_base_url = _start_mock_server()
    try:
        with tempfile.TemporaryDirectory(prefix="aiversus_verify_", ignore_cleanup_errors=True) as tmp_dir:
            os.environ["AIVERSUS_DATA_DIR"] = tmp_dir
            os.environ["AIVERSUS_BASE_URL"] = mock_base_url

            sys.path.insert(0, str(PROJECT_ROOT))
            from streamlit.testing.v1 import AppTest

            at = AppTest.from_file(str(PROJECT_ROOT / "app.py"))
            at.run(timeout=30)
            assert not at.exception, f"Fehler beim initialen Lauf: {at.exception}"

            at.text_input(key="nvidia_api_key").input("verify-key").run(timeout=30)
            assert not at.exception, f"Fehler nach Key-Eingabe: {at.exception}"

            at.selectbox(key="model_picker").select(MODEL_ID).run(timeout=30)
            assert not at.exception, f"Fehler nach Modellauswahl: {at.exception}"

            add_button = next(b for b in at.button if b.label.strip() == "Add")
            add_button.click().run(timeout=30)
            assert not at.exception, f"Fehler nach Add-Klick: {at.exception}"

            start_button = next(b for b in at.button if "Start benchmark" in b.label)
            start_button.click().run(timeout=30)
            assert not at.exception, f"Fehler nach Start-Klick: {at.exception}"

            # Der Benchmark laeuft ueber ein @st.fragment(run_every=0.4) weiter, solange
            # Futures offen sind - mehrfach nachrunnen, bis der Mock-Call durch ist.
            for _ in range(20):
                if at.session_state.get("run") is None:
                    break
                at.run(timeout=30)
            assert at.session_state.get("run") is None, "Benchmark ist nicht fertig geworden"
            assert len(at.session_state.get("results", [])) == 2, "Erwartete 2 Ergebniszeilen (1 Modell x 2 Prompts)"

            tmp_runs_db = Path(tmp_dir) / "runs.db"
            tmp_rows = _row_count(tmp_runs_db)
            print(f"Zeilen in der Temp-runs.db ({tmp_runs_db}): {tmp_rows}")
            assert tmp_rows == 2, f"Mock-Lauf hat nicht wie erwartet in die Temp-DB geschrieben: {tmp_rows}"
    finally:
        server.shutdown()
        os.environ.pop("AIVERSUS_DATA_DIR", None)
        os.environ.pop("AIVERSUS_BASE_URL", None)

    rows_after = _row_count(REAL_RUNS_DB)
    print(f"Zeilen in {REAL_RUNS_DB} nach dem Mock-Lauf: {rows_after}")
    if rows_after != rows_before:
        print("FEHLGESCHLAGEN: die echte data/runs.db hat sich veraendert!")
        return 1

    print("ERFOLG: Mock-Lauf hat ausschliesslich die Temp-runs.db beschrieben, "
          "die echte data/runs.db ist unveraendert geblieben.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
