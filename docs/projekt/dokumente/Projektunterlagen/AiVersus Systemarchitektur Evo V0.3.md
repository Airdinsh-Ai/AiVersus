# AiVersus Systemarchitektur Evo V0.3

Stand: 18.10.2026 · zusammengefasst aus Konzept, Backlog und dem tatsächlichen Code (`app.py`, `rag.py`, `storage.py`, `pricing.py`). Bei Abweichungen gilt der Code.

## 1. Überblick

AiVersus ist eine lokale Streamlit-App. Sie ruft OpenAI- und Google-Gemini-Modelle auf, vergleicht die Ergebnisse, reichert Prompts optional mit Dokument-Kontext (RAG) an und speichert jeden Lauf für die Timeline. Es gibt keinen eigenen Server und keinen Login: Alles läuft in einem lokalen Prozess, die Daten liegen in zwei lokalen Datei-Stores.

## 2. Aufbau

```
Browser  ←→  Streamlit (app.py)
                │
                ├── OpenAI-API ── gpt-4o-mini, gpt-4.1-mini, gpt-5-mini
                │                 + Embeddings für RAG (text-embedding-3-small)
                ├── Google-Gemini-API (OpenAI-kompatibler Endpunkt)
                │                 ── gemini-2.5-flash, gemini-2.5-pro
                ├── SQLite    runs.db      (alle Ergebniszeilen → Timeline)
                └── ChromaDB  rag_store/   (Dokument-Chunks mit Embeddings)
```

Beide Provider werden über dasselbe `openai`-Python-SDK angesprochen, nur Basis-URL und Key unterscheiden sich.

## 3. Datenfluss A — Vergleich

```
Modelle wählen + Prompts (mit Prompt Technique) pflegen
        ↓  "Benchmark starten"
Für jede Modell×Prompt-Kombination:
   Aufruf beim jeweiligen Provider → Antwort, Tokens (in/out), Latenz
   Kosten = Tokens × Preis aus pricing.py
        ↓
Ergebniszeile: run_id, timestamp, model_id ("provider:modell"), prompt_id,
               technique, ok, response, tokens_in, tokens_out, latency_s,
               cost_usd, injected_context, retrieved_sources
        ↓
   → in runs.db gespeichert   → als JSON/CSV exportierbar
        ↓
Timeline liest runs.db über alle Läufe → Liniendiagramm je Modell
```

## 4. Datenfluss B — RAG (optional)

```
Dokument hochladen (PDF/TXT/MD) → Text extrahieren
        ↓
Chunking (1000 Zeichen, 150 Überlappung) → Embedding (OpenAI) → ChromaDB
        ↓
Bei aktivem RAG, pro Prompt: Top-K ähnlichste Chunks abrufen
        ↓
Kontext wird vor die Frage gesetzt → normaler Modellaufruf (Datenfluss A)
        ↓
Ergebniszeile: injected_context = true, retrieved_sources = [Datei#Chunk, …]
```

## 5. Dateien

| Datei | Aufgabe |
| --- | --- |
| `app.py` | UI, Provider-Routing, Benchmark-Schleife, Ergebnisse, Timeline |
| `rag.py` | Extraktion, Chunking, Embedding, ChromaDB, Retrieval, Prompt-Bau |
| `storage.py` | `RunStore`: Ergebniszeilen in SQLite speichern und laden |
| `pricing.py` | Preistabelle (USD pro 1M Tokens) und `estimate_cost_usd()` |

## 6. Speicherformate

**SQLite (`runs.db`), Tabelle `results`:** `run_id, timestamp, model_id, prompt_id, technique, ok, response, tokens_in, tokens_out, latency_s, cost_usd, injected_context, retrieved_sources` — Primärschlüssel `(run_id, model_id, prompt_id)`, ein erneuter Lauf mit gleichen Schlüsseln überschreibt.

**ChromaDB (`rag_store/`):** Collection `documents`, je Chunk die Metadaten `source` und `chunk_index`.

## 7. Grenzen

- Single-User, lokal: Mehrere Personen auf demselben Datenbestand bräuchten einen echten Server.
- Kosten sind Schätzwerte aus Richtpreisen; Modelle ohne Preiseintrag erscheinen mit 0.
- Die Timeline setzt stabile Modell-IDs voraus; bei einer Umbenennung durch den Anbieter reißt die Zeitreihe ab.
- Token-Zahlen kommen von den Providern; bei Reasoning-Modellen ist zu prüfen, ob Denk-Tokens enthalten sind (Backlog).

## 8. Tech-Stack

Python · Streamlit · openai-SDK · Pandas · ChromaDB · pypdf · sqlite3 (Standardbibliothek)

---

© 2026 Airdinsh (Erdinç Arslan) · Masterschool AI Engineering Track · MIT-Lizenz (siehe LICENSE im Repo)  
📧 Signlab@gmx.de · 🌐 Airdinsh.com
