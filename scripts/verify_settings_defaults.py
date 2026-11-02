# -*- coding: utf-8 -*-
#
# AiVersus - Beweis-Skript fuer die Session-State-Defaults rund um settings.json
# (c) 2026 Airdinsh (Erdinc Arslan) . MIT License . Masterschool AI Engineering Track
# Signlab@gmx.de . https://Airdinsh.com
#

"""
Regressionsbeweis fuer einen gemeldeten Bug: save_settings() warf AttributeError, sobald
eine bestehende Sitzung oder eine vorhandene settings.json den Schluessel
last_successful_embed_model nicht kannte (eingefuehrt mit "Embedding-Modelle vor dem
Index-Aufbau pruefen"). Fix: alle Session-State-Schluessel, die save_settings() voraussetzt,
werden im Initialisierungsblock per st.session_state.setdefault(...) angelegt, und
save_settings() liest sie ueber .get(...) statt per Punktzugriff.

Szenario (a): frische Sitzung, settings.json ist eine KOPIE der echten Datei (falls
vorhanden, sonst ein realistisches Beispiel mit 5 Modellen + Sentiment-Prompt), aber ohne
den Schluessel last_successful_embed_model - simuliert eine settings.json aus der
Vorgaengerversion dieses Fixes.

Szenario (b): bestehende Sitzung (Schluessel ist bereits gesetzt), der Schluessel wird
gezielt aus st.session_state entfernt, danach ein Rerun - der naechste save_settings()-
Aufruf darf nicht crashen und muss den Schluessel wiederherstellen.

Laeuft ausschliesslich gegen Temp-Verzeichnisse (AIVERSUS_DATA_DIR) - liest hoechstens die
echte data/settings.json, schreibt nie in echte Projektdaten.

Aufruf: uv run python scripts/verify_settings_defaults.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REAL_SETTINGS = PROJECT_ROOT / "data" / "settings.json"

FALLBACK_SETTINGS = {
    "prompts": [
        {"id": "p1", "text": "Erkläre RAG in 3 Sätzen.", "technique": "Zero-Shot Prompting"},
        {
            "id": "p2",
            "text": (
                "Klassifiziere die Stimmung (positiv/negativ/neutral) der folgenden Aussage.\n\n"
                "Beispiel 1:\nAussage: \"Der Support hat mir super schnell geholfen!\"\nStimmung: positiv\n\n"
                "Jetzt du:\nAussage: \"Die App ist ok, aber der Login hängt sich ständig auf.\"\nStimmung:"
            ),
            "technique": "Few-Shot Prompting",
        },
    ],
    "selected_models": ["org-a/model-1", "org-b/model-2", "org-c/model-3", "org-d/model-4", "org-e/model-5"],
    "model_prices": {"org-a/model-1": {"input": 0.0, "output": 0.0, "free": False}},
}


def _old_version_settings() -> dict:
    """Kopie der echten settings.json ohne last_successful_embed_model, oder ein Fallback

    mit 5 Modellen + Sentiment-Prompt, falls keine echte Datei existiert.
    """
    if REAL_SETTINGS.exists():
        real = json.loads(REAL_SETTINGS.read_text(encoding="utf-8"))
        return {k: v for k, v in real.items() if k != "last_successful_embed_model"}
    return dict(FALLBACK_SETTINGS)


def _run_scenario_a(app_path: str) -> None:
    old_settings = _old_version_settings()
    assert "last_successful_embed_model" not in old_settings

    with tempfile.TemporaryDirectory(prefix="aiversus_verify_settings_a_", ignore_cleanup_errors=True) as tmp_dir:
        os.environ["AIVERSUS_DATA_DIR"] = tmp_dir
        (Path(tmp_dir) / "settings.json").write_text(json.dumps(old_settings), encoding="utf-8")

        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(app_path)
        at.run(timeout=30)
        assert not at.exception, f"Szenario (a) - AttributeError/Exception beim ersten Lauf: {at.exception}"
        assert at.session_state.get("last_successful_embed_model") is None

        new_settings = json.loads((Path(tmp_dir) / "settings.json").read_text(encoding="utf-8"))
        assert "last_successful_embed_model" in new_settings and new_settings["last_successful_embed_model"] is None

    print("Szenario (a) OK: alte settings.json ohne den Schlüssel führt nicht zum Absturz.")


def _run_scenario_b(app_path: str) -> None:
    with tempfile.TemporaryDirectory(prefix="aiversus_verify_settings_b_", ignore_cleanup_errors=True) as tmp_dir:
        os.environ["AIVERSUS_DATA_DIR"] = tmp_dir

        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(app_path)
        at.run(timeout=30)
        assert not at.exception, f"Szenario (b) - Exception beim ersten Lauf: {at.exception}"
        assert "last_successful_embed_model" in at.session_state

        del at.session_state["last_successful_embed_model"]
        at.run(timeout=30)
        assert not at.exception, f"Szenario (b) - AttributeError/Exception nach dem Rerun: {at.exception}"
        assert at.session_state.get("last_successful_embed_model") is None, "setdefault() hätte ihn wiederherstellen müssen"

    print("Szenario (b) OK: ein nachträglich entfernter Schlüssel wird beim Rerun wiederhergestellt, kein Absturz.")


def main() -> int:
    os.environ["AIVERSUS_BASE_URL"] = "http://127.0.0.1:1/v1"  # unbenutzt - diese Pfade rufen keine API
    sys.path.insert(0, str(PROJECT_ROOT))
    app_path = str(PROJECT_ROOT / "app.py")

    try:
        _run_scenario_a(app_path)
        _run_scenario_b(app_path)
    except AssertionError as e:
        print(f"FEHLGESCHLAGEN: {e}")
        return 1
    finally:
        os.environ.pop("AIVERSUS_DATA_DIR", None)
        os.environ.pop("AIVERSUS_BASE_URL", None)

    print("ERFOLG: beide Szenarien laufen ohne AttributeError, last_successful_embed_model "
          "wird in jedem Fall per setdefault() zuverlässig angelegt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
