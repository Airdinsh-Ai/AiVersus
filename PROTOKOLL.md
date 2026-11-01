# AiVersus – Protokoll

## Nachtschicht 01./02.11. – Entscheidungen & offene Fragen

Autonomer Nachtlauf laut Auftrag vom 01.11. (Nutzer bis 02.11. nicht erreichbar).
Arbeitsregeln: pro Schritt Syntax-Check + Smoke-Test + eigener Commit; bei
Unklarheiten konservative Lösung wählen und hier dokumentieren statt zu fragen;
kein `uv --active`, keine Änderungen außerhalb AiVersus, kein Push bis zum Schluss,
nur gemockte Clients (kein API-Key vorhanden).

Dieser Abschnitt wird während der Nacht laufend ergänzt (neueste Einträge oben
innerhalb des Abschnitts).

### LIVE-TEST OFFEN (Checkliste für morgen)
- [ ] Schritt 6 (Design): Theme/CSS nur auf Fehlerfreiheit geprüft (App startet,
  kein Streamlit-Theme-Fehler im Log), nicht visuell im Browser verglichen mit
  der Design-Vorlage (Farben/Schriftarten/Abstände) - das geht nur per Augenschein.
- [ ] Schritt 5 (RAG): volle Kette Datei-Upload (echter st.file_uploader) →
  Index aufbauen → Benchmark mit injected_context=True → Chunks auf der Karte.
  Nur die Bausteine einzeln getestet (RagIndex add_document/retrieve mit
  gemocktem Client, Embedding-Modell-Filter, Lazy-Import), nicht der
  Datei-Upload-Widget-Pfad selbst (in AppTest nicht praktikabel simulierbar).

- Beim Testen der RAG-Reaktivierung (Schritt 5) ist versehentlich ein echter
  `rag_store/`-Ordner (chromadb-Datei) im Projekt-Root entstanden, obwohl der
  Test in einem Temp-Verzeichnis laufen sollte (Ursache nicht abschließend
  geklärt - vermutlich hat `get_index()`/`RagIndex` den relativen Default-Pfad
  "rag_store" zu einem Zeitpunkt aufgelöst, an dem das CWD doch wieder das
  Projektverzeichnis war). War ohnehin gitignored, keine echten Daten betroffen;
  einzelne Datei + leeren Ordner gezielt entfernt (kein rm -rf, das hat der
  Auto-Mode-Classifier als "irreversible lokale Zerstörung" abgelehnt).
  Für weitere Tests heute Nacht: RagIndex-Instanzen mit explizitem, absolutem
  Temp-Pfad für persist_dir erzeugen statt auf chdir+relativen Pfad zu vertrauen.
- Recherche für Schritt 3 (Pricing-Vorbefüllung): WebSearch nach
  "NVIDIA Build pricing per million tokens" und WebFetch auf
  build.nvidia.com/pricing (404) zeigen: NVIDIA Build hat keine eigene,
  auffindbare, offizielle Preistabelle pro Modell - nur Drittanbieter-
  Aggregatoren (anotherwrapper.com, pricepertoken.com) mit nicht
  gegen NVIDIA verifizierten Zahlen. Konservative Entscheidung: KEINE
  Vorbefüllung in pricing.json (leer lassen), da "offizielle
  Anbieter-Seite" nicht erfüllbar ist. Preisfelder bleiben "–", bis
  der Nutzer selbst Preise + Quelle einträgt.
- `pricing.json` (Schritt 3) bewusst NICHT gitignored, anders als `availability.json`:
  availability.json ist flüchtige, account-/zeitabhängige Messung (gehört nicht ins
  Repo), pricing.json dagegen kuratierte, quellenbelegte Referenzdaten, die mit dem
  Projekt mitgeliefert werden sollen (ähnlich wie pricing.py bisher). Entscheidung,
  da die Auftragsliste für pricing.json kein "(gitignored)" nannte, für
  availability.json aber explizit.
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
