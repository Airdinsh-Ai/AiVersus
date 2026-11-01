# -*- coding: utf-8 -*-
#
# AiVersus – LLM-Vergleich (Evo V0.4)
# © 2026 Airdinsh (Erdinç Arslan) · MIT License · Masterschool AI Engineering Track
# Signlab@gmx.de · https://Airdinsh.com
#

"""
AiVersus: LLMs mit denselben Prompts vergleichen (Antwort, Tokens, Latenz, Kosten),
optional mit eigenen Dokumenten als RAG-Kontext, jeder Lauf wird für die Timeline gespeichert.

Anbieter: NVIDIA Build (OpenAI-kompatible API, https://build.nvidia.com).

Start:   uv run streamlit run app.py
API-Key wird in der Sidebar eingegeben, nur im Session-State gehalten und nirgends
gespeichert (kein .env-Fallback, kein Logging, nicht in runs.db, nicht in Exporten).
"""

import json
import time
from collections import Counter
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    NotFoundError,
    OpenAI,
    RateLimitError,
)

from chat_client import call_chat_streaming
from models import SEPARATOR, build_dropdown_options, fetch_chat_models, pick_quick_test_model
from pricing import estimate_cost_usd
from rag import RagIndex, build_prompt
from storage import RunStore

st.set_page_config(page_title="AiVersus", page_icon="🧪", layout="wide")
store = RunStore()

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
REQUEST_TIMEOUT_S = 60.0  # ein hängender Call darf den Lauf/die Session nicht blockieren
TECHNIQUES = ["Zero-Shot Prompting", "Few-Shot Prompting", "Chain-of-Thought Prompting", "Andere…"]

if "prompts" not in st.session_state:
    st.session_state.prompts = [
        {"id": "p1", "text": "Erkläre RAG in 3 Sätzen.", "technique": "Zero-Shot Prompting"},
        {"id": "p2", "text": "Schreibe eine Python-Funktion für Fibonacci.", "technique": "Few-Shot Prompting"},
    ]
if "results" not in st.session_state:
    st.session_state.results = []


def _original_message(e: Exception) -> str:
    """Die Original-Fehlermeldung aus dem Response-Body von NVIDIA Build, falls vorhanden."""
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
        if body.get("message"):
            return str(body["message"])
    return str(e)


def describe_api_error(e: Exception) -> str:
    """Lesbare deutsche Fehlermeldung statt Traceback in der UI, inkl. Original-Meldung."""
    if isinstance(e, TimeoutError):  # unser eigener Stream-Timeout (chat_client.py), kein Server-Fehler
        return f"Zeitüberschreitung: {e}"
    detail = _original_message(e)
    if isinstance(e, AuthenticationError):
        return f"API-Key ungültig oder abgelehnt (401). NVIDIA Build: {detail}"
    if isinstance(e, RateLimitError):
        return f"Rate-Limit bei NVIDIA Build erreicht (429) - kurz warten und erneut versuchen. NVIDIA Build: {detail}"
    if isinstance(e, NotFoundError):
        return f"Modell nicht gefunden (404) - Modell-ID in NVIDIA Build prüfen. NVIDIA Build: {detail}"
    if isinstance(e, APIStatusError) and e.status_code == 410:
        return f"Modell nicht mehr verfügbar (410) - bitte ein anderes Modell wählen. NVIDIA Build: {detail}"
    if isinstance(e, APIStatusError):
        return f"NVIDIA Build hat den Aufruf abgelehnt (Status {e.status_code}). NVIDIA Build: {detail}"
    if isinstance(e, APITimeoutError):
        return f"Zeitüberschreitung ({REQUEST_TIMEOUT_S:.0f} s) - keine Antwort von NVIDIA Build erhalten."
    if isinstance(e, APIConnectionError):
        return f"Verbindung zu NVIDIA Build fehlgeschlagen (Netzwerk): {detail}"
    if isinstance(e, APIError):
        return f"Verbindung zu NVIDIA Build fehlgeschlagen: {detail}"
    return f"Unbekannter Fehler beim API-Aufruf: {detail}"


@st.cache_resource
def get_index(api_key: str) -> RagIndex:
    return RagIndex(api_key=api_key)


