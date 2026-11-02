# AiVersus Systemarchitektur Evo V0.6

Stand: 02.11.2026 · abgeglichen mit dem tatsächlichen Code (`app.py`, `models.py`,
`chat_client.py`, `rag.py`, `storage.py`, `i18n.py` + `i18n/*.json`). Bei
Abweichungen gilt der Code.

## 1. Überblick

AiVersus ist eine lokale Streamlit-App ohne eigenen Server und ohne Login. Sie
spricht **ausschließlich NVIDIA Build** (ein OpenAI-kompatibler Endpunkt) - für
Chat-Modelle, die Verfügbarkeitsprüfung und RAG-Embeddings gleichermaßen, über einen
einzigen Key. Alle persistenten Daten liegen lokal unter `data/` (zwei Datei-Stores:
SQLite und ChromaDB, plus fünf JSON-Dateien).

## 2. Aufbau

```
Browser  ←→  Streamlit (app.py)
                │
                ├── NVIDIA Build (https://integrate.api.nvidia.com/v1, OpenAI-SDK)
                │     ├── Live-Chat-Katalog        (models.list(), models.py)
                │     ├── Streaming-Chat-Aufrufe   (bis zu 5 parallel, chat_client.py)
                │     ├── Verfügbarkeitsprüfung    (Mini-Call je Katalog-Modell, bis zu 5 parallel)
                │     └── Embeddings für RAG       (Live-Katalog, kein fester Modellname)
                ├── data/runs.db                      SQLite   (jede Ergebniszeile → Timeline)
                ├── data/rag_store/                    ChromaDB (Dokument-Chunks mit Embeddings)
                ├── data/availability.json             (letzte Chat-Verfügbarkeitsprüfung)
                ├── data/embedding_availability.json   (letzte Embedding-Verfügbarkeitsprüfung)
                ├── data/pricing.json                  (kuratierte Preisliste, Quelle+Datum)
                └── data/settings.json                 (Prompt-Suite, Modellauswahl, Preise)
```

`data/` ist per `.gitignore` komplett ausgeschlossen - nichts davon landet im Repo.
Die Basis-URL und das Datenverzeichnis sind über Umgebungsvariablen überschreibbar
(siehe Abschnitt 8) - ausschließlich zu dem Zweck, Tests von den echten Projektdaten
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
   bereits Fertiges)   → als JSON/CSV exportierbar, Karte in der UI (Abschnitt 4)
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
`run_every=0.5` (Chat- und Embedding-Verfügbarkeitsprüfung) - die Fragmente pollen
nur sich selbst, nicht die ganze Seite, und lösen bei Abschluss genau einen vollen
`st.rerun(scope="app")` aus.

## 4. Ergebniskarten

Jede Ergebniszeile (Benchmark-Lauf oder Verbindungstest) wird über dieselbe
`_render_card()` gerendert - immer sichtbar, danach mehrere unabhängige, nicht
verschachtelte `st.expander`/`st.toggle`-Blöcke:

- **Kopf:** Modellname mit fester Farbe (`model_color()`, deterministisch über den
  Modellnamen, nicht über die Listenposition), Status-Badge (ok/Fehler/Timeout/
  abgebrochen), ggf. "Abgeschnitten"- und "Beste Antwort"-Badge, 1-5 Sterne.
- **Verbrauchszeile:** TTFT, Generierungszeit, Tokens in/out, Tokens/s, Kosten.
  Tokens/s zeigt "–" statt einer Zahl, wenn `generation_s < 0.05s` ist (so kurze
  Dauern sind Messrauschen, keine belastbare Rate) - zentral in `_tokens_per_s()`.
- **Antwort:** hinter einem `st.toggle` (kein `st.expander`, siehe Code-Kommentar in
  `_render_card()` - ein programmatisch gesetzter `expanded`-Wert nach der ersten
  Erstellung wird von `st.expander` zuverlässig ignoriert, von `st.toggle` nicht),
  Markdown statt HTML-Escaping (sonst rendern Code-Blöcke/Überschriften kaputt).
- **Reasoning:** falls vorhanden, eigener `st.expander`, getrennt von der Antwort.
- **RAG-Kontext:** falls injiziert, ein `st.expander` mit Quelle+Chunk-Index je
  Treffer; der Chunk-Text selbst steht dahinter nochmal pro Chunk hinter einem
  `st.toggle` (kein zweiter Expander - Streamlit lässt Expander nicht verschachteln),
  standardmäßig eingeklappt.
