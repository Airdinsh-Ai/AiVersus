# AiVersus Backlog Evo V0.5

Stand: 02.11.2026 · abgeglichen mit dem tatsächlichen Code und `PROTOKOLL.md`. Bei
Abweichungen gilt der Code.

## Offenes

| Item | Notiz |
| --- | --- |
| Verbindungstest: zu lange Wartezeit | Probiert bis zu 5 Kandidaten nacheinander, jeder mit dem vollen, in der Sidebar eingestellten `first_token_timeout_s` (Standard 300s) - im ungünstigen Fall (mehrere nicht erreichbare Modelle vor dem ersten Treffer) kann das sehr lange dauern, bevor überhaupt ein Ergebnis erscheint (`app.py`, Verbindungstest-Schleife) |
| Preise mit Quelle und Datum | `pricing.json` ist aktuell leer vorbefüllt - für NVIDIA Build wurde keine auffindbare, offizielle Preistabelle gefunden (siehe `PROTOKOLL.md`); die meisten Modelle haben daher weiterhin keinen echten, quellenbelegten Preis |
| Comparison Table (Kursabgabe) | **Offene Entscheidung:** Die Comparison Table der ursprünglichen Aufgabe verlangt 5 konkrete OpenAI-/Google-Modelle, die App spricht aber inzwischen ausschließlich NVIDIA Build (siehe Entscheidungshistorie, 01.11.2026). Noch nicht entschieden, wie die Tabelle trotzdem befüllt wird - z.B. mit NVIDIA-Build-Gegenstücken statt der exakt vorgegebenen Modelle, oder mit einer befristeten Direktanbindung nur für diesen einen Abgabeschritt |
| Projekt-Präsentation | Noch nicht begonnen |
| Demo-Video | Noch nicht begonnen |
| Ordner aus dem Kursprojekt verschieben | `Privat/AiVersus` liegt noch unter `PythonProject8_Boolsche_Funktionen` (Name einer alten, unabhängigen Bootcamp-Übung) - ein eigenständiges uv-Projekt mit eigenem Git-Repo, aber physisch noch am falschen Ort verschachtelt |
| "Alle Läufe fehlgeschlagen" nicht grün melden | Die Abschlussmeldung nach einem Lauf prüft nur, ob der Nutzer abgebrochen hat (`run["cancelled"]`), nicht ob überhaupt ein Call erfolgreich war - sind alle Zeilen `ok = False`, erscheint trotzdem die grüne Erfolgsmeldung "Fertig - N/N Calls" statt einer Warnung (`app.py`, `_benchmark_progress_fragment`) |
| Zwei offene Tabs überschreiben sich bei `settings.json` | **Nur beschrieben, nicht umgesetzt.** `st.session_state` ist pro Browser-Tab getrennt, aber alle Tabs teilen sich dieselbe `settings.json`. `save_settings()` schreibt am Ende jedes Rerun-Zyklus den *kompletten* Snapshot des eigenen `session_state` (Prompts, Modelle, Preise, `last_successful_embed_model`) und überschreibt die Datei dabei vollständig - "letzter Schreiber gewinnt". Tab A liest `settings.json` nur einmal beim eigenen ersten Lauf (`_saved_settings = load_settings()`); ändert Tab B danach z.B. die Prompts und speichert, überschreibt der nächste Rerun von Tab A (der die alten Prompts noch in seinem `session_state` trägt) Tab Bs Änderung kommentarlos wieder - keine Fehlermeldung, kein Merge, kein Hinweis an den Nutzer. Betrifft nur `settings.json` (`runs.db` ist unkritisch: jede Zeile hat einen eigenen Primärschlüssel, kein Gesamt-Overwrite). **Vorschlag (nicht umgesetzt):** vor dem Schreiben die aktuelle Datei erneut laden und Feld für Feld mergen statt den ganzen Dict zu überschreiben (reduziert die Kollision auf sich wirklich überlappende Felder), oder die Datei-`mtime` beim eigenen `load_settings()`-Zeitpunkt merken und vor dem Schreiben vergleichen - hat sie sich seitdem geändert, warnen statt stillschweigend zu überschreiben. Keine der beiden Varianten verhindert das Problem vollständig (Streamlit hat keinen eingebauten Sitzungs-übergreifenden Zustand), macht es aber sichtbar bzw. seltener |

## Bereits erledigt (zur Einordnung - zum Zeitpunkt des Code-Abgleichs bereits gelöste Themen)

