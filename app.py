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

import concurrent.futures
import hashlib
import html
import json
import os
import threading
import time
from collections import Counter
from datetime import datetime, timezone

import altair as alt
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

from chat_client import StreamCancelled, call_chat_streaming
from models import (
    SEPARATOR,
    build_dropdown_options,
    fetch_chat_models,
    fetch_chat_models_by_recency,
    fetch_embedding_models,
    pick_quick_test_candidates,
)
from pricing import PRICING_USD_PER_1M_TOKENS
from rag import RagIndex, build_prompt
from storage import RunStore

st.set_page_config(page_title="AiVersus", page_icon="🧪", layout="wide")
store = RunStore()

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
CATALOG_TIMEOUT_S = 30.0  # für models.list() - unabhängig von der Generierungs-Warteschlange
MAX_CONCURRENT_CALLS = 5  # Calls parallel, aber begrenzt - kein Ansturm auf den Freikontingent-Key
AVAILABILITY_PATH = "availability.json"
AVAILABILITY_CHECK_TIMEOUT_S = 20.0  # kurzes Zeitfenster pro Modell - reicht für den Mini-Call
PRICING_JSON_PATH = "pricing.json"
TECHNIQUES = ["Zero-Shot Prompting", "Few-Shot Prompting", "Chain-of-Thought Prompting", "Andere…"]
MODEL_COLOR_PALETTE = [
    "#6CA8FF", "#F59E4C", "#4CC9B0", "#D97757", "#9B8AFB",
    "#E85D75", "#7FD858", "#F2B34A", "#5AC8FA", "#C77DFF",
]


def model_color(model_id: str) -> str:
    """Feste Farbe pro Modell - deterministisch über den Namen, nicht über die Listenposition

    (sonst würde das Entfernen eines Modells die Farben der übrigen verschieben).
    """
    idx = int(hashlib.md5(model_id.encode()).hexdigest(), 16) % len(MODEL_COLOR_PALETTE)
    return MODEL_COLOR_PALETTE[idx]


