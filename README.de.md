# AiVersus

AiVersus lässt dieselben Prompts parallel gegen beliebig viele [NVIDIA Build](https://build.nvidia.com)-Modelle laufen und vergleicht Antworten, Zeiten, Tokens und Kosten - optional mit eigenen Dokumenten als RAG-Kontext.

*(🇬🇧 English version: [README.md](README.md))*

![AiVersus Übersicht](docs/screenshots/overview.png)

## Funktionen

- **Beliebig viele Modelle nebeneinander** - im Live-Katalog von NVIDIA Build suchen,
  so viele Modelle wie gewünscht hinzufügen und wieder entfernen; jedes bekommt eine
  feste Farbe.
- **Parallele Benchmark-Läufe** gegen dieselben Prompts, mit Live-Statuszeile pro
  Modell/Prompt (Warteschlange, generiert, fertig, Fehler, Timeout, abgebrochen) und einem
  **Stop**-Button, der sauber abbricht - fertige Antworten bleiben erhalten, nichts bereits
  Gespeichertes geht verloren.
- **Metriken pro Antwort**: Zeit bis zum ersten Token (TTFT, inkl. NVIDIA-Warteschlange),
  reine Generierungszeit, Input-/Output-Tokens und Tokens pro Sekunde - plus die
  tatsächlich gesendeten Parameter (lehnt ein Modell einen Parameter ab, z.B. `seed`, wird
  einmal ohne ihn wiederholt, sichtbar markiert).
- **Reasoning-Anzeige**: Modelle, die eine eigene Denkspur zurückgeben, zeigen sie in
  einem eigenen, aufklappbaren Bereich auf der Karte, getrennt von der eigentlichen Antwort.
- **Kosten nach selbst eingetragenen Preisen**: Input-/Output-Preis pro Modell eintragen
  (oder als kostenlos markieren); ohne Preis zeigt die Karte unbekannte Kosten, nie
  stillschweigend $0.
- **Bewertung**: pro Prompt die beste Antwort markieren und 1-5 Sterne pro Antwort vergeben;
  beides wird mit dem Lauf gespeichert.
- **Timeline über Läufe**: jeder Lauf wird lokal gespeichert; Latenz, Tokens oder Kosten
  über mehrere Modelle und Läufe vergleichen, plus ein "Siege pro Modell"-Diagramm aus
  deinen Bewertungen.
- **RAG (optional)**: PDF/TXT/MD-Dokumente hochladen, lokaler Index (ChromaDB), Embeddings
  laufen ebenfalls über NVIDIA Build - kein zweiter Anbieter nötig.
- **Export** der Ergebnisse als CSV oder JSON.
- **Englische oder deutsche Oberfläche**, Englisch als Standard, umschaltbar in der Sidebar.

## Screenshots

![AiVersus laufender Benchmark](docs/screenshots/run-progress.png)
*`run-progress.png` - ein laufender Benchmark: Live-Status pro Modell/Prompt.*

![AiVersus Ergebniskarten](docs/screenshots/result-cards.png)
*`result-cards.png` - Ergebniskarten eines Prompts, Antworten aufgeklappt, beste Antwort
markiert und Sterne vergeben.*

![AiVersus Reasoning](docs/screenshots/reasoning.png)
*`reasoning.png` - die Denkspur eines Reasoning-Modells, getrennt von seiner Antwort.*

![AiVersus Ergebnistabelle](docs/screenshots/results-table.png)
*`results-table.png` - alle Ergebnisse eines Laufs als sortierbare Tabelle.*

![AiVersus Timeline](docs/screenshots/timeline.png)
*`timeline.png` - der Timeline-Abschnitt: ein Metrik-Chart über mehrere Läufe plus das
"Siege pro Modell"-Diagramm.*

![AiVersus Pricing-Dialog](docs/screenshots/pricing-dialog.png)
*`pricing-dialog.png` - die editierbare Preisliste, mit Quelle und Datum pro Modell.*

![AiVersus RAG](docs/screenshots/rag.png)
*`rag.png` - die RAG-Sidebar nach dem Indexaufbau, und eine Ergebniskarte mit den
abgerufenen Chunks und dem aufgeklappten Text eines Chunks.*

## Schnellstart

Benötigt [uv](https://docs.astral.sh/uv/) - installiert die in
[`.python-version`](.python-version) festgelegte Python-Version (aktuell 3.14) automatisch,
keine separate Python-Installation nötig.

```bash
git clone https://github.com/Airdinsh-Ai/AiVersus.git
cd AiVersus
uv sync
uv run streamlit run app.py
```

Die vom Terminal ausgegebene lokale Adresse öffnen (Standard `http://localhost:8501`),
dann den NVIDIA-Build-API-Key in der Sidebar eintragen - wie man einen kostenlos bekommt,
steht im nächsten Abschnitt.

## NVIDIA-API-Key (kostenlos)

1. <https://build.nvidia.com/> öffnen und anmelden oder ein kostenloses NVIDIA-Konto anlegen.
2. Im Konto den Bereich für API-Keys öffnen ("Get API Key" auf der Seite) und einen Key
   erzeugen. Er beginnt mit `nvapi-` und wird nur einmal angezeigt.
3. In der AiVersus-Seitenleiste einfügen. Der Key bleibt nur in der Sitzung und wird nie
   gespeichert, geloggt oder exportiert.

Bedingungen und Limits des Free Tiers legt NVIDIA fest und ändert sie gelegentlich;
Wartezeiten können lang sein. Aktuelles auf <https://build.nvidia.com/>.

## Nutzung

1. API-Key eintragen, Verbindung testen, dann ein oder mehrere Modelle unter **Modelle**
   hinzufügen.
2. Einen oder mehrere Prompts in der **Prompt-Suite** schreiben. Die beiden
   mitgelieferten Standard-Prompts zeigen den Unterschied zwischen den
   Techniken-Etiketten: `p1` ist Zero-Shot (direkte Frage, keine Beispiele),
   `p2` ist echtes Few-Shot - eine Stimmungs-Klassifizierung (positiv/negativ/
   neutral) mit drei vorgemachten Beispielen, bevor das Modell die letzte,
   noch unmarkierte Aussage einordnen soll. Das Etikett nur setzen, wenn es
   zum jeweiligen Prompt wirklich passt.
3. Die gemeinsamen **Parameter** setzen (temperature, top_p, max_tokens - Standard 4096,
   bei sichtbarem "Abgeschnitten"-Badge auf einer Karte höher setzen -, optionaler
   System-Prompt, optional fixierter Seed).
4. **Benchmark starten** klicken. Ergebnisse erscheinen als Karten pro Prompt, sobald ein
   Modell fertig ist; die beste Antwort markieren und bei Bedarf Sterne vergeben.
5. Ergebnisse als CSV oder JSON exportieren, oder in der **Timeline** frühere Läufe ansehen.

## RAG (optional)

1. "RAG-Kontext verwenden" in der Sidebar aktivieren.
2. Zuerst "Embedding-Modelle prüfen" klicken - nicht jedes Embedding-Modell im Katalog ist
   für jeden Account erreichbar, die Prüfung blendet die nicht erreichbaren aus.
3. Dokumente hochladen (PDF, TXT, MD) und "Index aufbauen" klicken.

Die relevantesten Abschnitte werden einmal pro Prompt (nicht einmal pro Modell) abgerufen
und als Kontext mitgegeben; jede Ergebniskarte zeigt, ob Kontext injiziert wurde und den
Text der abgerufenen Abschnitte. Der Index liegt lokal in `rag_store/`.

Zum Ausprobieren ohne eigene Dokumente eignet sich
[`examples/rag_testdokument.txt`](examples/rag_testdokument.txt) - ein kurzes, komplett
erfundenes Mitarbeiterhandbuch, gezielt zum Testen der Retrieval-Funktion geschrieben (die
Fakten darin können in keinem Modell als Trainingswissen vorkommen). Beispiel-Prompts dafür:

- "Bis wann müssen Urlaubsanträge eingereicht werden?"
- "Wie heißt der Hausmeister und wann ist er erreichbar?"
- "Wo ist der Notfall-Treffpunkt im Alarmfall?"
- "Welche Inventarnummer hat die Kaffeemaschine im dritten Stock?"

## Daten und Datenschutz

Alles Dauerhafte - `runs.db`, `rag_store/`, `availability.json`,
`embedding_availability.json`, `settings.json`, `pricing.json` - liegt lokal unter `data/`
und ist nicht Teil des Repos (`data/` ist gitignored). Dein API-Key liegt nur im Speicher
der Browser-Sitzung, solange die App offen ist; er wird nie auf die Festplatte geschrieben,
nie geloggt und erscheint in keinem Export (CSV/JSON) und nicht in `runs.db`.

Zwei Umgebungsvariablen legen fest, wo diese Daten liegen und welche API angesprochen wird -
vor allem fürs Testen gedacht, damit ein Testlauf nie das echte `data/` berührt:

- `AIVERSUS_DATA_DIR` - überschreibt den `data/`-Ordner.
- `AIVERSUS_BASE_URL` - überschreibt die Basis-URL der NVIDIA-Build-API.

## Ehrliche Grenzen

- Die Warteschlange eines stark genutzten Modells zählt zur TTFT - eine langsame Antwort
  heißt nicht automatisch ein langsames Modell.
- Kosten werden ausschließlich aus selbst eingetragenen Preisen berechnet (mit explizitem
  "kostenlos"-Haken); eine offizielle NVIDIA-Build-Preisliste zum Vorbefüllen war nicht
  auffindbar, daher zeigt ein Modell ohne Preis unbekannte Kosten statt einer Schätzung.
- Reasoning-Tokens zählen zu den Output-Tokens und werden nicht von jedem Modell separat
  ausgewiesen - manche melden sie, manche nicht.
- Bei `temperature` über 0 sind Antworten nicht deterministisch, auch nicht bei identischem
  Prompt.

## Projektstruktur

- `app.py` - die Streamlit-App (UI, Benchmark-Ausführung, Sidebar).
- `chat_client.py` - Streaming-Chat-Aufrufe, Timeouts, Parameter-Retry-Logik.
- `models.py`, `rag.py`, `storage.py`, `i18n.py` - Modellkatalog, RAG-Index,
  Lauf-Speicherung, Übersetzungen.
- `i18n/` - die Übersetzungsdateien `de.json`/`en.json`.
- `.streamlit/config.toml` - das dunkle Theme.
- `scripts/` - eigenständige Prüf-/Migrationsskripte (keine Testsuite).
- `docs/` - Architektur, Backlog und weitere Projektdokumente (siehe unten).
- `data/` - lokaler, nutzerspezifischer Zustand (gitignored, nicht im Repo).

## Dokumentation

Architektur, Backlog und Entscheidungshistorie liegen unter
[`docs/projekt/dokumente/`](docs/projekt/dokumente).

## Lizenz

MIT - siehe [LICENSE](LICENSE).

---

© 2026 Airdinsh (Erdinç Arslan) · Masterschool AI Engineering Track · MIT-Lizenz (siehe
[LICENSE](LICENSE))
📧 Signlab@gmx.de · 🌐 [Airdinsh.com](https://Airdinsh.com)
