# AiVersus Konzept Evo V0.5

Stand: 02.11.2026 · abgeglichen mit dem tatsächlichen Code (`app.py`, `models.py`,
`chat_client.py`, `rag.py`, `storage.py`, `i18n/`). Bei Abweichungen gilt der Code.

## Ziel

AiVersus ist eine lokale Streamlit-App, die beliebig viele Chat-Modelle von
[NVIDIA Build](https://build.nvidia.com) nebeneinander vergleicht: dieselben Prompts
parallel gegen alle laufen lassen, Antwort, Tokens, Latenz und Kosten vergleichen -
optional mit eigenen Dokumenten als RAG-Kontext (die volle Kette mit echtem
Datei-Upload wurde bisher nie live getestet, siehe Backlog). Jeder Lauf wird lokal
gespeichert, sodass über mehrere Sitzungen eine **Timeline** der Modellentwicklung
entsteht. Läuft lokal im Browser (`uv run streamlit run app.py`), Oberfläche auf
Englisch (Standard) oder Deutsch.

## Vorgaben der Aufgabe

Ursprüngliche Kursaufgabe "LLM Vergleich" - unverändert dokumentiert, auch wenn die
App inzwischen ausschließlich NVIDIA Build spricht statt der hier genannten Anbieter
(siehe Backlog, offene Entscheidung "Comparison Table"):

- **Comparison Table (Notion-Vorlage):** 5 Modelle: OpenAI gpt-4o-mini, gpt-4.1-mini,
  gpt-5-mini und Google gemini-2.5-flash, gemini-2.5-pro, mit je 2 Prompts. Pro Zelle:
  Prompt Technique, Output, Anzahl Output-Tokens, Latenz, Total Cost; dazu Notes und
  Conclusion. Die Werte liefert die App, die Tabelle wird in Notion ausgefüllt.
- **RAG-Integration** (wie im Referenzprojekt RagLangBot)
- **Projekt-Präsentation**, **Demo-Video**, **GitHub-Repo** mit README

## Kernkomponenten

| Baustein | Aufgabe |
| --- | --- |
| API-Key | Ein NVIDIA-Build-Key in der Sidebar, nur im Session-State gehalten, nie gespeichert oder geloggt |
| Live-Modellkatalog | `models.list()` bei NVIDIA Build; Dropdown zeigt die Top-10-Modellfamilien (je das laut Namensmuster neueste Modell) plus Trennlinie plus Rest alphabetisch - keine fest eingetragenen Modell-IDs, da NVIDIA Build Modelle entfernt/ersetzt |
| Verbindungstest | Lädt den Katalog neu, probiert dann bis zu 5 Kandidaten nacheinander mit einem kurzen Mini-Call (siehe Backlog: kann dadurch lange dauern) |
| Verfügbarkeitsprüfung | Ein-Klick-Mini-Call an jedes Katalog-Modell (bis zu 5 parallel), Ergebnis dauerhaft in `availability.json` |
| Modellauswahl | Beliebig viele Modelle per Dropdown hinzufügen/entfernen, jedes bekommt eine feste Farbe und einen eigenen Preis (Input/Output $ pro 1M Tokens, oder ein Free-Tier-Haken) |
| LLM-Pricing-Dialog | Eigene, editierbare Preisliste mit Quelle und Datum pro Modell, gespeichert in `pricing.json` |
| Prompt-Suite | Beliebig viele Prompts mit Technik-Etikett (Zero-Shot, Few-Shot, Chain-of-Thought oder frei); zwei mitgelieferte Standard-Prompts zeigen den Unterschied - einer ist Zero-Shot, einer ein echtes Few-Shot-Beispiel (Stimmungs-Klassifizierung mit drei vorgemachten Beispielen) |
| Parameter | temperature/top_p/max_tokens gemeinsam für alle Modelle, optionaler System-Prompt, optionaler fixierter Seed; lehnt ein Modell einen Parameter ab (HTTP 400), wird der Aufruf einmal ohne diesen Parameter wiederholt |
| Benchmark | Bis zu 5 Modell×Prompt-Aufrufe parallel (Streaming, zwei getrennte Zeitüberschreitungen - Warteschlange vs. laufende Generierung), Stop-Button bricht sauber ab, bereits fertige Antworten bleiben erhalten |
| RAG (optional, ungetestet) | Dokument-Upload (PDF/TXT/MD), Chunking, Embedding über ein live aus dem Katalog gewähltes NVIDIA-Build-Modell, lokaler ChromaDB-Index, Retrieval einmal pro Prompt (nicht pro Modell); `injected_context` und Quellenliste pro Ergebniszeile. Die volle Kette mit echtem Datei-Upload und echtem Key wurde bisher nie live getestet |
| Bewertung | Beste Antwort pro Prompt markieren, 1-5 Sterne pro Antwort, "Siege pro Modell"-Diagramm |
| Speicherung | Jede Ergebniszeile wird sofort nach Abschluss in SQLite (`runs.db`) gesichert, damit ein Abbruch mitten im Lauf nichts bereits Fertiges verliert |
| Timeline | Modelle und Metrik wählen (Standard: Tokens/Sekunde); eine Linie verbindet nur Läufe mit gleichem Prompt-Text und gleichen Parametern (temperature/top_p/max_tokens) - bei Abweichung eigene Serie plus Hinweis |
| Export | JSON und CSV je Lauf |
| Sprache | Englisch (Standard) oder Deutsch, umschaltbar in der Sidebar |

## Stand & nächste Schritte

**Fertig:** Alle Bausteine oben sind implementiert und mit `streamlit.testing.v1.AppTest`
sowie einem lokalen Mock-Server getestet, einzelne Bereiche (z.B. die Ergebniskarten)
zusätzlich live im Browser per Chrome-Automatisierung gegen den Mock-Server. Konzept,
Systemarchitektur und Backlog sind auf diesem Stand (Evo V0.5).

**Offen:** siehe Backlog - vor allem RAG nie live mit echtem Key und echtem
Datei-Upload getestet, der Verbindungstest kann im schlechtesten Fall sehr lange
dauern, für die meisten Modelle fehlt noch ein echter, quellenbelegter Preis (keine
offizielle NVIDIA-Build-Preistabelle gefunden), Comparison Table/Präsentation/
Demo-Video für die Kursabgabe stehen noch aus, und der Projektordner liegt noch im
alten Kursprojekt-Verzeichnis.

## UI-Bereiche & Optionen (Rohfassung — nur dieser Abschnitt, frei erweiterbar)

Gesammelt aus zwei Referenzquellen — bewusst nur als Optionsliste, kein Styling-Vorschlag. Quelle A = "LLM Comparison Lab V5"-Screenshots (dicht, viele Felder, filigran). Quelle B = RagLangBot-Video (moderner, minimalistischer, aber weniger Detailtiefe). Mittelweg noch offen — hier nur, *was* an Funktionen/Optionen existiert, nicht *wie* es aussehen soll.

### Navigation / Grundgerüst

- [ ] Tab- oder Sidebar-Navigation (Quelle A: 7 Tabs oben · Quelle B: 4 Nav-Punkte + Icon-Sidebar)
- [ ] Login/Account-Icon (Quelle B)
- [ ] Light/Dark-Mode-Toggle in der Navbar (Quelle B)
- [ ] Dashboard/Startseite mit Übersichtskarten (Quelle B)

### Modelle & Konfiguration

- [ ] Modell-Auswahl per Checkbox, nach Familie gruppiert (Quelle A, bereits umgesetzt)
- [ ] Modell-Auswahl per Dropdown, einzeln pro Konversation/Agent (Quelle B)
- [ ] Eigene Modell-ID manuell ergänzen (Quelle A, bereits umgesetzt)
- [ ] Temperature-Slider (Quelle B)
- [ ] Sichtbarkeit „tatsächlich verwendete Parameter" vs. angefragte (Quelle A: `parameters_actually_used`)

### Agenten (RAG-Konfiguration als eigene Einheit)

- [ ] Agent anlegen: Name, Beschreibung, Modell, Temperature, Dokumenten-Upload (Quelle B, Drag&Drop)
- [ ] Agenten-Übersicht als Kartenraster: Status (Active/…), Erstellungsdatum, direkter Chat-Einstieg (Quelle B)
- [ ] Agent nachträglich bearbeiten (Stift-Icon, Quelle B)
- [ ] Sichtbares Flag pro Ergebnis: wurde RAG-Kontext injiziert? (Quelle A: `injected_context`)

### Chat / Ausführung

- [ ] Einzelchat mit einem Modell, Konversationsverlauf, Modell-Wechsel pro Chat (Quelle B)
- [ ] Konversationsliste in Sidebar, mehrere parallele Chats (Quelle B)
- [ ] Alle Konversationen als eigene Übersichtsseite (Quelle B)

### Vergleich / Benchmark

- [ ] Side-by-side-Vergleich: zwei (oder mehr?) Spalten, gemeinsames Prompt-Feld (Quelle B)
- [ ] Pro Spalte: Response Statistics (Inference Time, Tokens in/out, Tokens/Sekunde, Kosten) getrennt von Model Specifications (Model Size, Context Length, Suggested Use) (Quelle B)
- [ ] Lauf-Liste einzeln anklickbar, mit Status (OK/Fehler) und Latenz je Zeile (Quelle A)
- [ ] Detailansicht pro Ergebnis mit Unter-Tabs: Output · JSON · Technical Settings · Tokens & Cost · Performance · Request (Quelle A)
- [ ] "Nur ausgewählte Modelle erneut laufen lassen" statt immer alles neu (Quelle A)

### Kosten

- [ ] Cost Calculator als eigener Bereich — Kosten vorab schätzen, vor dem eigentlichen Lauf (Quelle A, aktuell nur Backlog-Punkt)
- [ ] Kosten pro Ergebnis in echter Währung, nicht nur Tokens (Quelle A, bereits im Backlog als kritisch)

### Beobachtung & Externe Anbindung

- [ ] Observability/Langfuse als eigener Bereich (Quelle A, aktuell nirgends im Code)
- [ ] Notion-Anbindung als eigener Bereich (Quelle A, aktuell nirgends im Code)

### Export

- [ ] Export als Excel (zusätzlich zu JSON/CSV, Quelle A)

---

*Hier weiterschreiben — eigener Abschnitt, unabhängig vom Rest des Dokuments.*

---

© 2026 Airdinsh (Erdinç Arslan) · Masterschool AI Engineering Track · MIT-Lizenz (siehe LICENSE im Repo)  
📧 Signlab@gmx.de · 🌐 Airdinsh.com
