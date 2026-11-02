# AiVersus

Eigenständiges uv-Projekt (kein Workspace-Member) - siehe Root-CLAUDE.md für die
allgemeinen Arbeitsregeln (Sprache, Git, Protokoll). Diese Datei ergänzt sie um
AiVersus-spezifische Regeln.

## Tests dürfen nie echte Projektdaten berühren

Hintergrund: Tests und Live-Tests haben in mehreren Sitzungen versehentlich in echte
Projektdaten geschrieben (`data/runs.db`, `data/availability.json`, zuletzt vier
Mock-Zeilen in `runs.db`), weil Testläufe im Projektordner als Arbeitsverzeichnis
liefen. Seitdem laufen alle persistenten Daten über die Konstante `DATA_DIR` in
`app.py` (Standard: `data/` im Projekt, überschreibbar mit `AIVERSUS_DATA_DIR`) und
die API-Basis-URL über `AIVERSUS_BASE_URL` (Standard: die echte NVIDIA-Build-URL).

**Feste Regel**: Jeder Test, Mock-Test oder jedes Scratch-Skript läuft NUR mit

```
AIVERSUS_DATA_DIR=<Temp-Verzeichnis>
AIVERSUS_BASE_URL=<Mock-Server-URL>
```

gesetzt, bevor `app.py` importiert oder ausgeführt wird (per `AppTest`, Subprozess
oder Browser-Test) - nie mit dem Projektordner als Arbeitsverzeichnis und nie ohne
diese beiden Variablen. `app.py` selbst wird für Tests nicht verändert.

Vor jedem Test, der schreiben könnte, die Zeilenzahl von `data/runs.db` notieren
(`SELECT COUNT(*) FROM results`) und danach vergleichen - weicht sie ab, ist etwas
an der Isolation kaputt und der Test ist ungültig, bis das geklärt ist.

Reproduzierbarer Beweis, dass die Isolation funktioniert: `scripts/verify_data_isolation.py`
(startet einen Mock-Server, lässt einen vollständigen Benchmark-Lauf gegen ein
Temp-`DATA_DIR` laufen, vergleicht die Zeilenzahl von `data/runs.db` vorher/nachher).
