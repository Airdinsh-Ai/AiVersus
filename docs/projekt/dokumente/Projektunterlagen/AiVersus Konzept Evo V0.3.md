# AiVersus Konzept Evo V0.3

Stand: 18.10.2026

## Ziel

AiVersus ist die Software zur Kursaufgabe LLM Vergleich. Sie lässt dieselben Prompts gegen mehrere LLMs laufen und misst Antwort, Tokens, Latenz und Kosten. Optional bindet sie eigene Dokumente als RAG-Kontext ein, und jeder Lauf wird gespeichert, sodass über Wochen eine **Timeline** der Modellentwicklung entsteht. Sie läuft lokal im Browser (`streamlit run app.py`).

## Vorgaben der Aufgabe

- **Comparison Table (Notion-Vorlage):** 5 Modelle: OpenAI gpt-4o-mini, gpt-4.1-mini, gpt-5-mini und Google gemini-2.5-flash, gemini-2.5-pro, mit je 2 Prompts. Pro Zelle: Prompt Technique, Output, Anzahl Output-Tokens, Latenz, Total Cost; dazu Notes und Conclusion. Die Werte liefert die App, die Tabelle wird in Notion ausgefüllt.
- **RAG-Integration** (wie im Referenzprojekt RagLangBot)
- **Projekt-Präsentation**, **Demo-Video**, **GitHub-Repo** mit README

## Kernkomponenten

| Baustein | Aufgabe |
| --- | --- |
| Modellauswahl | Die 5 Modelle der Comparison Table, per Checkbox; je Provider ein API-Key (OpenAI, Google), nur zur Laufzeit eingegeben |
| Prompt-Suite | Prompts mit Prompt Technique (Zero-Shot, Few-Shot, Chain-of-Thought oder frei), bleibt zwischen Läufen fix, damit Unterschiede am Modell liegen |
| Benchmark | Jede Modell×Prompt-Kombination: Antwort, Tokens (in/out), Latenz, geschätzte Kosten, Fehler |
| RAG | Dokument-Upload (PDF/TXT/MD), Chunking, Embedding (OpenAI), ChromaDB, Retrieval, Kontext im Prompt; `injected_context` und Quellen pro Ergebniszeile |
| Speicherung | Jeder Lauf automatisch in SQLite (`runs.db`) |
| Timeline | Modelle und Metrik (Latenz, Tokens, Kosten) wählen, Verlauf über alle gespeicherten Läufe |
| Export | JSON und CSV je Lauf |

## Stand & nächste Schritte

**Fertig:** App mit allen Komponenten oben (bisher nur mit Attrappen getestet, nicht live gegen die Provider-APIs), Konzept, Systemarchitektur, Backlog.

**Offen:** siehe Backlog, vor allem Live-Test mit echten Keys, Läufe und Comparison Table, Präsentation, Demo-Video, GitHub-Push.

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