def load_availability() -> dict:
    """{"checked_at": iso-Zeitstempel oder None, "models": {model_id: {"status", "detail"}}}."""
    if not os.path.exists(AVAILABILITY_PATH):
        return {"checked_at": None, "models": {}}
    try:
        with open(AVAILABILITY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {"checked_at": data.get("checked_at"), "models": data.get("models", {})}
    except (OSError, json.JSONDecodeError):
        return {"checked_at": None, "models": {}}


def save_availability(models: dict) -> dict:
    data = {"checked_at": datetime.now(timezone.utc).isoformat(), "models": models}
    with open(AVAILABILITY_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


def load_pricing_file() -> dict:
    """{model_id: {"input", "output", "source", "updated"}} - nur Preise mit Quelle+Datum, die

    gegen eine offizielle Anbieter-Seite verifiziert wurden (siehe PROTOKOLL.md: für NVIDIA Build
    aktuell keine auffindbare offizielle Preistabelle, daher bewusst leer vorbefüllt).
    """
    if not os.path.exists(PRICING_JSON_PATH):
        return {}
    try:
        with open(PRICING_JSON_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("models", {})
    except (OSError, json.JSONDecodeError):
        return {}


def save_pricing_file(models: dict) -> None:
    with open(PRICING_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump({"models": models}, f, ensure_ascii=False, indent=2)


if "prompts" not in st.session_state:
    st.session_state.prompts = [
        {"id": "p1", "text": "Erkläre RAG in 3 Sätzen.", "technique": "Zero-Shot Prompting"},
        {"id": "p2", "text": "Schreibe eine Python-Funktion für Fibonacci.", "technique": "Few-Shot Prompting"},
    ]
if "results" not in st.session_state:
    st.session_state.results = []
if "unavailable_models" not in st.session_state:
    st.session_state.unavailable_models = set()
if "selected_models" not in st.session_state:
    st.session_state.selected_models = []
if "model_prices" not in st.session_state:
    st.session_state.model_prices = {}
if "last_successful_test_model" not in st.session_state:
    st.session_state.last_successful_test_model = None
if "run" not in st.session_state:
    st.session_state.run = None
if "last_run_message" not in st.session_state:
    st.session_state.last_run_message = None
if "availability_data" not in st.session_state:
    st.session_state.availability_data = load_availability()
if "availability_run" not in st.session_state:
    st.session_state.availability_run = None
if "pricing_data" not in st.session_state:
    st.session_state.pricing_data = load_pricing_file()


def _original_message(e: Exception) -> str:
    """Die Original-Fehlermeldung aus dem Response-Body von NVIDIA Build, falls vorhanden.

    Kann Account-/Function-IDs enthalten - deshalb nur fürs Terminal-Log, nie für die UI.
    """
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
        if body.get("message"):
            return str(body["message"])
    return str(e)


def log_error_detail(context: str, e: Exception) -> None:
    """Volle Fehlermeldung (kann Account-/Function-IDs enthalten) nur ins Terminal, nie in die UI."""
    print(
        f"[{datetime.now(timezone.utc).isoformat()}] FEHLERDETAIL {context}: "
        f"{type(e).__name__}: {_original_message(e)}",
        flush=True,
    )


def describe_api_error(e: Exception) -> str:
    """Kurze, deutsche Fehlermeldung ohne Account-/Function-IDs - Details gehen ins Terminal-Log."""
    if isinstance(e, StreamCancelled):
        return "Abgebrochen (Stop-Button)."
    if isinstance(e, TimeoutError):  # unser eigener Stream-Timeout (chat_client.py), kein Server-Fehler
        return f"Zeitüberschreitung: {e}"
    if isinstance(e, AuthenticationError):
        return "API-Key ungültig oder abgelehnt (401)."
    if isinstance(e, RateLimitError):
        return "Rate-Limit bei NVIDIA Build erreicht (429) - kurz warten und erneut versuchen."
    if isinstance(e, NotFoundError):
        return "Modell nicht gefunden oder für diesen Account nicht verfügbar (404)."
    if isinstance(e, APIStatusError) and e.status_code == 410:
        return "Modell nicht mehr verfügbar (410) - bitte ein anderes Modell wählen."
    if isinstance(e, APIStatusError):
        return f"NVIDIA Build hat den Aufruf abgelehnt (Status {e.status_code})."
    if isinstance(e, APITimeoutError):
        return "Zeitüberschreitung auf Transport-Ebene - keine Antwort von NVIDIA Build erhalten."
    if isinstance(e, APIConnectionError):
        return "Verbindung zu NVIDIA Build fehlgeschlagen (Netzwerk)."
    if isinstance(e, APIError):
        return "Verbindung zu NVIDIA Build fehlgeschlagen."
    return "Unbekannter Fehler beim API-Aufruf."


def _is_definitively_unavailable(e: Exception) -> bool:
    """404/410 sind eine definitive Absage (Modell existiert/ist für den Account nicht

    verfügbar) - ein Timeout dagegen heißt nur "langsam/unbekannt", nicht "nicht verfügbar".
    """
    if isinstance(e, NotFoundError):
        return True
    return isinstance(e, APIStatusError) and e.status_code == 410


def _classify_availability(result) -> str:
    """available / unavailable (404/410 - definitiv) / slow (Timeout oder sonstiger Fehler -

    unbekannt, nicht bestätigt tot).
    """
    if result.ok:
        return "available"
    if _is_definitively_unavailable(result.error):
        return "unavailable"
    return "slow"


def _check_one_model_task(client, model_id: str):
    """Läuft in einem Worker-Thread - Mini-Call (max_tokens=1), kurzer Timeout."""
    result = call_chat_streaming(
        client, model_id, [{"role": "user", "content": "Hi"}],
        first_token_timeout_s=AVAILABILITY_CHECK_TIMEOUT_S,
        inter_token_timeout_s=AVAILABILITY_CHECK_TIMEOUT_S,
        max_tokens=1,
    )
    status = _classify_availability(result)
    detail = None if result.ok else describe_api_error(result.error)
    return model_id, status, detail


@st.cache_resource
def get_index(api_key: str, embed_model: str) -> RagIndex:
    return RagIndex(api_key=api_key, base_url=NVIDIA_BASE_URL, embed_model=embed_model)


@st.cache_data(ttl=3600, show_spinner="Modellkatalog wird geladen ...")
def _load_chat_models(api_key: str) -> list:
    client = OpenAI(base_url=NVIDIA_BASE_URL, api_key=api_key, timeout=CATALOG_TIMEOUT_S, max_retries=0)
    return fetch_chat_models(client)


@st.cache_data(ttl=3600, show_spinner=False)
def _load_embedding_models(api_key: str) -> list:
    client = OpenAI(base_url=NVIDIA_BASE_URL, api_key=api_key, timeout=CATALOG_TIMEOUT_S, max_retries=0)
    return fetch_embedding_models(client)


# ---------------- Sidebar: API-Key ----------------
st.sidebar.header("NVIDIA Build API-Key")
nvidia_key = st.sidebar.text_input(
    "API-Key",
    type="password",
    placeholder="nvapi-...",
    key="nvidia_api_key",
    help="Nur für diese Sitzung im Speicher - wird nicht geloggt, nicht gespeichert, nicht exportiert.",
)

# ---------------- Sidebar: Timeouts ----------------
st.sidebar.divider()
st.sidebar.subheader("Timeouts")
st.sidebar.caption("NVIDIA Build (Freikontingent) kann vor dem ersten Token mehrere Minuten Warteschlange haben.")
first_token_timeout_s = st.sidebar.number_input(
    "Warten auf erstes Token (s)", min_value=10, max_value=600, value=300, step=10,
)
inter_token_timeout_s = st.sidebar.number_input(
    "Danach: kein weiteres Token (s)", min_value=5, max_value=300, value=60, step=5,
)
chat_client_timeout_s = first_token_timeout_s + 30  # Transport-Timeout muss größer sein als unser eigenes

# ---------------- Sidebar: Verbindungstest ----------------
st.sidebar.divider()
st.sidebar.subheader("Verbindungstest")
st.sidebar.caption("Lädt zuerst den Modellkatalog (prüft den Key), dann ein kurzer Testaufruf an ein kleines Modell daraus.")
if st.sidebar.button("Verbindung testen", disabled=not nvidia_key):
    client = OpenAI(base_url=NVIDIA_BASE_URL, api_key=nvidia_key, timeout=chat_client_timeout_s, max_retries=0)
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

        chat_models_by_recency = fetch_chat_models_by_recency(client)
        preferred = [st.session_state.last_successful_test_model] if st.session_state.last_successful_test_model else []
        candidates = pick_quick_test_candidates(chat_models_by_recency, limit=5, preferred=preferred)
        if not candidates:
            st.sidebar.warning("Kein passendes Modell im Katalog gefunden.")
        else:
            status_box = st.sidebar.empty()
            text_box = st.sidebar.empty()
            tried, result, test_model = [], None, None

            def _on_progress(elapsed_s: float, partial_text: str, got_first_token: bool) -> None:
                if not got_first_token:
                    status_box.caption(f"in der NVIDIA-Warteschlange - wartet seit {elapsed_s:.0f} s ...")
                else:
                    status_box.caption(f"generiert ... ({elapsed_s:.0f} s)")
                if partial_text:
                    text_box.markdown(f"*(läuft)* {partial_text}")

            sent_params = {"temperature": 0.2, "max_tokens": 20}
            for candidate in candidates:
                tried.append(candidate)
                print(f"[{datetime.now(timezone.utc).isoformat()}] START {candidate} (Verbindungstest)", flush=True)
                result = call_chat_streaming(
                    client, candidate,
                    [{"role": "user", "content": "Antworte in einem Wort: Test erfolgreich."}],
                    on_progress=_on_progress,
                    first_token_timeout_s=first_token_timeout_s,
                    inter_token_timeout_s=inter_token_timeout_s,
                    temperature=sent_params["temperature"],
                    max_tokens=sent_params["max_tokens"],
                )
                print(
                    f"[{datetime.now(timezone.utc).isoformat()}] ENDE {candidate} "
                    f"dauer={result.duration_s}s status={'OK' if result.ok else 'FEHLER'}",
                    flush=True,
                )
                if not result.ok:
                    log_error_detail(f"Verbindungstest {candidate}", result.error)
                test_model = candidate
                if result.ok or not _is_definitively_unavailable(result.error):
                    break  # Erfolg, oder ein Fehler, der auch bei anderen Modellen käme (z.B. 401)
                st.sidebar.caption(f"{candidate}: für diesen Account nicht verfügbar - nächstes Modell ...")

            status_box.empty()
            text_box.empty()
            if result.ok:
                st.session_state.last_successful_test_model = test_model
                st.sidebar.success(f"Testaufruf an {test_model} beantwortet ({result.duration_s} s).")
                if len(tried) > 1:
                    st.sidebar.caption(f"Nicht verfügbar probiert: {', '.join(tried[:-1])}")
                st.sidebar.write("**Antwort:**", result.content)
                st.sidebar.write("**Gesendete Parameter:**", {"model": test_model, **sent_params})
                st.sidebar.write(
                    "**usage (roh von NVIDIA Build):**",
                    {
                        "prompt_tokens": result.tokens_in,
                        "completion_tokens": result.tokens_out,
                        "reasoning_tokens": result.reasoning_tokens,
                    },
                )
                st.sidebar.write("**TTFT / Generierungszeit:**", f"{result.ttft_s} s / {result.generation_s} s")
                st.sidebar.write("**finish_reason:**", result.finish_reason)
                if result.reasoning:
                    with st.sidebar.expander("Reasoning"):
                        st.write(result.reasoning)
            else:
                st.sidebar.error(describe_api_error(result.error))

# ---------------- Sidebar: Verfügbarkeit ----------------
st.sidebar.divider()
st.sidebar.subheader("Verfügbarkeit")
availability_run_active = st.session_state.availability_run is not None
last_checked = st.session_state.availability_data.get("checked_at")
if last_checked:
    st.sidebar.caption(f"Letzte Prüfung: {last_checked}")
else:
    st.sidebar.caption("Noch nicht geprüft.")

if st.sidebar.button(
    "Verfügbarkeit prüfen", disabled=availability_run_active or not nvidia_key,
    help="Mini-Call (max_tokens=1) an jedes Katalog-Modell, parallel, kurzer Timeout.",
):
    client = OpenAI(base_url=NVIDIA_BASE_URL, api_key=nvidia_key, timeout=AVAILABILITY_CHECK_TIMEOUT_S + 10, max_retries=0)
    try:
        all_chat_models = fetch_chat_models(client)
    except Exception as e:
        st.sidebar.error(describe_api_error(e))
        all_chat_models = []
    if all_chat_models:
        avail_executor = concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENT_CALLS)
        avail_futures = {avail_executor.submit(_check_one_model_task, client, m): m for m in all_chat_models}
        st.session_state.availability_run = {
            "executor": avail_executor, "futures": avail_futures, "pending": set(avail_futures),
            "total": len(all_chat_models), "done_count": 0, "results": {},
        }
        st.rerun()

if st.session_state.availability_run is not None:
    avail_run = st.session_state.availability_run
    for future in [f for f in avail_run["pending"] if f.done()]:
        avail_run["pending"].discard(future)
        model_id = avail_run["futures"][future]
        try:
            _, status, detail = future.result()
        except Exception as e:
            status, detail = "slow", str(e)
        avail_run["results"][model_id] = {"status": status, "detail": detail}
        avail_run["done_count"] += 1

    st.sidebar.progress(
        avail_run["done_count"] / avail_run["total"], text=f"{avail_run['done_count']}/{avail_run['total']} geprüft",
    )
    if not avail_run["pending"]:
        avail_run["executor"].shutdown(wait=False)
        st.session_state.availability_data = save_availability(avail_run["results"])
        n_avail = sum(1 for v in avail_run["results"].values() if v["status"] == "available")
        n_unavail = sum(1 for v in avail_run["results"].values() if v["status"] == "unavailable")
        n_slow = sum(1 for v in avail_run["results"].values() if v["status"] == "slow")
        print(
            f"[{datetime.now(timezone.utc).isoformat()}] VERFÜGBARKEITSPRÜFUNG fertig - "
            f"verfügbar={n_avail} nicht_verfügbar={n_unavail} langsam/unbekannt={n_slow}",
            flush=True,
        )
        st.session_state.availability_run = None
        st.sidebar.success(f"{n_avail} verfügbar, {n_unavail} nicht verfügbar, {n_slow} langsam/unbekannt.")
        st.rerun()
    else:
        time.sleep(0.5)
        st.rerun()

# ---------------- Sidebar: LLM Pricing ----------------
st.sidebar.divider()


@st.dialog("LLM Pricing", width="large")
def _pricing_dialog() -> None:
    st.caption(
        "Preise nur eintragen, wenn auf einer offiziellen Anbieter-Seite verifiziert - mit Quelle "
        "und Stand-Datum. Unbekannt bleibt leer (wird als '–' angezeigt, nicht als 0)."
    )
    models_dict = st.session_state.pricing_data
    rows = [
        {"Modell": m, "Input $/1M": v.get("input"), "Output $/1M": v.get("output"),
         "Quelle": v.get("source") or "", "Stand": v.get("updated") or ""}
        for m, v in sorted(models_dict.items())
    ]
    pricing_df = pd.DataFrame(rows, columns=["Modell", "Input $/1M", "Output $/1M", "Quelle", "Stand"])
    edited = st.data_editor(
        pricing_df, num_rows="dynamic", use_container_width=True, key="pricing_editor",
        column_config={
            "Input $/1M": st.column_config.NumberColumn(format="%.4f"),
            "Output $/1M": st.column_config.NumberColumn(format="%.4f"),
            "Stand": st.column_config.TextColumn(help="z.B. 2026-11-02"),
        },
    )
    col_save, col_close = st.columns(2)
    if col_save.button("Speichern", type="primary", use_container_width=True):
        new_models = {}
        for _, r in edited.iterrows():
            model_name = str(r["Modell"] or "").strip()
            if not model_name:
                continue
            new_models[model_name] = {
                "input": float(r["Input $/1M"]) if pd.notna(r["Input $/1M"]) else None,
                "output": float(r["Output $/1M"]) if pd.notna(r["Output $/1M"]) else None,
                "source": str(r["Quelle"]).strip() or None,
                "updated": str(r["Stand"]).strip() or None,
            }
        st.session_state.pricing_data = new_models
        save_pricing_file(new_models)
        st.rerun()
    if col_close.button("Schließen", use_container_width=True):
        st.rerun()


if st.sidebar.button("LLM Pricing"):
    _pricing_dialog()

# ---------------- Sidebar: RAG ----------------
st.sidebar.header("RAG (optional)")
use_rag = st.sidebar.checkbox("RAG-Kontext verwenden", value=False)
index = None
rag_ready = False
top_k = 4

if not use_rag:
    st.sidebar.caption("Deaktiviert - Prompts gehen ohne eigene Dokumente an die Modelle.")
elif not nvidia_key:
    st.sidebar.caption("RAG braucht den NVIDIA Build API-Key (Embeddings).")
else:
    try:
        embedding_models = _load_embedding_models(nvidia_key)
    except Exception as e:
        st.sidebar.error(describe_api_error(e))
        embedding_models = []
    if not embedding_models:
        st.sidebar.warning("Kein Embedding-Modell im Katalog gefunden.")
    else:
        embed_model = st.sidebar.selectbox("Embedding-Modell", embedding_models, key="embed_model_pick")
        index = get_index(nvidia_key, embed_model)
        top_k = st.sidebar.slider("Top-K Chunks", 1, 10, 4)
        uploads = st.sidebar.file_uploader(
            "Dokumente (PDF, TXT, MD)", type=["pdf", "txt", "md"], accept_multiple_files=True,
        )
        col_build, col_clear = st.sidebar.columns(2)
        if col_build.button("Index aufbauen", disabled=not uploads, use_container_width=True):
            with st.sidebar, st.spinner("Chunking + Embedding ..."):
                for f in uploads:
                    try:
                        index.add_document(f.name, f.getvalue())
                    except Exception as e:
                        st.sidebar.error(f"{f.name}: {describe_api_error(e)}")
        if col_clear.button("Index leeren", use_container_width=True):
            index.clear()

        for name, n in index.sources().items():
            st.sidebar.caption(f"· {name} ({n} Chunks)")

        rag_ready = index.document_count() > 0
        if not rag_ready:
            st.sidebar.caption("Noch kein Dokument indexiert - der Lauf geht ohne Kontext.")

# ---------------- Modelle ----------------
st.title("AiVersus")
st.subheader("Modelle")

if not nvidia_key:
    st.caption("Trage deinen API-Key ein (Sidebar), um den Modellkatalog zu laden.")
    chat_models = []
else:
    try:
        chat_models = _load_chat_models(nvidia_key)
    except Exception as e:
        st.error(describe_api_error(e))
        chat_models = []

availability_models = st.session_state.availability_data.get("models", {})
hard_unavailable = {m for m, info in availability_models.items() if info.get("status") == "unavailable"}
slow_models = {m for m, info in availability_models.items() if info.get("status") == "slow"}

dropdown_options = build_dropdown_options(chat_models)
available_choices = [
    m for m in dropdown_options
    if m != SEPARATOR and m not in st.session_state.unavailable_models and m not in hard_unavailable
]
addable_choices = [m for m in available_choices if m not in st.session_state.selected_models]

hidden = st.session_state.unavailable_models | hard_unavailable
if hidden:
    st.caption(f"Nicht verfügbar (ausgeblendet): {', '.join(sorted(hidden))}")

col_pick, col_add = st.columns([5, 1])
model_pick = col_pick.selectbox(
    "Modell hinzufügen", addable_choices, index=None, placeholder="Modell suchen ...",
    key="model_picker", label_visibility="collapsed",
    format_func=lambda m: f"{m} (langsam/unbekannt)" if m in slow_models else m,
)
if col_add.button("Hinzufügen", disabled=not model_pick, use_container_width=True):
    st.session_state.selected_models.append(model_pick)
    priced = st.session_state.pricing_data.get(model_pick)
    if priced and priced.get("input") is not None and priced.get("output") is not None:
        st.session_state.model_prices[model_pick] = {"input": priced["input"], "output": priced["output"]}
    else:
        legacy = PRICING_USD_PER_1M_TOKENS.get(model_pick)  # alte OpenAI/Gemini-IDs, meist kein Treffer
        st.session_state.model_prices[model_pick] = (
            {"input": legacy[0], "output": legacy[1]} if legacy else {"input": 0.0, "output": 0.0}
        )
    st.rerun()

if st.session_state.selected_models:
    if len(st.session_state.selected_models) >= 5:
        st.caption(
            "Ab 5 Modellen kann NVIDIA Build (Freikontingent) insgesamt länger dauern "
            "(parallel, aber begrenzt) - kein hartes Limit, nur ein Hinweis."
        )
    header_dot, header_name, header_in, header_out, header_del = st.columns([0.4, 3, 1.3, 1.3, 0.5])
    header_name.caption("Modell")
    header_in.caption("Input $/1M")
    header_out.caption("Output $/1M")

    to_remove = None
    for model_id in st.session_state.selected_models:
        col_dot, col_name, col_in, col_out, col_del = st.columns([0.4, 3, 1.3, 1.3, 0.5])
        col_dot.markdown(
            f"<span style='color:{model_color(model_id)}; font-size:22px;'>●</span>", unsafe_allow_html=True,
        )
        col_name.write(model_id)
        price = st.session_state.model_prices.setdefault(model_id, {"input": 0.0, "output": 0.0})
        price["input"] = col_in.number_input(
            "Input $/1M", value=price["input"], step=0.01, format="%.4f",
            key=f"price_in_{model_id}", label_visibility="collapsed",
        )
        price["output"] = col_out.number_input(
            "Output $/1M", value=price["output"], step=0.01, format="%.4f",
            key=f"price_out_{model_id}", label_visibility="collapsed",
        )
        if col_del.button("✕", key=f"del_model_{model_id}"):
            to_remove = model_id
    if to_remove is not None:
        st.session_state.selected_models.remove(to_remove)
        st.session_state.model_prices.pop(to_remove, None)
        st.rerun()
else:
    st.caption("Noch keine Modelle hinzugefügt.")

selected = st.session_state.selected_models

# ---------------- Prompt-Suite ----------------
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

# ---------------- Parameter (für alle Modelle gleich) ----------------
st.subheader("Parameter")
col_temp, col_top_p, col_max_tokens = st.columns(3)
temperature = col_temp.number_input("temperature", min_value=0.0, max_value=2.0, value=0.7, step=0.1)
top_p = col_top_p.number_input("top_p", min_value=0.0, max_value=1.0, value=1.0, step=0.05)
max_tokens = col_max_tokens.number_input("max_tokens", min_value=1, max_value=8192, value=1024, step=1)

system_prompt = st.text_area(
    "System-Prompt (optional)", value="", placeholder="z.B. Antworte knapp und auf Deutsch.",
)

col_seed_on, col_seed_val = st.columns([1, 2])
use_seed = col_seed_on.checkbox("Seed fixieren", value=False)
seed = col_seed_val.number_input(
    "seed", min_value=0, max_value=2_147_483_647, value=42, step=1, disabled=not use_seed,
)
seed_to_send = seed if use_seed else None

# API-Parameter (an NVIDIA Build gesendet) getrennt von der Anzeige/Speicherung (nie null bei
# temperature/top_p/max_tokens - die haben immer einen konkreten Wert, nur seed/System-Prompt
# können echt "nicht gesetzt" sein, und das wird auch so angezeigt statt als leeres Feld).
api_params = {"temperature": temperature, "top_p": top_p, "max_tokens": max_tokens}
if seed_to_send is not None:
    api_params["seed"] = seed_to_send
sent_params_record = {
    "temperature": temperature, "top_p": top_p, "max_tokens": max_tokens,
    "seed": seed_to_send, "system_prompt": system_prompt.strip() or None,
}


def _run_one_task(client, model_id, prompt, task_progress, progress_lock, cancel_event, retrieved_chunks):
    """Läuft in einem Worker-Thread - rührt nie st.session_state oder st.* an, nur den

    geteilten task_progress-Dict (für die Live-Anzeige im Hauptthread). `retrieved_chunks` wird
    einmal pro Prompt im Hauptthread vorab geholt (sonst würde jedes Modell dieselbe Anfrage
    redundant selbst embedden).
    """
    key = (model_id, prompt["id"])
    call_start = time.perf_counter()

    def _on_progress(elapsed_s: float, partial_text: str, got_first_token: bool) -> None:
        with progress_lock:
            task_progress[key] = {"elapsed": elapsed_s, "first_token": got_first_token, "done": False}

    print(f"[{datetime.now(timezone.utc).isoformat()}] START {model_id} prompt={prompt['id']}", flush=True)
    try:
        messages = []
        if sent_params_record["system_prompt"]:
            messages.append({"role": "system", "content": sent_params_record["system_prompt"]})
        messages.append({"role": "user", "content": build_prompt(prompt["text"], retrieved_chunks)})
        result = call_chat_streaming(
            client, model_id, messages,
            on_progress=_on_progress,
            first_token_timeout_s=first_token_timeout_s,
            inter_token_timeout_s=inter_token_timeout_s,
            cancel_event=cancel_event,
            **api_params,
        )
        exc = None
    except Exception as e:  # unerwarteter Fehler außerhalb des API-Aufrufs selbst
        result, exc = None, e
    with progress_lock:
        task_progress[key] = {
            "elapsed": result.duration_s if result else round(time.perf_counter() - call_start, 3),
            "first_token": True, "done": True,
        }
    return result, exc, call_start, retrieved_chunks


def _cost_usd(model_id: str, tokens_in, tokens_out):
    """Kosten nach den in der Modell-Liste eingetragenen Preisen - gilt nur für diesen Lauf.

    None (nicht 0.0), wenn kein Preis eingetragen ist - unbekannt ist nicht dasselbe wie
    kostenlos. Heuristik: 0.0/0.0 (der Vorgabewert ohne Treffer in pricing.py) gilt als
    "kein Preis eingetragen"; sobald eines der beiden Felder > 0 ist, gilt der Preis als bekannt.
    """
    price = st.session_state.model_prices.get(model_id, {"input": 0.0, "output": 0.0})
    if price["input"] == 0.0 and price["output"] == 0.0:
        return None
    if tokens_in is None or tokens_out is None:
        return None
    return round((tokens_in * price["input"] + tokens_out * price["output"]) / 1_000_000, 6)


def _classify_outcome(result, exc) -> str:
    """ok / timeout / abgebrochen / fehler - für die Live-Statuszeile, nicht nur "fertig"."""
    error = exc if exc is not None else (None if result is None or result.ok else result.error)
    if error is None:
        return "ok"
    if isinstance(error, StreamCancelled):
        return "abgebrochen"
    if isinstance(error, TimeoutError):
        return "timeout"
    return "fehler"


def _actual_sent_params(result) -> dict:
    """Was tatsächlich gesendet wurde - nach einem 400-Retry kann das von der Vorgabe abweichen."""
    if result is None:  # Fehler vor dem ersten Versuch (z.B. RAG-Retrieval) - nur die Absicht bekannt
        return {**sent_params_record, "dropped_param": None}
    return {
        "temperature": result.used_params.get("temperature"),
        "top_p": result.used_params.get("top_p"),
        "max_tokens": result.used_params.get("max_tokens"),
        "seed": result.used_params.get("seed"),
        "system_prompt": sent_params_record["system_prompt"],
        "dropped_param": result.dropped_param,
    }


def _build_result_row(
    run_id: str, model_id: str, prompt: dict, result, exc, call_start: float, retrieved_chunks=(),
) -> dict:
    row = {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model_id": model_id,
        "prompt_id": prompt["id"],
        "technique": prompt["technique"],
        "injected_context": bool(retrieved_chunks),
        "retrieved_sources": [f"{c.source}#{c.chunk_index}" for c in retrieved_chunks],
        "sent_params": _actual_sent_params(result),
        "stars": None,
        "is_best": False,
    }
    if exc is not None:
        duration = round(time.perf_counter() - call_start, 3)
        log_error_detail(f"Benchmark {model_id}/{prompt['id']}", exc)
        row.update(ok=False, response=describe_api_error(exc), reasoning="",
                   tokens_in=None, tokens_out=None, reasoning_tokens=None, ttft_s=None, generation_s=None)
    elif result.ok:
        duration = result.duration_s
        row.update(
            ok=True, response=result.content, reasoning=result.reasoning,
            tokens_in=result.tokens_in, tokens_out=result.tokens_out, reasoning_tokens=result.reasoning_tokens,
            ttft_s=result.ttft_s, generation_s=result.generation_s,
        )
    else:
        duration = result.duration_s
        log_error_detail(f"Benchmark {model_id}/{prompt['id']}", result.error)
        if _is_definitively_unavailable(result.error):
            st.session_state.unavailable_models.add(model_id)
            response_text = "Im Katalog, aber für diesen Account nicht verfügbar."
        else:
            response_text = describe_api_error(result.error)
        row.update(ok=False, response=response_text, reasoning="", tokens_in=None, tokens_out=None,
                   reasoning_tokens=None, ttft_s=result.ttft_s, generation_s=result.generation_s)

    status = "OK" if row["ok"] else f"FEHLER: {row['response']}"
    dropped = row["sent_params"].get("dropped_param")
    if dropped:
        status += f" (nach 400 ohne Parameter '{dropped}' wiederholt)"
    print(
        f"[{datetime.now(timezone.utc).isoformat()}] ENDE {model_id} prompt={prompt['id']} "
        f"dauer={duration}s status={status}",
        flush=True,
    )
    row["latency_s"] = duration
    row["tokens_per_s"] = (
        round(row["tokens_out"] / row["generation_s"], 1)
        if row.get("tokens_out") and row.get("generation_s") else None
    )
    row["cost_usd"] = _cost_usd(model_id, row["tokens_in"], row["tokens_out"])
    return row


# ---------------- Ausführung ----------------
# Läuft über mehrere Streamlit-Reruns statt einer einzigen blockierenden Schleife, sonst könnte
# der Stop-Button nie dazwischenfunken: Start legt Executor/Futures in st.session_state.run ab,
# jeder Rerun schöpft fertige Futures ab und stößt (falls noch was offen ist) den nächsten Rerun an.
run_active = st.session_state.run is not None
col_start, col_stop = st.columns([4, 1])
start_clicked = col_start.button(
    "▶ Benchmark starten", type="primary",
    disabled=run_active or not (selected and prompts and nvidia_key),
)
stop_clicked = col_stop.button("■ Stop", disabled=not run_active)

if st.session_state.last_run_message:
    level, text = st.session_state.last_run_message
    getattr(st, level)(text)

if start_clicked and not run_active:
    st.session_state.last_run_message = None
    client = OpenAI(base_url=NVIDIA_BASE_URL, api_key=nvidia_key, timeout=chat_client_timeout_s, max_retries=0)
    tasks = [(m, p) for m in selected for p in prompts]
    st.session_state.results = []
    cancel_event = threading.Event()
    task_progress: dict = {}
    progress_lock = threading.Lock()

    # Einmal pro Prompt abrufen, nicht pro Modell - sonst würde jedes Modell dieselbe Anfrage
    # redundant selbst embedden (gleicher Prompt, unabhängig vom Modell dieselben Chunks).
    retrieval_by_prompt = {}
    if rag_ready:
        with st.spinner("RAG-Kontext wird abgerufen ..."):
            for p in prompts:
                try:
                    retrieval_by_prompt[p["id"]] = index.retrieve(p["text"], top_k)
                except Exception as e:
                    log_error_detail(f"RAG-Retrieval {p['id']}", e)
                    retrieval_by_prompt[p["id"]] = []

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=min(MAX_CONCURRENT_CALLS, len(tasks)))
    futures = {
        executor.submit(
            _run_one_task, client, model_id, prompt, task_progress, progress_lock, cancel_event,
            retrieval_by_prompt.get(prompt["id"], []),
        ): (model_id, prompt)
        for model_id, prompt in tasks
    }
    st.session_state.run = {
        "run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "executor": executor, "futures": futures, "pending": set(futures), "cancel_event": cancel_event,
        "task_progress": task_progress, "progress_lock": progress_lock,
        "total": len(tasks), "done_count": 0, "cancelled": False,
    }
    st.rerun()

if stop_clicked and run_active:
    run = st.session_state.run
    run["cancel_event"].set()
    run["cancelled"] = True
    affected = [f"{m}/{p['id']}" for f, (m, p) in run["futures"].items() if f in run["pending"]]
    print(
        f"[{datetime.now(timezone.utc).isoformat()}] ABBRUCH angefordert - "
        f"betroffene Calls: {', '.join(affected) if affected else '(keine mehr offen)'}",
        flush=True,
    )
    run["executor"].shutdown(wait=False, cancel_futures=True)
    st.rerun()

if st.session_state.run is not None:
    run = st.session_state.run

    for future in [f for f in run["pending"] if f.done()]:
        run["pending"].discard(future)
        model_id, prompt = run["futures"][future]
        try:
            result, exc, call_start, retrieved_chunks = future.result()
        except concurrent.futures.CancelledError:
            result, exc, call_start = None, StreamCancelled("Vor dem Start abgebrochen."), time.perf_counter()
            retrieved_chunks = []
        row = _build_result_row(run["run_id"], model_id, prompt, result, exc, call_start, retrieved_chunks)
        with run["progress_lock"]:
            run["task_progress"][(model_id, prompt["id"])] = {
                "elapsed": row["latency_s"] or 0.0, "first_token": True, "done": True,
                "status": _classify_outcome(result, exc), "detail": row["response"],
            }
        st.session_state.results.append(row)
        store.save_results([row])  # sofort sichern - ein später abbrechender Lauf verliert nichts Bisheriges
        run["done_count"] += 1

    st.progress(run["done_count"] / run["total"], text=f"{run['done_count']}/{run['total']} abgeschlossen")
    STATUS_LABELS = {"ok": "fertig", "fehler": "Fehler", "timeout": "Timeout", "abgebrochen": "abgebrochen"}
    lines = []
    with run["progress_lock"]:
        for model_id, prompt in run["futures"].values():
            info = run["task_progress"].get((model_id, prompt["id"]))
            if info is None:
                lines.append(f"- {model_id} · {prompt['id']}: wartet auf freien Slot ...")
            elif info["done"]:
                label = STATUS_LABELS.get(info.get("status", "ok"), "fertig")
                detail = f" - {info['detail']}" if info.get("status") not in (None, "ok") and info.get("detail") else ""
                lines.append(f"- {model_id} · {prompt['id']}: {label} ({info['elapsed']:.1f} s){detail}")
            elif not info["first_token"]:
                lines.append(f"- {model_id} · {prompt['id']}: in der NVIDIA-Warteschlange - wartet seit {info['elapsed']:.0f} s")
            else:
                lines.append(f"- {model_id} · {prompt['id']}: generiert ... ({info['elapsed']:.0f} s)")
    st.markdown("\n".join(lines))

    if not run["pending"]:
        run["executor"].shutdown(wait=False)
        if run["cancelled"]:
            print(
                f"[{datetime.now(timezone.utc).isoformat()}] ABBRUCH abgeschlossen - "
                f"{run['done_count']}/{run['total']} Calls fertig.",
                flush=True,
            )
            st.session_state.last_run_message = (
                "warning", f"Lauf abgebrochen – {run['done_count']} von {run['total']} Calls fertig.",
            )
        else:
            st.session_state.last_run_message = ("success", f"Fertig - {run['done_count']}/{run['total']} Calls.")
        st.session_state.run = None
        st.rerun()  # Start/Stop-Button-Zustand sofort neu zeichnen, nicht erst beim nächsten Klick
    else:
        time.sleep(0.4)
        st.rerun()

def _fmt(value, suffix: str = "", digits: int = 2) -> str:
    if value is None:
        return "–"
    return f"{value:.{digits}f}{suffix}" if isinstance(value, float) else f"{value}{suffix}"


def _fmt_tokens(value) -> str:
    return "–" if value is None else str(value)


def _fmt_cost(value) -> str:
    return "–" if value is None else f"${value:.6f}"


def _render_result_card(row: dict) -> str:
    # Bewusst EIN zusammenhängender String ohne eingerücktes HTML über mehrere Zeilen: st.markdown
    # interpretiert eine Zeile mit >= 4 Leerzeichen Einzug als Markdown-Codeblock und reißt dann
    # auch die nächste(n) Karte(n) mit in den Codeblock (Live-Test-Bug, siehe PROTOKOLL.md).
    color = model_color(row["model_id"])
    sp = row.get("sent_params") or {}
    params_line = (
        f"temperature={sp.get('temperature')}, top_p={sp.get('top_p')}, max_tokens={sp.get('max_tokens')}, "
        f"seed={sp.get('seed') if sp.get('seed') is not None else 'nicht gesetzt'}"
    )
    if sp.get("dropped_param"):
        params_line += f" (ohne '{sp['dropped_param']}', von NVIDIA Build abgelehnt)"
    metrics = (
        f"TTFT {_fmt(row.get('ttft_s'), ' s')} · Gen. {_fmt(row.get('generation_s'), ' s')} · "
        f"Tokens {_fmt_tokens(row.get('tokens_in'))}/{_fmt_tokens(row.get('tokens_out'))}"
        + (f" (davon {row['reasoning_tokens']} Reasoning)" if row.get("reasoning_tokens") else "")
        + f" · {_fmt(row.get('tokens_per_s'), ' Tok/s', 1)} · {_fmt_cost(row.get('cost_usd'))}"
    )
    status_html = "" if row["ok"] else "<div style='color:#E85D75;font-weight:600;margin-bottom:6px;'>Fehler</div>"
    if row.get("is_best"):
        status_html += "<div style='color:#F2B34A;font-weight:600;margin-bottom:6px;'>★ Beste Antwort</div>"
    if row.get("stars"):
        status_html += f"<div style='color:#F2B34A;margin-bottom:6px;'>{'★' * row['stars']}{'☆' * (5 - row['stars'])}</div>"
    reasoning_html = ""
    if row.get("reasoning"):
        reasoning_html = (
            "<details style='margin-top:8px;'><summary style='cursor:pointer;color:#9AA3AE;'>Reasoning</summary>"
            f"<div style='white-space:pre-wrap;margin-top:6px;font-size:13px;'>{html.escape(row['reasoning'])}</div>"
            "</details>"
        )
    rag_html = ""
    if row.get("injected_context"):
        sources_list = "".join(f"<li>{html.escape(s)}</li>" for s in row.get("retrieved_sources", []))
        rag_html = (
            "<details style='margin-top:8px;'><summary style='cursor:pointer;color:#9AA3AE;'>"
            f"RAG-Kontext ({len(row.get('retrieved_sources', []))} Chunks)</summary>"
            f"<ul style='margin:6px 0 0; padding-left:18px; font-size:12px;'>{sources_list}</ul></details>"
        )
    return (
        "<div style=\"min-width:320px;max-width:380px;flex:0 0 auto;background:#14171C;"
        "border:1px solid #252A31;border-radius:12px;padding:16px;color:#E7E9EC;\">"
        "<div style=\"display:flex;align-items:center;gap:8px;margin-bottom:8px;\">"
        f"<span style=\"color:{color};font-size:18px;\">●</span>"
        f"<strong>{html.escape(row['model_id'])}</strong>"
        "</div>"
        f"{status_html}"
        f"<div style=\"font-size:13px;color:#9AA3AE;margin-bottom:8px;\">{metrics}</div>"
        f"<div style=\"white-space:pre-wrap;font-size:14px;\">{html.escape(row['response'] or '')}</div>"
        f"{reasoning_html}"
        f"{rag_html}"
        f"<div style=\"font-size:12px;color:#7D8691;margin-top:10px;\">{html.escape(params_line)}</div>"
        "</div>"
    )


# ---------------- Ergebnisse ----------------
if st.session_state.results:
    st.subheader("Ergebnisse")

    dropped_by_model = {
        r["model_id"] for r in st.session_state.results if r["sent_params"].get("dropped_param")
    }
    if dropped_by_model:
        st.caption(
            "Bei manchen Modellen wurde nach einem 400-Fehler ein Parameter entfernt und ohne ihn "
            f"wiederholt - betroffen: {', '.join(sorted(dropped_by_model))}. Details pro Karte/Export."
        )

    by_prompt: dict = {}
    for r in st.session_state.results:
        by_prompt.setdefault(r["prompt_id"], []).append(r)
    prompt_order = [p["id"] for p in st.session_state.prompts if p["id"] in by_prompt]
    prompt_order += [pid for pid in by_prompt if pid not in prompt_order]  # Prompt inzwischen gelöscht

    for prompt_id in prompt_order:
        prompt_text = next((p["text"] for p in st.session_state.prompts if p["id"] == prompt_id), prompt_id)
        rows_for_prompt = by_prompt[prompt_id]
        run_id_for_rating = rows_for_prompt[0]["run_id"]

        st.markdown(f"**{prompt_id} · {prompt_text}**")
        cards = "".join(_render_result_card(r) for r in rows_for_prompt)
        st.markdown(
            f"<div style='display:flex;gap:16px;overflow-x:auto;padding-bottom:12px;'>{cards}</div>",
            unsafe_allow_html=True,
        )

        model_ids_here = [r["model_id"] for r in rows_for_prompt]
        current_best_model = next((r["model_id"] for r in rows_for_prompt if r.get("is_best")), None)
        best_options = ["Keine"] + model_ids_here
        best_choice = st.radio(
            "Beste Antwort", best_options,
            index=best_options.index(current_best_model) if current_best_model in best_options else 0,
            horizontal=True, key=f"best_{run_id_for_rating}_{prompt_id}",
        )
        winner = best_choice if best_choice != "Keine" else None
        if winner != current_best_model:
            for r in rows_for_prompt:
                r["is_best"] = (r["model_id"] == winner)
            store.set_best_answer(run_id_for_rating, prompt_id, winner)

        star_cols = st.columns(len(rows_for_prompt))
        for col, r in zip(star_cols, rows_for_prompt):
            with col:
                st.caption(r["model_id"])
                stars = st.feedback(
                    "stars", key=f"stars_{run_id_for_rating}_{r['model_id']}_{prompt_id}",
                )
                if stars is not None and stars + 1 != r.get("stars"):
                    r["stars"] = stars + 1
                    store.set_stars(run_id_for_rating, r["model_id"], prompt_id, stars + 1)
        st.divider()

    df = pd.DataFrame(st.session_state.results)
    known_cost = df["cost_usd"].dropna()
    unknown_cost_count = int(df["cost_usd"].isna().sum())
    cost_note = (
        f" (zzgl. {unknown_cost_count} Antwort/en mit unbekanntem Preis, nicht eingerechnet)"
        if unknown_cost_count else ""
    )
    st.caption(
        f"Geschätzte Gesamtkosten dieses Laufs: ${known_cost.sum():.6f} "
        f"(deine Preise aus der Modell-Liste oben){cost_note}"
    )

    with st.expander("Alle Ergebnisse als Tabelle"):
        table_cols = ["model_id", "prompt_id", "technique", "ok",
                      "ttft_s", "generation_s", "latency_s", "tokens_in", "tokens_out",
                      "tokens_per_s", "reasoning_tokens", "cost_usd", "response"]
        int_cols = {"tokens_in", "tokens_out", "reasoning_tokens"}
        cost_cols = {"cost_usd"}
        float_cols = {"ttft_s", "generation_s", "latency_s", "tokens_per_s"}

        def _fmt_table_value(value, col):
            if pd.isna(value):
                return "–"
            if col in int_cols:
                return str(int(value))
            if col in cost_cols:
                return f"${value:.6f}"
            if col in float_cols:
                return f"{value:.2f}"
            return value

        display_df = df[table_cols].copy()
        for col in int_cols | cost_cols | float_cols:
            display_df[col] = display_df[col].apply(lambda v, c=col: _fmt_table_value(v, c))
        st.dataframe(display_df, use_container_width=True)

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
    TIMELINE_METRICS = ["generation_s", "tokens_per_s", "ttft_s", "latency_s", "tokens_out", "tokens_in", "cost_usd"]
    metric = st.selectbox(
        "Metrik", TIMELINE_METRICS,
        format_func=lambda m: {
            "generation_s": "Generierungszeit (s, ohne Warteschlange)", "tokens_per_s": "Tokens/Sekunde",
            "ttft_s": "TTFT (s, inkl. Warteschlange)", "latency_s": "Gesamtlatenz (s, inkl. Warteschlange)",
            "tokens_out": "Output-Tokens", "tokens_in": "Input-Tokens", "cost_usd": "Kosten (USD)",
        }[m],
        help="Generierungszeit/Tokens pro Sekunde spiegeln die Modell-Leistung - die Gesamtlatenz "
             "misst bei NVIDIA Build (Freikontingent) vor allem die Warteschlange.",
    )
    if chosen:
        hist = store.load_for_models(chosen)
        hist = hist.dropna(subset=[metric])
        if hist.empty:
            st.caption("Für diese Metrik liegen bei den gewählten Modellen noch keine Werte vor.")
        else:
            chart = (
                hist.groupby([hist["timestamp"].dt.floor("min"), "model_id"])[metric].mean()
                .reset_index().pivot(index="timestamp", columns="model_id", values=metric)
            )
            y_max = float(chart.max().max())
            st.altair_chart(
                alt.Chart(chart.reset_index().melt(id_vars="timestamp", var_name="model_id", value_name=metric))
                .mark_line(point=True)
                .encode(
                    x="timestamp:T",
                    y=alt.Y(f"{metric}:Q", scale=alt.Scale(domain=[0, y_max * 1.1 if y_max > 0 else 1])),
                    color="model_id:N",
                )
                .properties(height=320),
                use_container_width=True,
            )
            st.caption(
                f"{store.run_count()} Lauf/Läufe gespeichert. Voraussetzung: Der Anbieter hält die Modell-ID stabil — "
                "bei einer Umbenennung reißt die Zeitreihe ab."
            )

    st.markdown("**Siege pro Modell**")
    wins = store.wins_per_model()
    if wins.empty:
        st.caption("Noch keine 'Beste Antwort' markiert.")
    else:
        st.bar_chart(wins.set_index("model_id")["wins"])
