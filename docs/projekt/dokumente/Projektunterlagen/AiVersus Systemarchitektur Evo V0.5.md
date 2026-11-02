# AiVersus Systemarchitektur Evo V0.5

Stand: 02.11.2026 · abgeglichen mit dem tatsächlichen Code (`app.py`, `models.py`,
`chat_client.py`, `rag.py`, `storage.py`, `i18n.py` + `i18n/*.json`). Bei
Abweichungen gilt der Code.

## 1. Überblick

AiVersus ist eine lokale Streamlit-App ohne eigenen Server und ohne Login. Sie
spricht **ausschließlich NVIDIA Build** (ein OpenAI-kompatibler Endpunkt) - für
Chat-Modelle, die Verfügbarkeitsprüfung und RAG-Embeddings gleichermaßen, über einen
einzigen Key. Alle persistenten Daten liegen lokal unter `data/` (zwei Datei-Stores:
SQLite und ChromaDB, plus drei JSON-Dateien).

## 2. Aufbau

```
Browser  ←→  Streamlit (app.py)
                │
                ├── NVIDIA Build (https://integrate.api.nvidia.com/v1, OpenAI-SDK)
                │     ├── Live-Chat-Katalog        (models.list(), models.py)
                │     ├── Streaming-Chat-Aufrufe   (bis zu 5 parallel, chat_client.py)
                │     ├── Verfügbarkeitsprüfung    (Mini-Call je Katalog-Modell, bis zu 5 parallel)
                │     └── Embeddings für RAG       (Live-Katalog, kein fester Modellname)
                ├── data/runs.db          SQLite   (jede Ergebniszeile → Timeline)
                ├── data/rag_store/       ChromaDB (Dokument-Chunks mit Embeddings)
                ├── data/availability.json         (letzte Verfügbarkeitsprüfung)
                ├── data/pricing.json              (kuratierte Preisliste, Quelle+Datum)
                └── data/settings.json             (Prompt-Suite, Modellauswahl, Preise)
```

`data/` ist per `.gitignore` komplett ausgeschlossen - nichts davon landet im Repo.
Die Basis-URL und das Datenverzeichnis sind über Umgebungsvariablen überschreibbar
(siehe Abschnitt 7) - ausschließlich zu dem Zweck, Tests von den echten Projektdaten
zu isolieren.

## 3. Datenfluss A — Vergleich (Benchmark)

```
API-Key eingeben → Live-Katalog laden (models.list(), 1h gecacht)
        ↓
Modelle hinzufügen (feste Farbe, Preis aus pricing.json oder 0/unbekannt)
Prompts pflegen (Text + Technik-Etikett) + gemeinsame Parameter setzen
(temperature, top_p, max_tokens, optional System-Prompt, optional Seed)
        ↓  "Start Benchmark"
Pro Prompt (nicht pro Modell) ggf. RAG-Retrieval (siehe Datenfluss B)
        ↓
ThreadPoolExecutor, bis zu min(5, Anzahl Aufgaben) parallel:
   Streaming-Aufruf an NVIDIA Build (zwei Zeitüberschreitungen: bis zum ersten
   Token inkl. Warteschlange, zwischen zwei Tokens danach)
   Lehnt das Modell einen Parameter mit HTTP 400 ab → einmal ohne ihn wiederholt
   (sent_params.dropped_param zeigt das an)
        ↓  pro fertigem Call (laufend, nicht erst am Ende)
Ergebniszeile: run_id, timestamp, model_id, prompt_id, prompt_text, technique, ok,
   response, reasoning, tokens_in/out, reasoning_tokens, finish_reason,
   ttft_s, generation_s, tokens_per_s, latency_s, cost_usd, sent_params (JSON),
   injected_context, retrieved_sources, stars, is_best
        ↓
   sofort in runs.db gespeichert (ein Abbruch mitten im Lauf verliert nichts
   bereits Fertiges)   → als JSON/CSV exportierbar
        ↓
Beste Antwort + Sterne vergeben → sofort in runs.db aktualisiert
        ↓
Timeline liest runs.db über alle Läufe → ein Punkt pro (run_id, model_id, prompt_id)
```