- **Parameter:** eigener `st.expander` mit den tatsächlich gesendeten Werten
  (inkl. `dropped_param`-Hinweis nach einem 400-Retry) und dem Prompt-Text.

**Ergebniskopf pro Prompt** (oberhalb der Kartenreihe): nur die Prompt-ID ist fett
(`**p1**`) - der Prompt-Text steht als eigene Zeile darunter, bei langen/mehrzeiligen
Prompts (>100 Zeichen oder mit Zeilenumbruch) eingeklappt hinter einem `st.expander`.
Vorher stand der komplette Prompt-Text innerhalb von `**...**`, was bei mehrzeiligen
Prompts das Markdown zerriss.

## 5. Datenfluss B — RAG (optional, live getestet am 02.11.2026)

```
Embedding-Modelle vor der Auswahl per Mini-Call prüfen (analog zur Chat-
Verfügbarkeitsprüfung, Ergebnis in data/embedding_availability.json gecacht):
  - 404/410 → "unavailable" (für den Account nicht freigeschaltet)
  - 400 → "incompatible" (erreichbar, lehnt aber das Anfrageformat ab - z.B. ein
    Bild-/Video-Embedding-Modell, Namensteil "-vl-")
  - alles andere → "slow" (Timeout/unbekannt)
beide "unavailable" und "incompatible" werden ausgeblendet; Standardauswahl =
zuletzt erfolgreiches Modell, sonst das erste bestätigt "available" Modell, nie
eines mit "slow/unbekannt" und nie ein Modell mit "-vl-" im Namen (siehe
_pick_default_embed_model() - ersetzt das alte, blinde "erstes Katalog-Modell")
        ↓
Dokument hochladen (PDF/TXT/MD) → Text extrahieren (pypdf für PDF, UTF-8 sonst)
        ↓
Chunking: Sliding-Window, 1000 Zeichen, 150 Zeichen Überlappung
        ↓
Embedding über das gewählte NVIDIA-Build-Modell (fetch_embedding_models() -
kein fest eingetragener Modellname); 404 beim Indexieren selbst zeigt "anderes
Embedding-Modell wählen", 400 zeigt denselben Hinweis mit expliziterem Text
("Modell nimmt die Anfrage nicht an") - beide tragen das Modell sofort in den
Verfügbarkeits-Cache ein, nicht erst bei der nächsten manuellen Prüfung
        ↓
ChromaDB (data/rag_store/, Collection "documents", Upsert mit sha256-IDs) - die
Collection ist über ihre Metadaten an genau ein Embedding-Modell gebunden; ein
Wechsel bei bereits vorhandenen Chunks wird verweigert (RagIndex löst
EmbedModelMismatch aus, UI bietet "Index leeren und Modell X übernehmen" an),
statt Vektoren unterschiedlicher Modelle (oft unterschiedliche Dimension) in
derselben Collection zu mischen
        ↓
Bei aktivem RAG, einmal pro Prompt (nicht pro Modell): Top-K ähnlichste Chunks
abrufen (Default 4, einstellbar 1-10)
        ↓
Kontext wird vor die Frage gesetzt ("beantworte ausschließlich auf Basis des
Kontexts, sonst sag das ausdrücklich") → normaler Modellaufruf (Datenfluss A)
        ↓
Ergebniszeile: injected_context = true, retrieved_sources = ["Datei#Chunk-Index", …],
retrieved_chunks = [{"source", "chunk_index", "text"}, …] (nur für die Karte in
diesem Lauf, nicht in runs.db persistiert)
        ↓
Ergebniskarte zeigt Quelle+Chunk-Index je Treffer, den Chunk-Text selbst per
Toggle pro Chunk, standardmäßig eingeklappt (siehe Abschnitt 4)
```

Ein Live-Test am 02.11.2026 (echter NVIDIA-Build-Key, echter `st.file_uploader`-
Upload) deckte insgesamt vier Mängel auf, alle behoben: (1) ein im Katalog gelistetes,
aber für den Account nicht freigeschaltetes Embedding-Modell fiel erst beim
Indexieren mit einer generischen Fehlermeldung auf (→ Mini-Call-Prüfung); (2) ein
Wechsel des Embedding-Modells schrieb stillschweigend in dieselbe Collection weiter
(→ `EmbedModelMismatch`); (3) die Ergebniskarte zeigte nur Quelle+Chunk-Index, nicht
den Chunk-Text selbst (→ Toggle in der Karte); (4) die Standardauswahl wählte blind
das erste Katalog-Modell - im konkreten Test `nvidia/llama-nemotron-embed-vl-1b-v2`,
ein Bild-/Video-Embedding-Modell, das mit HTTP 400 scheiterte, während
`nvidia/nemotron-3-embed-1b` funktionierte (→ `_pick_default_embed_model()` plus
400-Klassifikation "incompatible", siehe oben). Siehe Abschnitt 13 (Teststand) dazu,
wie die einzelnen Fixes verifiziert wurden.