| Item | Wann/wie gelöst |
| --- | --- |
| Timeline-Vergleichbarkeit nach Parametern | Im Rahmen dieser Doku-Sitzung behoben (Commit `f3cf481`, 02.11.2026): eine Linie verbindet nur noch Läufe mit gleichem `prompt_text` und gleichen `temperature`/`top_p`/`max_tokens`; Parameter lagen bereits in `sent_params`/`prompt_text` pro Zeile vor, keine Migration nötig |
| Few-Shot-Etikett bei p2 | Im Rahmen dieser Doku-Sitzung behoben (Commit `6a172e3`, 02.11.2026): der mitgelieferte Standard-Prompt `p2` enthielt keine Beispiele und war trotzdem als "Few-Shot Prompting" etikettiert - ersetzt durch ein echtes Few-Shot-Beispiel (Stimmungs-Klassifizierung mit drei vorgemachten Beispielen). Bleibt ein manuell frei wählbares Etikett ohne automatische Prüfung gegen den Prompt-Text - das gilt weiterhin für jeden selbst geschriebenen Prompt |
| RAG live getestet (02.11.2026) | Drei Befunde aus dem Live-Test behoben, je ein Commit: (1) Embedding-Modelle werden jetzt vor dem Indexieren per Mini-Call geprüft (analog zur Chat-Verfügbarkeitsprüfung), nicht erreichbare ausgeblendet, Standard ist das zuletzt erfolgreiche Modell (Commit `741481d`); (2) die ChromaDB-Collection ist jetzt über ihre Metadaten an genau ein Embedding-Modell gebunden - ein Wechsel bei vorhandenen Chunks wird verweigert (`EmbedModelMismatch`) statt leise unterschiedliche Vektor-Dimensionen zu mischen (Commit `8d585c8`); (3) die Ergebniskarte zeigt zusätzlich zur Quelle jetzt auch den abgerufenen Chunk-Text, pro Chunk eingeklappt per Toggle (Commit `199e9af`). Die drei Fixes selbst wurden in dieser Sitzung nur gegen einen lokalen Mock-Server mit simulierten Embeddings nachgewiesen (`streamlit.testing.v1.AppTest`, kein echter NVIDIA-Build-Key in dieser Umgebung) - der Live-Test mit echtem Key/Upload, der diese drei Befunde ursprünglich lieferte, lief separat |

## Entscheidungshistorie (verworfen oder ersetzt — nur hier dokumentiert)

| Datum | Entscheidung | Grund |
| --- | --- | --- |
| 18.10.2026 | `apprealism` (natives App-Fenster via pywebview, 3 Themes) entfernt | Nutzung läuft über den Browser (`streamlit run app.py`); das Design kommt separat |
| 18.10.2026 | Eigenes CLI-Script entfernt | Die App deckt alles ab |
| 01.11.2026 | OpenAI/Google-Direktanbindung entfernt, NVIDIA Build als einziger Anbieter (Commit `342167a`) | Die Pflichtmodelle der ursprünglichen Comparison-Table-Aufgabe waren OpenAI/Google (siehe V0.3-Dokumente) - das wird hiermit erneut umgekehrt: ein OpenAI-kompatibler Client gegen NVIDIA Build, Live-Katalog statt fester Modell-IDs, ein Key statt zweien. Siehe Backlog-Punkt "Comparison Table" für den dadurch offenen Konflikt |
| 02.11.2026 | `pricing.py` (feste Preistabelle im Code) entfernt (Commit `efa1570`) | Preise kommen seit dem Pricing-Dialog ausschließlich noch aus `pricing.json`; der alte Code-Fallback war seitdem unbenutzt und doppelte Wahrheitsquelle |

## Konventionen

- Das Projekt heißt **AiVersus**. „Evo V0.x" (Evolution Version) ist nur die Versionsbezeichnung der Dokumente: „AiVersus [Typ] Evo V0.x".
- Der Code im Repo ist die Wahrheit; Dokumente beschreiben ihn und werden bei Änderungen nachgezogen.
- API-Keys werden nur zur Laufzeit in der Sidebar eingegeben und nirgends gespeichert.
- Jeder Test läuft nur mit `AIVERSUS_DATA_DIR`/`AIVERSUS_BASE_URL` gesetzt, nie gegen die echten Projektdaten (siehe projekteigene `CLAUDE.md`).

---

© 2026 Airdinsh (Erdinç Arslan) · Masterschool AI Engineering Track · MIT-Lizenz (siehe LICENSE im Repo)  
📧 Signlab@gmx.de · 🌐 Airdinsh.com
