# AiVersus Backlog Evo V0.5

Stand: 02.11.2026 · abgeglichen mit dem tatsächlichen Code und `PROTOKOLL.md`. Bei
Abweichungen gilt der Code.

## Offenes

| Item | Notiz |
| --- | --- |
| Verbindungstest: zu lange Wartezeit | Probiert bis zu 5 Kandidaten nacheinander, jeder mit dem vollen, in der Sidebar eingestellten `first_token_timeout_s` (Standard 300s) - im ungünstigen Fall (mehrere nicht erreichbare Modelle vor dem ersten Treffer) kann das sehr lange dauern, bevor überhaupt ein Ergebnis erscheint (`app.py`, Verbindungstest-Schleife) |
| RAG live testen | Chunking, Embedding-Aufruf, ChromaDB-Zugriff und Katalog-Filter sind einzeln mit gemockten Clients getestet; die volle Kette mit echtem `st.file_uploader`-Upload und echtem NVIDIA-Build-Key wurde noch nie durchgespielt (siehe `PROTOKOLL.md`, "LIVE-TEST OFFEN") |
| Preise mit Quelle und Datum | `pricing.json` ist aktuell leer vorbefüllt - für NVIDIA Build wurde keine auffindbare, offizielle Preistabelle gefunden (siehe `PROTOKOLL.md`); die meisten Modelle haben daher weiterhin keinen echten, quellenbelegten Preis |
| Comparison Table (Kursabgabe) | **Offene Entscheidung:** Die Comparison Table der ursprünglichen Aufgabe verlangt 5 konkrete OpenAI-/Google-Modelle, die App spricht aber inzwischen ausschließlich NVIDIA Build (siehe Entscheidungshistorie, 01.11.2026). Noch nicht entschieden, wie die Tabelle trotzdem befüllt wird - z.B. mit NVIDIA-Build-Gegenstücken statt der exakt vorgegebenen Modelle, oder mit einer befristeten Direktanbindung nur für diesen einen Abgabeschritt |
| Projekt-Präsentation | Noch nicht begonnen |
| Demo-Video | Noch nicht begonnen |
| Ordner aus dem Kursprojekt verschieben | `Privat/AiVersus` liegt noch unter `PythonProject8_Boolsche_Funktionen` (Name einer alten, unabhängigen Bootcamp-Übung) - ein eigenständiges uv-Projekt mit eigenem Git-Repo, aber physisch noch am falschen Ort verschachtelt |
| "Alle Läufe fehlgeschlagen" nicht grün melden | Die Abschlussmeldung nach einem Lauf prüft nur, ob der Nutzer abgebrochen hat (`run["cancelled"]`), nicht ob überhaupt ein Call erfolgreich war - sind alle Zeilen `ok = False`, erscheint trotzdem die grüne Erfolgsmeldung "Fertig - N/N Calls" statt einer Warnung (`app.py`, `_benchmark_progress_fragment`) |

## Bereits erledigt (zur Einordnung - zwei der oben für dieses Dokument vorgegebenen Themen sind beim Code-Abgleich bereits gelöst)

| Item | Wann/wie gelöst |
| --- | --- |
| Timeline-Vergleichbarkeit nach Parametern | Im Rahmen dieser Doku-Sitzung behoben (Commit `f3cf481`, 02.11.2026): eine Linie verbindet nur noch Läufe mit gleichem `prompt_text` und gleichen `temperature`/`top_p`/`max_tokens`; Parameter lagen bereits in `sent_params`/`prompt_text` pro Zeile vor, keine Migration nötig |
| Few-Shot-Etikett bei p2 | Im Rahmen dieser Doku-Sitzung behoben (Commit `6a172e3`, 02.11.2026): der mitgelieferte Standard-Prompt `p2` enthielt keine Beispiele und war trotzdem als "Few-Shot Prompting" etikettiert - ersetzt durch ein echtes Few-Shot-Beispiel (Stimmungs-Klassifizierung mit drei vorgemachten Beispielen). Bleibt ein manuell frei wählbares Etikett ohne automatische Prüfung gegen den Prompt-Text - das gilt weiterhin für jeden selbst geschriebenen Prompt |

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