**Abbruch (Stop-Button):** setzt ein `threading.Event`, schließt offene Streams aktiv
(`stream.close()`), noch nicht gestartete Futures werden über
`executor.shutdown(cancel_futures=True)` verworfen. Bereits fertige Ergebniszeilen
sind zu diesem Zeitpunkt schon gespeichert und bleiben erhalten; abgebrochene Calls
bekommen den Status "abgebrochen".

**Live-Fortschritt** läuft über `st.fragment(run_every=0.4)` (Benchmark) bzw.
`run_every=0.5` (Verfügbarkeitsprüfung) - die Fragmente pollen nur sich selbst, nicht
die ganze Seite, und lösen bei Abschluss genau einen vollen `st.rerun(scope="app")`
aus.

## 4. Datenfluss B — RAG (optional, ⚠️ nie live getestet)

```
Dokument hochladen (PDF/TXT/MD) → Text extrahieren (pypdf für PDF, UTF-8 sonst)
        ↓
Chunking: Sliding-Window, 1000 Zeichen, 150 Zeichen Überlappung
        ↓
Embedding über ein live aus dem Katalog gewähltes NVIDIA-Build-Modell
(fetch_embedding_models() - kein fest eingetragener Modellname)
        ↓
ChromaDB (data/rag_store/, Collection "documents", Upsert mit sha256-IDs)
        ↓
Bei aktivem RAG, einmal pro Prompt (nicht pro Modell): Top-K ähnlichste Chunks
abrufen (Default 4, einstellbar 1-10)
        ↓
Kontext wird vor die Frage gesetzt ("beantworte ausschließlich auf Basis des
Kontexts, sonst sag das ausdrücklich") → normaler Modellaufruf (Datenfluss A)
        ↓
Ergebniszeile: injected_context = true, retrieved_sources = ["Datei#Chunk-Index", …]
```

Die einzelnen Bausteine (Chunking, Embedding-Aufruf, ChromaDB-Zugriff,
Katalog-Filter für Embedding-Modelle) sind mit gemockten Clients getestet. **Die
volle Kette mit einem echten `st.file_uploader`-Upload und einem echten NVIDIA-
Build-Key wurde bisher kein einziges Mal live durchgespielt** (siehe PROTOKOLL.md,
"LIVE-TEST OFFEN" sowie Backlog).

## 5. Dateien

| Datei | Aufgabe |
| --- | --- |
| `app.py` | UI (Sidebar + Hauptbereich), Benchmark-/Verfügbarkeits-Schleifen, Ergebniskarten, Timeline, Persistenz-Glue |
| `models.py` | Live-Modellkatalog: Chat-/Embedding-Modelle filtern, Top-10-Familien-Erkennung, Dropdown-Reihenfolge, Kandidaten für den Verbindungstest |
| `chat_client.py` | `call_chat_streaming()`: Streaming-Aufruf in eigenem Thread, zwei Zeitüberschreitungen, Abbruch, 400-Retry ohne abgelehnten Parameter |
| `rag.py` | Textextraktion, Chunking, Embedding, ChromaDB (`RagIndex`), Prompt-Bau mit Kontext |
| `storage.py` | `RunStore`: Ergebniszeilen in SQLite speichern/laden, Migrationen, Sterne/Beste-Antwort, Timeline-Abfragen |
| `i18n.py` + `i18n/en.json` + `i18n/de.json` | Übersetzungsfunktion `t(key, **kwargs)`, Englisch als Fallback; beide Sprachdateien aktuell mit je 149 Schlüsseln vollständig synchron |

`pricing.py` (feste Preistabelle) wurde entfernt - Preise kommen ausschließlich noch
über den Pricing-Dialog/`pricing.json` (siehe Abschnitt 8).

