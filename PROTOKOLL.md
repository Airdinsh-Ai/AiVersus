# AiVersus – Protokoll

## Nachtschicht 01./02.11. – Entscheidungen & offene Fragen

Autonomer Nachtlauf laut Auftrag vom 01.11. (Nutzer bis 02.11. nicht erreichbar).
Arbeitsregeln: pro Schritt Syntax-Check + Smoke-Test + eigener Commit; bei
Unklarheiten konservative Lösung wählen und hier dokumentieren statt zu fragen;
kein `uv --active`, keine Änderungen außerhalb AiVersus, kein Push bis zum Schluss,
nur gemockte Clients (kein API-Key vorhanden).

Dieser Abschnitt wird während der Nacht laufend ergänzt (neueste Einträge oben
innerhalb des Abschnitts).

- Beim Testen von storage.py-Methoden ist versehentlich eine Testzeile
  (run_id "testrun") in die echte, lokale `runs.db` gelangt (die Datei existiert
  schon aus den Live-Tests des Nutzers, ist aber gitignored). Zeile sofort wieder
  gezielt gelöscht (`DELETE ... WHERE run_id='testrun'`), echte Daten unberührt.
  Ab jetzt für alle weiteren isolierten storage.py-Tests eine `tempfile`-DB
  verwenden, nie die Projekt-`runs.db`.

## 2026-10-18

### Was gemacht
- `Privat/AiVersus` als eigenständiges uv-Projekt angelegt (`uv init --no-workspace`,
  eigene `.venv`, eigene `pyproject.toml`) – bewusst nicht als Workspace-Member im
  Root-`pyproject.toml` eingetragen, damit die gemeinsame venv unangetastet bleibt.
- Pakete per `uv add streamlit openai pandas chromadb pypdf` installiert.
- `git init`, `.gitignore` (`runs.db`, `rag_store/`, `__pycache__/`, `.venv/`, `.env`).
- Aus `AiVersus Dokumente.zip` (Downloads): `app.py`, `rag.py`, `storage.py`,
  `pricing.py`, `README.md` in den Projekt-Root kopiert; die drei Konzept-/
  Systemarchitektur-/Backlog-Dokumente (Evo V0.3) nach
  `docs/projekt/dokumente/Projektunterlagen/`. `requirements.txt` bewusst nicht
  übernommen (ersetzt durch `pyproject.toml`).
- Von `uv init` erzeugte Boilerplate `main.py` entfernt (kein echter Einstiegspunkt,
  `app.py` startet die App).
- README-Startbefehl auf `uv run streamlit run app.py` geändert, sonst nichts.
- `uv run python -m py_compile app.py rag.py storage.py pricing.py` → OK.

### Was entschieden
- Eigenständiges uv-Projekt statt Workspace-Member, auf ausdrücklichen Wunsch.
- Keine stigmem-Struktur (kommt laut Nutzer später).
- App nicht gestartet – API-Keys gibt der Nutzer selbst ein.

### Was gemacht (Fortsetzung, 2026-11-01)
- Initial-Commit erstellt (lokale noreply-E-Mail gesetzt, siehe
  Workspace-Memory "Git noreply-Identität") und auf das bereits bestehende,
  öffentliche GitHub-Repo `github.com/Airdinsh-Ai/AiVersus` gepusht
  (Repo war schon angelegt, aber leer; Remote `origin` neu gesetzt).

### Offen
- Dokumente im Zip sind mit "Evo V0.3" betitelt, in der ursprünglichen Anfrage war von
  "Evo V0.4" die Rede – bisher nicht geklärt, ob das ein Tippfehler war oder eine neuere
  Version noch nachgereicht wird.
- Live-Test mit echten API-Keys steht laut Backlog-Dokument noch aus (bisher nur mit
  Attrappen getestet).