## 6. Dateien

| Datei | Aufgabe |
| --- | --- |
| `app.py` | UI (Sidebar + Hauptbereich), Benchmark-/Verfügbarkeits-Schleifen, Ergebniskarten, Timeline, Persistenz-Glue |
| `models.py` | Live-Modellkatalog: Chat-/Embedding-Modelle filtern, Top-10-Familien-Erkennung, Dropdown-Reihenfolge, Kandidaten für den Verbindungstest |
| `chat_client.py` | `call_chat_streaming()`: Streaming-Aufruf in eigenem Thread, zwei Zeitüberschreitungen, Abbruch, 400-Retry ohne abgelehnten Parameter |
| `rag.py` | Textextraktion, Chunking, Embedding, ChromaDB (`RagIndex`), Prompt-Bau mit Kontext |
| `storage.py` | `RunStore`: Ergebniszeilen in SQLite speichern/laden, Migrationen, Sterne/Beste-Antwort, Timeline-Abfragen (inkl. nach Messwert+Aktualität gerankte Modell-Vorauswahl) |
| `i18n.py` + `i18n/en.json` + `i18n/de.json` | Übersetzungsfunktion `t(key, **kwargs)`, Englisch als Fallback; beide Sprachdateien aktuell mit je 163 Schlüsseln vollständig synchron |
| `.streamlit/config.toml` | Dunkles Theme laut Design-Vorlage (Farben, IBM Plex Sans/Mono, Rundungen, feste Modellfarbpalette für Diagramme) |

`pricing.py` (feste Preistabelle) wurde entfernt - Preise kommen ausschließlich noch
über die beiden Preiswege in Abschnitt 9.

## 7. Speicherformate

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
- `retrieved_sources`: JSON-Liste von `"Dateiname#Chunk-Index"`. Der volle
  Chunk-Text (`retrieved_chunks` in der Ergebniszeile, für die Karte) wird NICHT
  mitgespeichert - nur für den Lauf im Session-State, nicht Teil des Schemas.
- `tokens_per_s`: Zeilen aus der Zeit vor dem 0.05s-Schwellwert (Abschnitt 4) wurden
  per `scripts/migrate_tokens_per_s_null.py` einmalig auf `NULL` korrigiert, wo
  `generation_s < 0.05s` war (4 betroffene Zeilen in der echten `runs.db`).

**ChromaDB (`data/rag_store/`):** Collection `documents`, Collection-Metadaten
`{"embed_model": <Modell-ID>}` (siehe Abschnitt 5 - bindet die Collection an genau
ein Embedding-Modell), je Chunk die Dokument-Metadaten `source` und `chunk_index`,
IDs als sha256 über Dateiname+Index+Textanfang.

**`data/availability.json`:** `{"checked_at": <ISO-Zeitstempel oder null>, "models":
{model_id: {"status": "available"|"unavailable"|"slow", "detail": <Fehlertext oder
null>}}}` - Chat-Modelle.

**`data/embedding_availability.json`:** gleiches Format wie `availability.json`,
eigene Datei für die Embedding-Modelle (siehe Abschnitt 5) - Chat- und
Embedding-Modelle teilen sich keinen Namensraum und werden unabhängig geprüft; der
`status`-Wert kennt hier zusätzlich `"incompatible"` (HTTP 400).

**`data/pricing.json`:** `{"models": {model_id: {"input": <$/1M Tokens oder null>,
"output": <… oder null>, "source": <Text oder null>, "updated": <Text oder null>,
"free": <bool>}}}` - nur Preise, die der Nutzer selbst mit Quelle und Datum
eingetragen hat (aktuell leer, siehe Backlog).

