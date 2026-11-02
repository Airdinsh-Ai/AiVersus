# AiVersus Backlog Evo V0.6

Stand: 02.11.2026 · abgeglichen mit dem tatsächlichen Code und `PROTOKOLL.md`. Bei
Abweichungen gilt der Code.

## Offenes

| Item | Notiz |
| --- | --- |
| Verbindungstest: zu lange Wartezeit | Probiert bis zu 5 Kandidaten nacheinander, jeder mit dem vollen, in der Sidebar eingestellten `first_token_timeout_s` (Standard 300s) - im ungünstigen Fall (mehrere nicht erreichbare Modelle vor dem ersten Treffer) kann das sehr lange dauern, bevor überhaupt ein Ergebnis erscheint (`app.py`, Verbindungstest-Schleife) |
| Preise mit Quelle und Datum | `pricing.json` ist aktuell leer vorbefüllt - für NVIDIA Build wurde keine auffindbare, offizielle Preistabelle gefunden (siehe `PROTOKOLL.md`); die meisten Modelle haben daher weiterhin keinen echten, quellenbelegten Preis |
| Ordner aus dem Kursprojekt verschieben | `Privat/AiVersus` liegt noch unter `PythonProject8_Boolsche_Funktionen` (Name einer alten, unabhängigen Bootcamp-Übung) - ein eigenständiges uv-Projekt mit eigenem Git-Repo, aber physisch noch am falschen Ort verschachtelt |
| "Alle Läufe fehlgeschlagen" nicht grün melden | Die Abschlussmeldung nach einem Lauf prüft nur, ob der Nutzer abgebrochen hat (`run["cancelled"]`), nicht ob überhaupt ein Call erfolgreich war - sind alle Zeilen `ok = False`, erscheint trotzdem die grüne Erfolgsmeldung "Fertig - N/N Calls" statt einer Warnung (`app.py`, `_benchmark_progress_fragment`) |
| Zwei offene Tabs überschreiben sich bei `settings.json` | **Nur beschrieben, nicht umgesetzt.** `st.session_state` ist pro Browser-Tab getrennt, aber alle Tabs teilen sich dieselbe `settings.json`. `save_settings()` schreibt am Ende jedes Rerun-Zyklus den *kompletten* Snapshot des eigenen `session_state` (Prompts, Modelle, Preise, `last_successful_embed_model`) und überschreibt die Datei dabei vollständig - "letzter Schreiber gewinnt". Tab A liest `settings.json` nur einmal beim eigenen ersten Lauf (`_saved_settings = load_settings()`); ändert Tab B danach z.B. die Prompts und speichert, überschreibt der nächste Rerun von Tab A (der die alten Prompts noch in seinem `session_state` trägt) Tab Bs Änderung kommentarlos wieder - keine Fehlermeldung, kein Merge, kein Hinweis an den Nutzer. Betrifft nur `settings.json` (`runs.db` ist unkritisch: jede Zeile hat einen eigenen Primärschlüssel, kein Gesamt-Overwrite). **Vorschlag (nicht umgesetzt):** vor dem Schreiben die aktuelle Datei erneut laden und Feld für Feld mergen statt den ganzen Dict zu überschreiben (reduziert die Kollision auf sich wirklich überlappende Felder), oder die Datei-`mtime` beim eigenen `load_settings()`-Zeitpunkt merken und vor dem Schreiben vergleichen - hat sie sich seitdem geändert, warnen statt stillschweigend zu überschreiben. Keine der beiden Varianten verhindert das Problem vollständig (Streamlit hat keinen eingebauten Sitzungs-übergreifenden Zustand), macht es aber sichtbar bzw. seltener |

## Bereits erledigt (zur Einordnung - zum Zeitpunkt des Code-Abgleichs bereits gelöste Themen)