@st.cache_data(ttl=300, show_spinner="Modellkatalog wird geladen ...")
def _load_chat_models(api_key: str) -> list:
    client = OpenAI(base_url=NVIDIA_BASE_URL, api_key=api_key, timeout=REQUEST_TIMEOUT_S, max_retries=0)
    return fetch_chat_models(client)


# ---------------- Sidebar: API-Key ----------------
st.sidebar.header("NVIDIA Build API-Key")
nvidia_key = st.sidebar.text_input(
    "API-Key",
    type="password",
    placeholder="nvapi-...",
    key="nvidia_api_key",
    help="Nur für diese Sitzung im Speicher - wird nicht geloggt, nicht gespeichert, nicht exportiert.",
)

# ---------------- Sidebar: Verbindungstest ----------------
st.sidebar.divider()
st.sidebar.subheader("Verbindungstest")
st.sidebar.caption("Lädt zuerst den Modellkatalog (prüft den Key), dann ein kurzer Testaufruf an ein kleines Modell daraus.")
if st.sidebar.button("Verbindung testen", disabled=not nvidia_key):
    client = OpenAI(base_url=NVIDIA_BASE_URL, api_key=nvidia_key, timeout=REQUEST_TIMEOUT_S, max_retries=0)
    try:
        chat_models = fetch_chat_models(client)  # ungecacht - der Test soll den Key gerade neu prüfen
    except Exception as e:
        st.sidebar.error(describe_api_error(e))
    else:
        st.sidebar.success(f"Key gültig - {len(chat_models)} Chat-Modelle verfügbar.")

        with st.sidebar.expander("Katalog-Diagnose"):
            namespace_counts = Counter(m.split("/", 1)[0] for m in chat_models if "/" in m)
            without_namespace = [m for m in chat_models if "/" not in m]
            st.write(
                "**Namespaces:** "
                + ", ".join(f"{ns}: {count}" for ns, count in sorted(namespace_counts.items()))
            )
            if without_namespace:
                st.write(f"**Ohne Namespace ({len(without_namespace)}):**", without_namespace)
            st.write("**Alle Chat-Modell-IDs:**")
            st.code("\n".join(sorted(chat_models)))

        test_model = pick_quick_test_model(chat_models)
        if not test_model:
            st.sidebar.warning("Kein passendes Modell im Katalog gefunden.")
        else:
            sent_params = {"model": test_model, "temperature": 0.2, "max_tokens": 20}
            status_box = st.sidebar.empty()
            text_box = st.sidebar.empty()

            def _on_progress(elapsed_s: float, partial_text: str) -> None:
                status_box.caption(f"wartet seit {elapsed_s:.0f} s ...")
                if partial_text:
                    text_box.markdown(f"*(läuft)* {partial_text}")

            print(f"[{datetime.now(timezone.utc).isoformat()}] START {test_model} (Verbindungstest)", flush=True)
            result = call_chat_streaming(
                client, test_model,
                [{"role": "user", "content": "Antworte in einem Wort: Test erfolgreich."}],
                on_progress=_on_progress,
                temperature=sent_params["temperature"],
                max_tokens=sent_params["max_tokens"],
            )
            status_box.empty()
            text_box.empty()
            print(
                f"[{datetime.now(timezone.utc).isoformat()}] ENDE {test_model} "
                f"dauer={result.duration_s}s status={'OK' if result.ok else 'FEHLER'}",
                flush=True,
            )
            if result.ok:
                st.sidebar.success(f"Testaufruf an {test_model} beantwortet ({result.duration_s} s).")
                st.sidebar.write("**Antwort:**", result.content)
                st.sidebar.write("**Gesendete Parameter:**", sent_params)
                st.sidebar.write(
                    "**usage (roh von NVIDIA Build):**",
                    {"prompt_tokens": result.tokens_in, "completion_tokens": result.tokens_out},
                )
                st.sidebar.write("**finish_reason:**", result.finish_reason)
            else:
                st.sidebar.error(describe_api_error(result.error))

# ---------------- Sidebar: Modelle ----------------
st.sidebar.header("Modelle")
if not nvidia_key:
    st.sidebar.caption("Trage deinen API-Key ein, um den Modellkatalog zu laden.")
    selected = []