**`data/settings.json`:** `{"prompts": […], "selected_models": […],
"model_prices": {…}, "last_successful_embed_model": <Modell-ID oder null>}` -
bewusst keine API-Keys und keine Ergebnisse; Keys bleiben ausschließlich im
Session-State, Ergebnisse liegen in `runs.db`. Alle Schlüssel werden beim
Session-Start per `st.session_state.setdefault(...)` angelegt (Wert aus
`settings.json`, sonst `None`/leer) - eine bestehende Sitzung oder eine ältere
`settings.json`, der ein neu hinzugekommener Schlüssel fehlt, löst dadurch keinen
`AttributeError` mehr aus; `save_settings()` liest zusätzlich defensiv über `.get(...)`.

## 8. `data/` und Umgebungsvariablen

| Variable | Standard | Zweck |
| --- | --- | --- |
| `AIVERSUS_DATA_DIR` | `<Projektordner>/data` | Überschreibt, wo `runs.db`, `availability.json`, `embedding_availability.json`, `pricing.json`, `settings.json` und `rag_store/` liegen |
| `AIVERSUS_BASE_URL` | `https://integrate.api.nvidia.com/v1` | Überschreibt die NVIDIA-Build-Basis-URL |

Beide Variablen existieren ausschließlich zur Testisolation: jeder Test/Mock-Lauf
setzt beide auf ein Temp-Verzeichnis bzw. einen lokalen Mock-Server, bevor `app.py`
überhaupt importiert wird - nie mit dem Projektordner als Arbeitsverzeichnis (feste
Regel, siehe projekteigene `CLAUDE.md` und `scripts/verify_data_isolation.py` als
Beweis-Skript).

## 9. Zwei Preiswege

Es gibt zwei unabhängige Wege, einen Preis einzutragen - beide schreiben letztlich in
`st.session_state.model_prices[model_id]` (`{"input", "output", "free"}`), aber nur
einer davon in `pricing.json`:

1. **Zeilenfelder in der Modell-Tabelle** (Hauptbereich, je ausgewähltes Modell):
   zwei `number_input`-Felder (Input-/Output-Preis) direkt in der Zeile - schnell,
   aber ohne Quelle/Datum und nicht in `pricing.json` gespeichert; gilt nur für die
   laufende Sitzung (bzw. wird über `settings.json` nur als nackte Zahl mitgeführt).
2. **Pricing-Dialog** (`st.dialog`, Sidebar-Button): editierbare Tabelle
   (`st.data_editor`, dynamische Zeilenzahl) mit Modell-ID, Input-/Output-Preis,
   Quelle, Aktualisierungsdatum, Free-Tier-Haken. Speichern schreibt nach
   `pricing.json` (die kuratierte, quellenbelegte Referenzliste) und überschreibt
   sofort auch die Zeilenfelder bereits ausgewählter Modelle (die
   `number_input`-Widgets ignorieren ab ihrer ersten Erstellung jedes neue `value=`,
   deshalb der direkte Session-State-Eingriff) - der umgekehrte Weg gilt nicht: ein
   nur in den Zeilenfeldern eingetragener Preis landet nicht automatisch im Dialog/
   in `pricing.json`.

Kosten pro Ergebniszeile: `free` gesetzt → 0.0; kein Preiseintrag (`input == output
== 0.0` ohne `free`) → `None` (unbekannt, nicht 0); sonst `tokens × Preis / 1 000 000`.

## 10. Sterne & Beste Antwort

Pro (Lauf, Prompt): ein Radio-Button markiert die beste Antwort unter den Modellen
dieses Prompts (`store.set_best_answer`), pro (Lauf, Modell, Prompt) `st.feedback
("stars")` für 1-5 Sterne (`store.set_stars`) - beides sofort in `runs.db`
geschrieben, nicht erst beim nächsten Lauf. `wins_per_model()` zählt `is_best = 1`
über alle Läufe für das "Siege pro Modell"-Diagramm (horizontale Balken,
`st.bar_chart(horizontal=True)` - vertikale Balken wurden bei vielen Modellen
zunehmend schmaler, horizontale haben eine feste Balkenbreite).

## 11. Timeline

