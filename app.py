# -*- coding: utf-8 -*-
#
# AiVersus – LLM-Vergleich (Evo V0.3)
# © 2026 Airdinsh (Erdinç Arslan) · MIT License · Masterschool AI Engineering Track
# Signlab@gmx.de · https://Airdinsh.com
#

"""
AiVersus: LLMs mit denselben Prompts vergleichen (Antwort, Tokens, Latenz, Kosten),
optional mit eigenen Dokumenten als RAG-Kontext, jeder Lauf wird für die Timeline gespeichert.

Start:   pip install -r requirements.txt
         streamlit run app.py
API-Keys werden in der Sidebar eingegeben und nirgends gespeichert.
"""

import json
import time
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
from openai import OpenAI

from pricing import estimate_cost_usd
from rag import RagIndex, build_prompt
from storage import RunStore

st.set_page_config(page_title="AiVersus", page_icon="🧪", layout="wide")
store = RunStore()

# Beide Provider sprechen über das openai-SDK; Google bietet dafür einen kompatiblen Endpunkt.
PROVIDERS = {
    "openai": {"label": "OpenAI", "base_url": None, "placeholder": "sk-..."},
    "google": {
        "label": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "placeholder": "AIza...",
    },
}
# Die Modelle der Comparison Table. Schlüssel überall: "provider:modell"
MODELS = [
    ("openai", "gpt-4o-mini"),
    ("openai", "gpt-4.1-mini"),
    ("openai", "gpt-5-mini"),
    ("google", "gemini-2.5-flash"),
    ("google", "gemini-2.5-pro"),
]
TECHNIQUES = ["Zero-Shot Prompting", "Few-Shot Prompting", "Chain-of-Thought Prompting", "Andere…"]

if "prompts" not in st.session_state:
    st.session_state.prompts = [
        {"id": "p1", "text": "Erkläre RAG in 3 Sätzen.", "technique": "Zero-Shot Prompting"},
        {"id": "p2", "text": "Schreibe eine Python-Funktion für Fibonacci.", "technique": "Few-Shot Prompting"},
    ]
if "results" not in st.session_state:
    st.session_state.results = []


@st.cache_resource
def get_index(openai_key: str) -> RagIndex:
    return RagIndex(api_key=openai_key)


# ---------------- Sidebar ----------------
st.sidebar.header("API-Keys")
keys = {
    p: st.sidebar.text_input(cfg["label"], type="password", placeholder=cfg["placeholder"], key=f"key_{p}")
    for p, cfg in PROVIDERS.items()
}

st.sidebar.header("Modelle")
selected = [
    f"{p}:{m}" for p, m in MODELS
    if st.sidebar.checkbox(f"{m}  ({PROVIDERS[p]['label']})", value=True, key=f"cb_{p}:{m}")
]

st.sidebar.header("RAG (optional)")
index = get_index(keys["openai"]) if keys["openai"] else None
use_rag = st.sidebar.checkbox("RAG-Kontext verwenden", value=False)
top_k = st.sidebar.slider("Top-K Chunks", 1, 10, 4, disabled=not use_rag)
uploads = st.sidebar.file_uploader("Dokumente (PDF, TXT, MD)", type=["pdf", "txt", "md"], accept_multiple_files=True)

if st.sidebar.button("Index aufbauen", disabled=not (index and uploads)):
    with st.sidebar, st.spinner("Chunking + Embedding ..."):
        for f in uploads:
            index.add_document(f.name, f.getvalue())
if st.sidebar.button("Index leeren", disabled=not index):
    index.clear()
if index:
    for name, n in index.sources().items():
        st.sidebar.caption(f"· {name} ({n} Chunks)")
elif use_rag:
    st.sidebar.caption("RAG braucht den OpenAI-Key (Embeddings).")

# ---------------- Prompt-Suite ----------------
st.title("AiVersus")
st.subheader("Prompt-Suite")

to_delete = None
for i, p in enumerate(st.session_state.prompts):
    col_text, col_tech, col_del = st.columns([6, 3, 1])
    p["text"] = col_text.text_area(p["id"], value=p["text"], key=f"text_{p['id']}")
    choice = col_tech.selectbox(
        "Prompt Technique", TECHNIQUES,
        index=TECHNIQUES.index(p["technique"]) if p["technique"] in TECHNIQUES else len(TECHNIQUES) - 1,
        key=f"tech_{p['id']}",
    )
    p["technique"] = col_tech.text_input("eigene Bezeichnung", value="", key=f"own_{p['id']}") if choice == "Andere…" else choice
    col_del.write("")
    col_del.write("")
    if col_del.button("✕", key=f"del_{p['id']}"):
        to_delete = i
if to_delete is not None:
    st.session_state.prompts.pop(to_delete)
    st.rerun()

