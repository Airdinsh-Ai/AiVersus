# AiVersus

Vergleicht LLMs mit denselben Prompts (Antwort, Tokens, Latenz, Kosten), optional mit eigenen Dokumenten als RAG-Kontext, und zeigt über mehrere Läufe eine Timeline. Läuft lokal im Browser.

## Start

```bash
uv run streamlit run app.py
```

API-Keys (OpenAI, Google Gemini) trägst du in der Sidebar ein. Sie werden nirgends gespeichert.

## Nutzung

1. Keys eintragen, Modelle in der Sidebar wählen (Standard: die 5 Modelle der Comparison Table).
2. Prompts und **Prompt Technique** (Zero-Shot, Few-Shot, Chain-of-Thought oder frei) pflegen.
3. **Benchmark starten**: Jede Modell×Prompt-Kombination läuft einmal. Die Tabelle zeigt Antwort, Tokens, Latenz und geschätzte Kosten und kann als CSV oder JSON exportiert werden.

## RAG (optional)

Dokumente (PDF, TXT, MD) hochladen, **Index aufbauen** und **RAG-Kontext verwenden** aktivieren. Pro Prompt werden die ähnlichsten Abschnitte abgerufen und dem Modell als Kontext mitgegeben. Jede Ergebniszeile zeigt `injected_context` und die verwendeten Quellen. Die Embeddings laufen über den OpenAI-Key. Der Index liegt in `rag_store/`.

## Timeline

Jeder Lauf wird in `runs.db` gespeichert. Der Bereich **Timeline** zeigt für gewählte Modelle Latenz, Tokens oder Kosten über alle gespeicherten Läufe. Die Zeitreihe setzt voraus, dass der Anbieter die Modell-ID stabil hält.

## Kosten

Die Kosten sind Schätzwerte aus Tokens × Preistabelle (`pricing.py`, Richtwerte). Vor einer Abgabe gegen die aktuellen Preise der Anbieter prüfen.

---

© 2026 Airdinsh (Erdinç Arslan) · Masterschool AI Engineering Track · MIT-Lizenz (siehe LICENSE im Repo)  
📧 Signlab@gmx.de · 🌐 Airdinsh.com