Jede Zeile `(run_id, model_id, prompt_id)` ist bereits ein Punkt (Primärschlüssel in
`runs.db`) - keine Aggregation nötig. Eine Linie verbindet nur Punkte mit gleichem
`prompt_text` **und** gleichen `temperature`/`top_p`/`max_tokens` (aus `sent_params`
geparst); weicht ein Lauf desselben Modells ab, bekommt er eine eigene Serie
(Altair-`detail`-Encoding, Farbe bleibt modellbezogen) plus einen Hinweis-Caption.
X-Achse: expliziter `scale(domain=[min, max], nice=False)` statt Vega-Lites
automatischem Runden auf "hübsche" Zeitgrenzen (reichte sonst über den tatsächlichen
Zeitraum der gewählten Läufe hinaus), maximal ~6 Ticks, Format `%d.%m. %H:%M`.
Standard-Metrik: `tokens_per_s` (wählbar: auch `generation_s`, `ttft_s`, `latency_s`,
Tokens in/out, Kosten). Standardauswahl der Modelle:
`store.models_ranked_by_recent_metric()` - Modelle mit mindestens einem Wert für die
gewählte Metrik, nach ihrem jüngsten solchen Lauf absteigend sortiert, max. 6 - statt
der vorherigen alphabetischen `known[:6]`. Fehlgeschlagene Zeilen (`ok = 0`) fließen
nicht in die Timeline ein.

## 12. Englisch/Deutsch

`i18n.py` lädt `i18n/<lang>.json` und baut daraus `t(key, **kwargs)`; Englisch ist
Standard und zugleich Fallback, falls ein Schlüssel in der gewählten Sprache (oder
in Englisch selbst) fehlt - dann erscheint der Schlüssel selbst statt eines Absturzes.
Umschaltbar per Radio-Button in der Sidebar (`st.session_state.lang`). Beide
Sprachdateien enthalten aktuell je 163 Schlüssel, vollständig deckungsgleich (kein
Schlüssel existiert nur in einer Sprache).

## 13. Teststand

Zwei Ebenen, keine klassische Testsuite (kein `pytest`, siehe `scripts/`-Hinweis):

- **Automatisiert, gegen Mock-Server + Temp-`AIVERSUS_DATA_DIR`:**
  `streamlit.testing.v1.AppTest` gegen lokale `http.server`-Mocks (simulierte
  Chat-/Embedding-Antworten, gezielt auch 404/400-Fehlerfälle) - deckt alle Fixes
  dieser und der vorangehenden Sitzungen ab (Session-State-Defaults, Ergebniskopf,
  `tokens_per_s`-Schwelle, Timeline-Standardauswahl/-Achse, Embedding-Standardwahl/
  400-Klassifikation, `use_container_width`-Migration). Zwei Skripte sind als
  wiederholbare "Beweis-Skripte" unter `scripts/` eingecheckt (nicht nur
  Wegwerf-Tests):`verify_data_isolation.py` (Testisolation selbst) und
  `verify_settings_defaults.py` (die Session-State-Defaults-Regression).
- **Live, mit echtem NVIDIA-Build-Key:** einmaliger RAG-Live-Test am 02.11.2026
  (echter Key, echter `st.file_uploader`-Upload) lieferte die vier in Abschnitt 5
  genannten Befunde; alle vier Fixes wurden danach nur gegen Mock-Server verifiziert,
  nicht erneut mit echtem Key gegengeprüft (siehe Grenzen, Abschnitt 14).

`scripts/migrate_tokens_per_s_null.py` ist kein Test, sondern eine einmalige
Datenmigration (Dry-Run per Default, `--apply` schreibt) - vor dem Lauf gegen die
echte `runs.db` an einer Kopie geprüft.

## 14. Grenzen

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
- RAG ist am 02.11.2026 live getestet worden (echter Key, echter Upload); die
  dabei gefundenen vier Mängel sind behoben (siehe Abschnitt 5), die Fixes selbst
  aber bisher nur gegen Mock-Server nachgewiesen, nicht erneut mit einem echten Key.
- Reasoning-Tokens kommen, falls vorhanden, aus
  `usage.completion_tokens_details.reasoning_tokens` - zählen zu den Output-Tokens
  und werden nicht von jedem Reasoning-Modell im Katalog separat ausgewiesen.
- Zwei offene Browser-Tabs überschreiben sich bei `settings.json` gegenseitig
  (letzter Schreiber gewinnt) - nur beschrieben, nicht behoben (siehe Backlog).

## 15. Tech-Stack

Python · Streamlit (inkl. Altair für die Timeline-Diagramme, kommt als
Streamlit-Abhängigkeit mit, kein eigener Projekteintrag) · openai-SDK · Pandas ·
ChromaDB · pypdf · sqlite3 (Standardbibliothek). Dev: pyflakes.

---

© 2026 Airdinsh (Erdinç Arslan) · Masterschool AI Engineering Track · MIT-Lizenz (siehe LICENSE im Repo)  
📧 Signlab@gmx.de · 🌐 Airdinsh.com