| Item | Wann/wie gelöst |
| --- | --- |
| Timeline-Vergleichbarkeit nach Parametern | Commit `f3cf481`, 02.11.2026: eine Linie verbindet nur noch Läufe mit gleichem `prompt_text` und gleichen `temperature`/`top_p`/`max_tokens` |
| Few-Shot-Etikett bei p2 | Commit `6a172e3`, 02.11.2026: der mitgelieferte Standard-Prompt `p2` enthielt keine Beispiele und war trotzdem als "Few-Shot Prompting" etikettiert - ersetzt durch ein echtes Few-Shot-Beispiel |
| RAG live getestet (02.11.2026), drei Befunde | Embedding-Modelle vor dem Indexieren per Mini-Call geprüft (Commit `741481d`); Collection über Metadaten an ein Embedding-Modell gebunden, `EmbedModelMismatch` statt stillem Mischen (Commit `8d585c8`); Ergebniskarte zeigt den abgerufenen Chunk-Text (Commit `199e9af`) |
| `save_settings()`-AttributeError nach Schlüssel-Erweiterung | Ein neu hinzugekommener Session-State-Schlüssel (`last_successful_embed_model`) ließ `save_settings()` mit `AttributeError` abstürzen, sobald eine bestehende Sitzung oder eine ältere `settings.json` ihn noch nicht kannte - behoben: alle Schlüssel per `setdefault()` angelegt, `save_settings()` liest über `.get(...)` (Commits `d5329b9`, `3271ee8`, Regressionsbeweis `scripts/verify_settings_defaults.py` in `f6c7dc8`) |
| Ergebniskopf: Prompt-Text zerriss das Markdown | Ein mehrzeiliger Prompt-Text innerhalb von `**...**` brach die Fettschrift - jetzt nur die Prompt-ID fett, Text als eigene Zeile, eingeklappt wenn lang (Commit `ce02ead`) |
| Irreführende Tokens/s bei Mikro-Generierungszeit | `tokens_out/generation_s` bei `generation_s < 0.05s` ist Messrauschen, keine belastbare Rate - zeigt jetzt "–" (Commit `9f6b866`); betroffene Altzeilen in der echten `runs.db` per `scripts/migrate_tokens_per_s_null.py` auf `NULL` korrigiert (4 Zeilen, `poolside/laguna-xs-2.1`) |
| "Siege pro Modell": gestauchte Balken bei vielen Modellen | `st.bar_chart(horizontal=True)` statt vertikal (Commit `482843b`) |
| Timeline: x-Achse über den Lauf-Zeitraum hinaus, Standardauswahl alphabetisch | Expliziter `scale(domain=…, nice=False)` (Commit `60bf388`); Standardauswahl jetzt nach Messwert+Aktualität gerankt statt alphabetisch (`models_ranked_by_recent_metric()`, Commit `63515dc`) |
| `use_container_width` veraltet | Alle 11 Stellen auf `width="stretch"` umgestellt, Mindestversion geprüft (Streamlit ≥1.51.0 nötig, `pyproject.toml` fordert bereits ≥1.66.0) (Commit `b69ee92`) |
| Embedding-Standardwahl wählte blind ein inkompatibles/vl-Modell | Live-Test-Befund: `nvidia/llama-nemotron-embed-vl-1b-v2` wurde als Standard gewählt, lieferte 400. Jetzt: 400 → eigener Status "incompatible" (nicht "slow"), Namen mit "-vl-" nie als Standard, `_pick_default_embed_model()` ersetzt das alte `embed_choices[0]` (Commit `4a98999`) |
| README überarbeitet, `pricing.json`-Aussage korrigiert, Screenshots werden eingecheckt | README/README.de komplett neu (API-Key-Anleitung, Grenzen, `examples/rag_testdokument.txt`), falsche Aussage "pricing.json wird eingecheckt" entfernt (liegt wie alles andere unter `data/`, komplett gitignored), Screenshot-Hinweistext "nicht eingecheckt" entfernt (Commits `e9d64b3`, `8927a34`, `f18cda2`) |

## Entscheidungshistorie (verworfen oder ersetzt — nur hier dokumentiert)

| Datum | Entscheidung | Grund |
| --- | --- | --- |
| 18.10.2026 | `apprealism` (natives App-Fenster via pywebview, 3 Themes) entfernt | Nutzung läuft über den Browser (`streamlit run app.py`); das Design kommt separat |
| 18.10.2026 | Eigenes CLI-Script entfernt | Die App deckt alles ab |
| 01.11.2026 | OpenAI/Google-Direktanbindung entfernt, NVIDIA Build als einziger Anbieter (Commit `342167a`) | Die Pflichtmodelle der ursprünglichen Comparison-Table-Aufgabe waren OpenAI/Google (siehe V0.3-Dokumente) - das wird hiermit erneut umgekehrt: ein OpenAI-kompatibler Client gegen NVIDIA Build, Live-Katalog statt fester Modell-IDs, ein Key statt zweien |
| 02.11.2026 | `pricing.py` (feste Preistabelle im Code) entfernt (Commit `efa1570`) | Preise kommen seit dem Pricing-Dialog ausschließlich noch aus `pricing.json`; der alte Code-Fallback war seitdem unbenutzt und doppelte Wahrheitsquelle |
| 02.11.2026 | Comparison Table: NVIDIA-Build-Modelle statt der ursprünglich vorgegebenen 5 OpenAI-/Google-Modelle | Folgeentscheidung zur NVIDIA-Build-Umstellung vom 01.11.2026 - die Comparison Table der Kursaufgabe wird mit NVIDIA-Build-Gegenstücken befüllt statt mit einer befristeten Direktanbindung an OpenAI/Google. **Nicht mit der Schule/dem Kurs abgestimmt** - ein Rückbau (befristete Direktanbindung nur für diesen Abgabeschritt) bleibt eine Option, falls das nicht akzeptiert wird |
| 02.11.2026 | "Demo-Video" und "Projekt-Präsentation" aus dem Backlog gestrichen | Entschieden: als Abgabe genügen das Repo und das README mit Screenshots, kein separates Video oder eine separate Präsentation |

## Konventionen

- Das Projekt heißt **AiVersus**. „Evo V0.x" (Evolution Version) ist nur die Versionsbezeichnung der Dokumente: „AiVersus [Typ] Evo V0.x".
- Der Code im Repo ist die Wahrheit; Dokumente beschreiben ihn und werden bei Änderungen nachgezogen.
- API-Keys werden nur zur Laufzeit in der Sidebar eingegeben und nirgends gespeichert.
- Jeder Test läuft nur mit `AIVERSUS_DATA_DIR`/`AIVERSUS_BASE_URL` gesetzt, nie gegen die echten Projektdaten (siehe projekteigene `CLAUDE.md`).

---

© 2026 Airdinsh (Erdinç Arslan) · Masterschool AI Engineering Track · MIT-Lizenz (siehe LICENSE im Repo)  
📧 Signlab@gmx.de · 🌐 Airdinsh.com
