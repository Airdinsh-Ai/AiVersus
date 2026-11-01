# AiVersus Backlog Evo V0.3

Stand: 18.10.2026

## Kritisch (Abgabe)

| Item | Status | Notiz |
| --- | --- | --- |
| App live mit echten Keys testen | To do | Bisher nur mit Attrappen getestet (Logik, Speicherung, RAG-Ablauf). Nicht live geprüft: Antworten der Provider, Gemini-Endpunkt, ChromaDB-Aufrufe, Streamlit-Oberfläche |
| Läufe mit den 5 Modellen fahren, Comparison Table in Notion ausfüllen, Conclusion schreiben | To do | Werte kommen aus der App (Export CSV/JSON) |
| Preise in `pricing.py` prüfen | To do | Richtwerte; Links stehen im Dateikopf |
| Projekt-Präsentation (Slides) | To do | |
| Demo-Video | To do | |
| GitHub-Repo pushen | To do | `.gitignore` ergänzen: `runs.db`, `rag_store/`, `__pycache__/`, `.venv/` |

## Weiteres

| Item | Notiz |
| --- | --- |
| Reasoning-Modelle prüfen | Enthalten die Token-Zahlen von gpt-5-mini und gemini-2.5-pro die Denk-Tokens? Beeinflusst Tokens und Kosten in der Tabelle |
| Qualitätsbewertung der Antworten | bisher nur Latenz, Tokens, Kosten |
| Cost Calculator | Kosten vorab schätzen (siehe UI-Optionen im Konzept) |
| UI-Design | macht Airdinsh separat (Figma) |
| Login, Agenten, Chat-Verlauf | nur falls ein Server gewünscht ist (siehe UI-Optionen im Konzept) |

## Erledigt

Modellvergleich mit Prompt Technique, Tokens, Latenz, Kosten · RAG (Upload, Chunking, Embedding, ChromaDB, Retrieval, `injected_context`) · Speicherung in SQLite · Timeline · JSON/CSV-Export · Konzept, Systemarchitektur, Backlog

## Konventionen

- Das Projekt heißt **AiVersus**. „Evo V0.x“ (Evolution Version) ist nur die Versionsbezeichnung der Dokumente: „AiVersus [Typ] Evo V0.x“.
- Der Code im Repo ist die Wahrheit; Dokumente beschreiben ihn und werden bei Änderungen nachgezogen.
- API-Keys werden nur zur Laufzeit in der Sidebar eingegeben und nirgends gespeichert.

## Entscheidungshistorie (verworfen oder ersetzt — nur hier dokumentiert)

| Datum | Entscheidung | Grund |
| --- | --- | --- |
| 18.10.2026 | `apprealism` (natives App-Fenster via pywebview, 3 Themes) entfernt | Nutzung läuft über den Browser (`streamlit run app.py`); das Design kommt separat |
| 18.10.2026 | NVIDIA Build als Provider entfernt (Modellkatalog, eigene Modell-IDs, Embeddings) | War nur Zwischenlösung (in BEG genutzt, zurückgestellt, als die OpenAI-API wieder funktionierte). Die Pflichtmodelle der Comparison Table sind OpenAI und Google; RAG-Embeddings laufen jetzt über OpenAI. Spätere Wiederanbindung ist einfach (OpenAI-kompatibel: Basis-URL + Key) |
| 18.10.2026 | Eigenes CLI-Script entfernt | Die App deckt alles ab |
| 18.10.2026 | Dokumente Übersicht, Manifest, Lizenzübersicht und eigene Lizenz-Datei entfernt | Redundant; `LICENSE` liegt im Repo; ein Manifest, das seinen eigenen Hash enthält, kann nicht stimmen |
| 18.10.2026 | Interview-/Feldeinsatz-App | Eigenes Vorhaben, nicht Teil von AiVersus |
| 22.09.2026 | Kein eigener Server, kein Multi-User-Login | Lokale Single-User-App genügt (weiterhin gültig) |

---

© 2026 Airdinsh (Erdinç Arslan) · Masterschool AI Engineering Track · MIT-Lizenz (siehe LICENSE im Repo)  
📧 Signlab@gmx.de · 🌐 Airdinsh.com
