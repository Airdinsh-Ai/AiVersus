# Screenshots

Referenziert aus `README.md`/`README.de.md`. Acht PNGs werden hier unter exakt diesen
Namen erwartet - beide READMEs binden sie bereits mit relativen Pfaden + Unterschrift ein.

## Vorgaben für alle Screenshots

- Nur der App-Bereich, ohne Browserleiste/Tabs/Lesezeichenleiste.
- Breite ca. 1400 px.
- Jede Datei möglichst unter ~500 KB (bei Bedarf als PNG optimieren, z.B. mit `pngquant`
  oder `oxipng`).
- Das API-Key-Feld in der Sidebar nie ins Bild nehmen (auch nicht leer/maskiert).
- Daten aus einem Temp-`AIVERSUS_DATA_DIR` (Kopie von `settings.json`/`pricing.json` aus
  `data/`, **nicht** `runs.db`), gegen die echte NVIDIA-Build-API (nicht den Mock-Server) -
  siehe `CLAUDE.md` im Projektordner für die Testisolations-Regel.
- Für die Timeline-Linien zwei (fast) identische Läufe fahren: 5 Modelle, 2 Prompts,
  temperature 0.7, top_p 1.0, max_tokens 4096.
- "Beste Antwort" und Sterne für `result-cards.png`/`timeline.png` selbst vergeben.

## Dateien

- `overview.png` - Hauptansicht: Modelle, Prompts, Parameter (vor dem Start eines Laufs).
- `run-progress.png` - ein laufender Benchmark: Live-Statuszeile pro Modell/Prompt.
- `result-cards.png` - Ergebniskarten eines Prompts, Antworten aufgeklappt, Beste
  Antwort/Sterne gesetzt.
- `reasoning.png` - eine Karte mit aufgeklappter Reasoning-Anzeige (Denkspur getrennt von
  der Antwort) - braucht ein Reasoning-Modell unter den gewählten Modellen.
- `results-table.png` - der aufgeklappte "Alle Ergebnisse als Tabelle"-Expander.
- `timeline.png` - der Timeline-Abschnitt inkl. "Wins per model"-Diagramm, nach den zwei
  Läufen oben.
- `pricing-dialog.png` - der offene Pricing-Dialog mit mind. einem editierten Preis
  (Quelle + Datum sichtbar).
- `rag.png` - die RAG-Sidebar (Index in der Seitenleiste, nach "Index aufbauen") und eine
  Ergebniskarte mit injiziertem RAG-Kontext und aufgeklapptem Chunk-Text - am besten mit
  `examples/rag_testdokument.txt` und einer der im README genannten Testfragen.

Sobald alle acht Dateien hier liegen, kann dieser Hinweistext entfernt werden (die PNGs
sprechen für sich).
