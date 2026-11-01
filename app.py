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
import json
import threading
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
from models import SEPARATOR, build_dropdown_options, fetch_chat_models, pick_quick_test_candidates
from pricing import estimate_cost_usd
from rag import RagIndex, build_prompt
from storage import RunStore

st.set_page_config(page_title="AiVersus", page_icon="🧪", layout="wide")
store = RunStore()

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
CATALOG_TIMEOUT_S = 30.0  # für models.list() - unabhängig von der Generierungs-Warteschlange
MAX_CONCURRENT_CALLS = 5  # Calls parallel, aber begrenzt - kein Ansturm auf den Freikontingent-Key
TECHNIQUES = ["Zero-Shot Prompting", "Few-Shot Prompting", "Chain-of-Thought Prompting", "Andere…"]

if "prompts" not in st.session_state:
    st.session_state.prompts = [
        {"id": "p1", "text": "Erkläre RAG in 3 Sätzen.", "technique": "Zero-Shot Prompting"},
        {"id": "p2", "text": "Schreibe eine Python-Funktion für Fibonacci.", "technique": "Few-Shot Prompting"},
    ]
if "results" not in st.session_state:
    st.session_state.results = []
if "unavailable_models" not in st.session_state:
    st.session_state.unavailable_models = set()


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


@st.cache_resource
def get_index(api_key: str) -> RagIndex:
    return RagIndex(api_key=api_key)


@st.cache_data(ttl=300, show_spinner="Modellkatalog wird geladen ...")
def _load_chat_models(api_key: str) -> list:
    client = OpenAI(base_url=NVIDIA_BASE_URL, api_key=api_key, timeout=CATALOG_TIMEOUT_S, max_retries=0)
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

        candidates = pick_quick_test_candidates(chat_models, limit=5)
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
    choices = [
        m for m in dropdown_options
        if m != SEPARATOR and m not in st.session_state.unavailable_models
    ]
    st.sidebar.caption(f"{len(choices)} Chat-Modelle geladen - Top 10 zuerst, dann der Rest alphabetisch.")
    if st.session_state.unavailable_models:
        st.sidebar.caption(
            "Für diesen Account nicht verfügbar (ausgeblendet): "
            + ", ".join(sorted(st.session_state.unavailable_models))
        )
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

def _run_one_task(client, model_id, prompt, task_progress, progress_lock):
    """Läuft in einem Worker-Thread - rührt nie st.session_state oder st.* an, nur den

    geteilten task_progress-Dict (für die Live-Anzeige im Hauptthread).
    """
    key = (model_id, prompt["id"])
    call_start = time.perf_counter()

    def _on_progress(elapsed_s: float, partial_text: str, got_first_token: bool) -> None:
        with progress_lock:
            task_progress[key] = {"elapsed": elapsed_s, "first_token": got_first_token, "done": False}

    print(f"[{datetime.now(timezone.utc).isoformat()}] START {model_id} prompt={prompt['id']}", flush=True)
    try:
        result = call_chat_streaming(
            client, model_id,
            [{"role": "user", "content": build_prompt(prompt["text"], [])}],
            on_progress=_on_progress,
            first_token_timeout_s=first_token_timeout_s,
            inter_token_timeout_s=inter_token_timeout_s,
        )
        exc = None
    except Exception as e:  # unerwarteter Fehler außerhalb des API-Aufrufs selbst
        result, exc = None, e
    with progress_lock:
        task_progress[key] = {
            "elapsed": result.duration_s if result else round(time.perf_counter() - call_start, 3),
            "first_token": True, "done": True,
        }
    return model_id, prompt, result, exc, call_start


def _build_result_row(run_id: str, model_id: str, prompt: dict, result, exc, call_start: float) -> dict:
    row = {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model_id": model_id,
        "prompt_id": prompt["id"],
        "technique": prompt["technique"],
        "injected_context": False,
        "retrieved_sources": [],
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
    row["cost_usd"] = estimate_cost_usd(model_id, row["tokens_in"], row["tokens_out"])
    return row


# ---------------- Ausführung ----------------
if st.button("▶ Benchmark starten", type="primary", disabled=not (selected and prompts and nvidia_key)):
    client = OpenAI(base_url=NVIDIA_BASE_URL, api_key=nvidia_key, timeout=chat_client_timeout_s, max_retries=0)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    tasks = [(m, p) for m in selected for p in prompts]
    st.session_state.results = []
    progress = st.progress(0.0)
    status_area = st.empty()

    task_progress: dict = {}
    progress_lock = threading.Lock()

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(MAX_CONCURRENT_CALLS, len(tasks))) as executor:
        future_to_task = {
            executor.submit(_run_one_task, client, model_id, prompt, task_progress, progress_lock): (model_id, prompt)
            for model_id, prompt in tasks
        }
        pending = set(future_to_task)
        done_count = 0
        while pending:
            done_now, pending = concurrent.futures.wait(
                pending, timeout=0.5, return_when=concurrent.futures.FIRST_COMPLETED
            )
            for future in done_now:
                model_id, prompt, result, exc, call_start = future.result()
                row = _build_result_row(run_id, model_id, prompt, result, exc, call_start)
                st.session_state.results.append(row)
                store.save_results([row])  # sofort sichern - ein später abbrechender Lauf verliert nichts Bisheriges
                done_count += 1

            lines = []
            with progress_lock:
                for model_id, prompt in tasks:
                    info = task_progress.get((model_id, prompt["id"]))
                    if info is None:
                        lines.append(f"- {model_id} · {prompt['id']}: wartet auf freien Slot ...")
                    elif info["done"]:
                        lines.append(f"- {model_id} · {prompt['id']}: fertig ({info['elapsed']:.1f} s)")
                    elif not info["first_token"]:
                        lines.append(f"- {model_id} · {prompt['id']}: in der NVIDIA-Warteschlange - wartet seit {info['elapsed']:.0f} s")
                    else:
                        lines.append(f"- {model_id} · {prompt['id']}: generiert ... ({info['elapsed']:.0f} s)")
            status_area.markdown("\n".join(lines))
            progress.progress(done_count / len(tasks), text=f"{done_count}/{len(tasks)} abgeschlossen")

    status_area.empty()
    progress.progress(1.0, text="Fertig")

# ---------------- Ergebnisse ----------------
if st.session_state.results:
    st.subheader("Ergebnisse")
    df = pd.DataFrame(st.session_state.results)
    st.dataframe(
        df[["model_id", "prompt_id", "technique", "ok",
            "ttft_s", "generation_s", "latency_s", "tokens_in", "tokens_out",
            "tokens_per_s", "reasoning_tokens", "cost_usd", "response"]],
        use_container_width=True,
    )
    st.caption(f"Geschätzte Gesamtkosten dieses Laufs: ${df['cost_usd'].sum():.6f} (Preise: pricing.py, Richtwerte)")

    reasoning_rows = [r for r in st.session_state.results if r.get("reasoning")]
    if reasoning_rows:
        with st.expander(f"Reasoning ({len(reasoning_rows)} Zeile/n mit Denkprozess)"):
            for r in reasoning_rows:
                st.markdown(f"**{r['model_id']} · {r['prompt_id']}**")
                st.write(r["reasoning"])
                st.divider()

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