else:
    try:
        chat_models = _load_chat_models(nvidia_key)
    except Exception as e:
        st.sidebar.error(describe_api_error(e))
        chat_models = []
    dropdown_options = build_dropdown_options(chat_models)
    choices = [m for m in dropdown_options if m != SEPARATOR]
    st.sidebar.caption(f"{len(choices)} Chat-Modelle geladen - Top 10 zuerst, dann der Rest alphabetisch.")
    selected = st.sidebar.multiselect("Modelle", choices, default=[])

# ---------------- Sidebar: RAG ----------------
st.sidebar.header("RAG (optional)")
st.sidebar.caption("Folgt in Schritt 7 (Embeddings über NVIDIA Build) - aktuell deaktiviert.")
use_rag = False
rag_ready = False
index = None

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

if not nvidia_key:
    st.warning("NVIDIA Build API-Key fehlt (Sidebar).")
if use_rag and not rag_ready:
    st.warning("RAG ist aktiv, aber es ist noch kein Dokument indexiert — der Lauf geht ohne Kontext.")

# ---------------- Ausführung ----------------
if st.button("▶ Benchmark starten", type="primary", disabled=not (selected and prompts and nvidia_key)):
    client = OpenAI(base_url=NVIDIA_BASE_URL, api_key=nvidia_key, timeout=REQUEST_TIMEOUT_S, max_retries=0)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    tasks = [(m, p) for m in selected for p in prompts]
    st.session_state.results = []
    progress = st.progress(0.0)
    status_box = st.empty()
    text_box = st.empty()

    for n, (model_id, prompt) in enumerate(tasks):
        progress.progress(n / len(tasks), text=f"{n + 1}/{len(tasks)} · {model_id} · {prompt['id']}")
        row = {
            "run_id": run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model_id": model_id,
            "prompt_id": prompt["id"],
            "technique": prompt["technique"],
            "injected_context": rag_ready,
            "retrieved_sources": [],
        }

        def _on_progress(elapsed_s: float, partial_text: str, _model=model_id, _pid=prompt["id"]) -> None:
            status_box.caption(f"{_model} · {_pid} - wartet seit {elapsed_s:.0f} s ...")
            if partial_text:
                text_box.markdown(partial_text)

        call_start = time.perf_counter()
        print(f"[{datetime.now(timezone.utc).isoformat()}] START {model_id} prompt={prompt['id']}", flush=True)
        try:
            retrieved = index.retrieve(prompt["text"], 4) if rag_ready else []
            row["retrieved_sources"] = [f"{c.source}#{c.chunk_index}" for c in retrieved]
            result = call_chat_streaming(
                client, model_id,
                [{"role": "user", "content": build_prompt(prompt["text"], retrieved)}],
                on_progress=_on_progress,
            )
            duration = result.duration_s
            if result.ok:
                row.update(ok=True, response=result.content, tokens_in=result.tokens_in, tokens_out=result.tokens_out)
                status = "OK"
            else:
                row.update(ok=False, response=describe_api_error(result.error), tokens_in=None, tokens_out=None)
                status = f"FEHLER: {row['response']}"
        except Exception as e:  # unerwarteter Fehler (z.B. RAG-Retrieval): Zeile bleibt sichtbar, Lauf läuft weiter
            duration = round(time.perf_counter() - call_start, 3)
            row.update(ok=False, response=describe_api_error(e), tokens_in=None, tokens_out=None)
            status = f"FEHLER: {row['response']}"

        print(
            f"[{datetime.now(timezone.utc).isoformat()}] ENDE {model_id} prompt={prompt['id']} "
            f"dauer={duration}s status={status}",
            flush=True,
        )
        row["latency_s"] = duration
        row["cost_usd"] = estimate_cost_usd(model_id, row["tokens_in"], row["tokens_out"])

        st.session_state.results.append(row)
        store.save_results([row])  # sofort sichern - ein später abbrechender Lauf verliert nichts Bisheriges

    status_box.empty()
    text_box.empty()
    progress.progress(1.0, text="Fertig")

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