## 6. Speicherformate

**SQLite (`data/runs.db`), Tabelle `results`** - Primärschlüssel
`(run_id, model_id, prompt_id)`, ein erneuter Lauf mit gleichen Schlüsseln
überschreibt (`INSERT OR REPLACE`):

`run_id, timestamp, model_id, prompt_id, technique, ok, response, tokens_in,
tokens_out, latency_s, cost_usd, injected_context, retrieved_sources, ttft_s,
generation_s, tokens_per_s, reasoning_tokens, sent_params, stars, is_best,
prompt_text, finish_reason`

- `sent_params`: JSON-String mit `temperature`, `top_p`, `max_tokens`, `seed`,
  `system_prompt`, `dropped_param` - was für diese Zeile tatsächlich gesendet wurde
  (kann nach einem 400-Retry von der Vorgabe abweichen).
- `prompt_text` und `finish_reason` wurden nachträglich per `ALTER TABLE` ergänzt
  (siehe `MIGRATIONS` in `storage.py`) - bei Zeilen aus der Zeit davor sind sie
  `NULL`.
- `retrieved_sources`: JSON-Liste von `"Dateiname#Chunk-Index"`.

**ChromaDB (`data/rag_store/`):** Collection `documents`, je Chunk die Metadaten
`source` und `chunk_index`, IDs als sha256 über Dateiname+Index+Textanfang.

**`data/availability.json`:** `{"checked_at": <ISO-Zeitstempel oder null>, "models":
{model_id: {"status": "available"|"unavailable"|"slow", "detail": <Fehlertext oder
null>}}}`.

**`data/pricing.json`:** `{"models": {model_id: {"input": <$/1M Tokens oder null>,
"output": <… oder null>, "source": <Text oder null>, "updated": <Text oder null>,
"free": <bool>}}}` - nur Preise, die der Nutzer selbst mit Quelle und Datum
eingetragen hat (aktuell leer, siehe Backlog).

**`data/settings.json`:** `{"prompts": […], "selected_models": […],
"model_prices": {…}}` - bewusst keine API-Keys und keine Ergebnisse; Keys bleiben
ausschließlich im Session-State, Ergebnisse liegen in `runs.db`.

## 7. `data/` und Umgebungsvariablen

| Variable | Standard | Zweck |
| --- | --- | --- |
| `AIVERSUS_DATA_DIR` | `<Projektordner>/data` | Überschreibt, wo `runs.db`, `availability.json`, `pricing.json`, `settings.json` und `rag_store/` liegen |
| `AIVERSUS_BASE_URL` | `https://integrate.api.nvidia.com/v1` | Überschreibt die NVIDIA-Build-Basis-URL |

Beide Variablen existieren ausschließlich zur Testisolation: jeder Test/Mock-Lauf
setzt beide auf ein Temp-Verzeichnis bzw. einen lokalen Mock-Server, bevor `app.py`
überhaupt importiert wird - nie mit dem Projektordner als Arbeitsverzeichnis (feste
Regel, siehe projekteigene `CLAUDE.md` und `scripts/verify_data_isolation.py` als
Beweis-Skript).

## 8. Pricing-Dialog

Ein `st.dialog` mit editierbarer Tabelle (`st.data_editor`, dynamische Zeilenzahl):
Modell-ID, Input-/Output-Preis pro 1M Tokens, Quelle, Aktualisierungsdatum,
Free-Tier-Haken. Speichern schreibt nach `pricing.json` und überschreibt sofort auch
die Preisfelder bereits ausgewählter Modelle (die zugehörigen `number_input`-Widgets
ignorieren ab ihrer ersten Erstellung jedes neue `value=`, deshalb der direkte
Session-State-Eingriff). Kosten pro Ergebniszeile: `free` gesetzt → 0.0; kein
Preiseintrag (`input == output == 0.0` ohne `free`) → `None` (unbekannt, nicht 0);
sonst `tokens × Preis / 1 000 000`.