if st.button("+ Prompt hinzufügen"):
    st.session_state.prompts.append(
        {"id": f"p{len(st.session_state.prompts) + 1}", "text": "", "technique": "Zero-Shot Prompting"}
    )
    st.rerun()

st.divider()
prompts = [p for p in st.session_state.prompts if p["text"].strip()]
st.write(f"**{len(selected)}** Modelle × **{len(prompts)}** Prompts = **{len(selected) * len(prompts)}** API-Calls")

missing = sorted({PROVIDERS[m.split(":")[0]]["label"] for m in selected if not keys[m.split(":")[0]]})
if missing:
    st.warning("API-Key fehlt für: " + ", ".join(missing))
rag_ready = bool(use_rag and index and index.document_count() > 0)
if use_rag and not rag_ready:
    st.warning("RAG ist aktiv, aber es ist noch kein Dokument indexiert — der Lauf geht ohne Kontext.")

# ---------------- Ausführung ----------------
if st.button("▶ Benchmark starten", type="primary", disabled=not (selected and prompts) or bool(missing)):
    clients = {
        p: OpenAI(base_url=PROVIDERS[p]["base_url"], api_key=keys[p])
        for p in {m.split(":")[0] for m in selected}
    }
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    tasks = [(m, p) for m in selected for p in prompts]
    results = []
    progress = st.progress(0.0)

    for n, (model_id, prompt) in enumerate(tasks):
        progress.progress(n / len(tasks), text=f"{model_id} · {prompt['id']}")
        provider, _, model = model_id.partition(":")
        retrieved = index.retrieve(prompt["text"], top_k) if rag_ready else []
        row = {
            "run_id": run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model_id": model_id,
            "prompt_id": prompt["id"],
            "technique": prompt["technique"],
            "injected_context": rag_ready,
            "retrieved_sources": [f"{c.source}#{c.chunk_index}" for c in retrieved],
        }
        start = time.perf_counter()
        try:
            resp = clients[provider].chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": build_prompt(prompt["text"], retrieved)}],
            )
            row.update(
                ok=True,
                response=resp.choices[0].message.content,
                tokens_in=resp.usage.prompt_tokens if resp.usage else None,
                tokens_out=resp.usage.completion_tokens if resp.usage else None,
            )
        except Exception as e:  # Fehler (Key, Limit, Modellname) landen als Zeile im Ergebnis
            row.update(ok=False, response=str(e), tokens_in=None, tokens_out=None)
        row["latency_s"] = round(time.perf_counter() - start, 3)
        row["cost_usd"] = estimate_cost_usd(model_id, row["tokens_in"], row["tokens_out"])
        results.append(row)

    progress.progress(1.0, text="Fertig")
    st.session_state.results = results
    store.save_results(results)

# ---------------- Ergebnisse ----------------
if st.session_state.results:
    st.subheader("Ergebnisse")
    df = pd.DataFrame(st.session_state.results)
    st.dataframe(
        df[["model_id", "prompt_id", "technique", "ok", "injected_context",
            "latency_s", "tokens_in", "tokens_out", "cost_usd", "response"]],
        use_container_width=True,
    )
    st.caption(f"Geschätzte Gesamtkosten dieses Laufs: ${df['cost_usd'].sum():.6f} (Preise: pricing.py, Richtwerte)")
    run_id = st.session_state.results[0]["run_id"]
    col_json, col_csv = st.columns(2)
    col_json.download_button("JSON", json.dumps(st.session_state.results, ensure_ascii=False, indent=2),
                             file_name=f"results_{run_id}.json", mime="application/json")
    col_csv.download_button("CSV", df.to_csv(index=False).encode("utf-8"),
                            file_name=f"results_{run_id}.csv", mime="text/csv")

# ---------------- Timeline ----------------
st.divider()
st.subheader("Timeline")
known = store.known_models()
if not known:
    st.caption("Noch keine gespeicherten Läufe — nach dem ersten Benchmark erscheint hier der Verlauf.")
else:
    chosen = st.multiselect("Modelle", known, default=known[:3])
    metric = st.selectbox(
        "Metrik", ["latency_s", "tokens_out", "tokens_in", "cost_usd"],
        format_func=lambda m: {"latency_s": "Latenz (s)", "tokens_out": "Output-Tokens",
                               "tokens_in": "Input-Tokens", "cost_usd": "Kosten (USD)"}[m],
    )
    if chosen:
        hist = store.load_for_models(chosen)
        chart = (
            hist.groupby([hist["timestamp"].dt.floor("min"), "model_id"])[metric].mean()
            .reset_index().pivot(index="timestamp", columns="model_id", values=metric)
        )
        st.line_chart(chart)
        st.caption(
            f"{store.run_count()} Lauf/Läufe gespeichert. Voraussetzung: Der Anbieter hält die Modell-ID stabil — "
            "bei einer Umbenennung reißt die Zeitreihe ab."
        )