## 9. Sterne & Beste Antwort

Pro (Lauf, Prompt): ein Radio-Button markiert die beste Antwort unter den Modellen
dieses Prompts (`store.set_best_answer`), pro (Lauf, Modell, Prompt) `st.feedback
("stars")` für 1-5 Sterne (`store.set_stars`) - beides sofort in `runs.db`
geschrieben, nicht erst beim nächsten Lauf. `wins_per_model()` zählt `is_best = 1`
über alle Läufe für das "Siege pro Modell"-Balkendiagramm.

## 10. Timeline

Jede Zeile `(run_id, model_id, prompt_id)` ist bereits ein Punkt (Primärschlüssel in
`runs.db`) - keine Aggregation nötig. Eine Linie verbindet nur Punkte mit gleichem
`prompt_text` **und** gleichen `temperature`/`top_p`/`max_tokens` (aus `sent_params`
geparst); weicht ein Lauf desselben Modells ab, bekommt er eine eigene Serie
(Altair-`detail`-Encoding, Farbe bleibt modellbezogen) plus einen Hinweis-Caption.
X-Achse: maximal ~6 Ticks, Format `%d.%m. %H:%M`. Standard-Metrik: `tokens_per_s`
(wählbar: auch `generation_s`, `ttft_s`, `latency_s`, Tokens in/out, Kosten).
Fehlgeschlagene Zeilen (`ok = 0`) fließen nicht in die Timeline ein.

## 11. Englisch/Deutsch

`i18n.py` lädt `i18n/<lang>.json` und baut daraus `t(key, **kwargs)`; Englisch ist
Standard und zugleich Fallback, falls ein Schlüssel in der gewählten Sprache (oder
in Englisch selbst) fehlt - dann erscheint der Schlüssel selbst statt eines Absturzes.
Umschaltbar per Radio-Button in der Sidebar (`st.session_state.lang`). Beide
Sprachdateien enthalten aktuell je 149 Schlüssel, vollständig deckungsgleich (kein
Schlüssel existiert nur in einer Sprache).

## 12. Grenzen

- Single-User, lokal: Mehrere Personen auf demselben Datenbestand bräuchten einen
  echten Server.
- Kosten sind nur so gut wie die selbst eingetragenen Preise - für NVIDIA Build
  wurde keine offizielle, auffindbare Preistabelle gefunden (siehe PROTOKOLL.md);
  unbekannt bleibt unbekannt, nie stillschweigend "kostenlos".
- Die Timeline setzt stabile Modell-IDs voraus; bei einer Umbenennung durch den
  Anbieter reißt die Zeitreihe ab.
- Der Verbindungstest probiert bis zu 5 Kandidaten nacheinander mit dem vollen,
  in der Sidebar eingestellten Zeitlimit (Standard 300s bis zum ersten Token) -
  kann sich dadurch stark summieren (siehe Backlog).
- RAG ist implementiert, aber nie mit einem echten Datei-Upload und einem echten
  Key live durchgespielt worden (siehe Abschnitt 4).
- Reasoning-Tokens kommen, falls vorhanden, aus
  `usage.completion_tokens_details.reasoning_tokens` - nicht gegen jedes
  Reasoning-Modell im Katalog verifiziert.

## 13. Tech-Stack

Python · Streamlit (inkl. Altair für die Timeline-Diagramme, kommt als
Streamlit-Abhängigkeit mit, kein eigener Projekteintrag) · openai-SDK · Pandas ·
ChromaDB · pypdf · sqlite3 (Standardbibliothek). Dev: pyflakes.

---

© 2026 Airdinsh (Erdinç Arslan) · Masterschool AI Engineering Track · MIT-Lizenz (siehe LICENSE im Repo)  
📧 Signlab@gmx.de · 🌐 Airdinsh.com
