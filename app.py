# -*- coding: utf-8 -*-
#
# AiVersus – LLM-Vergleich (Evo V0.5)
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

from chat_client import NoFirstTokenTimeout, NoFurtherTokenTimeout, StreamCancelled, call_chat_streaming
from i18n import make_translator
from models import (
    SEPARATOR,
    build_dropdown_options,
    fetch_chat_models,
    fetch_chat_models_by_recency,
    fetch_embedding_models,
    pick_quick_test_candidates,
)
from rag import EmbedModelMismatch, RagIndex, build_prompt, clear_persisted_collection
from storage import RunStore

st.set_page_config(page_title="AiVersus", page_icon="🧪", layout="wide")

DEBUG = os.environ.get("AIVERSUS_DEBUG") == "1"
if DEBUG:
    if "rerun_count" not in st.session_state:
        st.session_state.rerun_count = 0
    st.session_state.rerun_count += 1
    print(f"[{datetime.now(timezone.utc).isoformat()}] RERUN #{st.session_state.rerun_count}", flush=True)

# Buttons/Eingaben mit Mindesthöhe 44px (Barrierefreiheit, siehe Design-Vorlage) - [theme] in
# .streamlit/config.toml deckt Farben/Fonts/Radien ab, aber keine Mindesthöhen für Touch-Targets.
st.markdown(
    "<style>"
    ".stButton button, .stDownloadButton button, .stLinkButton a { min-height: 44px; }"
    "</style>",
    unsafe_allow_html=True,
)

if "lang" not in st.session_state:
    st.session_state.lang = "en"  # Englisch ist Standard
lang_choice = st.sidebar.radio(
    "Language / Sprache", ["EN", "DE"], horizontal=True,
    index=0 if st.session_state.lang == "en" else 1, key="lang_picker",
)
st.session_state.lang = "en" if lang_choice == "EN" else "de"
t = make_translator(st.session_state.lang)

NVIDIA_BASE_URL = os.environ.get("AIVERSUS_BASE_URL") or "https://integrate.api.nvidia.com/v1"
CATALOG_TIMEOUT_S = 30.0  # für models.list() - unabhängig von der Generierungs-Warteschlange
MAX_CONCURRENT_CALLS = 5  # Calls parallel, aber begrenzt - kein Ansturm auf den Freikontingent-Key

# Alle persistenten Daten (runs.db, availability.json, pricing.json, rag_store/) laufen über
# diese EINE Konstante - mit AIVERSUS_DATA_DIR überschreibbar. Tests/Mock-Läufe setzen das auf
# ein Temp-Verzeichnis und berühren so nie die echten Projektdaten (siehe CLAUDE.md).
DATA_DIR = os.environ.get("AIVERSUS_DATA_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)

AVAILABILITY_PATH = os.path.join(DATA_DIR, "availability.json")
AVAILABILITY_CHECK_TIMEOUT_S = 20.0  # kurzes Zeitfenster pro Modell - reicht für den Mini-Call
PRICING_JSON_PATH = os.path.join(DATA_DIR, "pricing.json")
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")

store = RunStore(db_path=os.path.join(DATA_DIR, "runs.db"))
TECHNIQUES = ["Zero-Shot Prompting", "Few-Shot Prompting", "Chain-of-Thought Prompting", t("main.prompts.other_technique")]
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


def _fmt(value, suffix: str = "", digits: int = 2) -> str:
    if value is None:
        return "–"
    return f"{value:.{digits}f}{suffix}" if isinstance(value, float) else f"{value}{suffix}"


def _fmt_tokens(value) -> str:
    return "–" if value is None else str(value)


def _fmt_cost(value) -> str:
    return "–" if value is None else f"${value:.6f}"


_STATUS_COLORS = {  # (Hintergrund, Text) - "ok" bekommt jetzt auch ein Badge, nicht nur Fehler
    "ok": ("#16301C", "#7FD858"), "fehler": ("#3A1F22", "#E85D75"),
    "timeout": ("#3A2A14", "#F2B34A"), "abgebrochen": ("#242830", "#9AA3AE"),
}
ANSWER_KEY_PREFIX = "show_answer_"


def _render_card(container, row: dict, card_key: str) -> None:
    """Eine Ergebniskarte - für Benchmark-Ergebnisse UND den Verbindungstest gleichermaßen.

    Immer sichtbar: Name/Farbe, Status-/Abgeschnitten-/Beste-Antwort-Badges, Sterne, die
    Verbrauchszeile, bei Fehlern die kurze Fehlermeldung. Aufklappbar (je ein eigener
    st.expander, nicht verschachtelt): Antwort, Reasoning, RAG-Quellen, Parameter. Die
    Antwort selbst geht NIE als HTML-String durch html.escape(), sondern über st.markdown() -
    sonst rendert z.B. ein ```python-Block oder eine '#'-Überschrift in der Modellantwort
    kaputt (Markdown wird im umschließenden HTML-String erneut interpretiert) oder zeigt
    escapte Entities (&quot; &gt; &lt;) statt der echten Zeichen (siehe Chat-Protokoll).
    """
    color = model_color(row["model_id"])
    status = row.get("outcome") or ("ok" if row.get("ok") else "fehler")
    bg, fg = _STATUS_COLORS.get(status, _STATUS_COLORS["fehler"])
    pill = "display:inline-block;padding:3px 10px;border-radius:999px;font-size:12px;margin:0 6px 6px 0;"
    badges_html = f"<span style='{pill}background:{bg};color:{fg};'>{html.escape(t(f'main.run.status_label.{status}'))}</span>"
    if row.get("finish_reason") == "length":
        badges_html += f"<span style='{pill}background:#3A2A14;color:#F2B34A;'>{t('main.card.truncated_badge')}</span>"
    if row.get("is_best"):
        badges_html += (
            f"<span style='{pill}background:#2A2314;color:#F2B34A;font-weight:600;'>{t('main.card.best_badge')}</span>"
        )

    sp = row.get("sent_params") or {}
    seed_display = sp.get("seed") if sp.get("seed") is not None else t("main.card.param_not_set")
    metrics = (
        f"TTFT {_fmt(row.get('ttft_s'), ' s')} · {t('main.card.metric_gen')} {_fmt(row.get('generation_s'), ' s')} · "
        f"Tokens {_fmt_tokens(row.get('tokens_in'))}/{_fmt_tokens(row.get('tokens_out'))}"
        + (t("main.card.metric_reasoning_tokens", count=row["reasoning_tokens"]) if row.get("reasoning_tokens") else "")
        + f" · {_fmt(row.get('tokens_per_s'), ' ' + t('main.card.metric_tokps'), 1)} · {_fmt_cost(row.get('cost_usd'))}"
    )

    with container:
        st.markdown(
            "<div style=\"display:flex;align-items:center;gap:8px;margin-bottom:6px;\">"
            f"<span style=\"color:{color};font-size:18px;\">●</span>"
            f"<strong>{html.escape(row['model_id'])}</strong></div>"
            f"<div>{badges_html}</div>",
            unsafe_allow_html=True,
        )
        if row.get("stars"):
            st.markdown(
                f"<div style='color:#F2B34A;margin-bottom:6px;'>{'★' * row['stars']}{'☆' * (5 - row['stars'])}</div>",
                unsafe_allow_html=True,
            )
        st.markdown(
            f"<div style=\"font-size:13px;color:#9AA3AE;margin:4px 0 8px;"
            f"font-family:'IBM Plex Mono',monospace;\">{metrics}</div>",
            unsafe_allow_html=True,
        )
        if not row.get("ok") and row.get("response"):
            st.markdown(
                f"<div style=\"font-size:13px;color:#E85D75;margin-bottom:8px;\">{html.escape(row['response'])}</div>",
                unsafe_allow_html=True,
            )

        if row.get("ok") and row.get("response"):
            # st.expander(expanded=..., key=...) ignoriert einen programmatisch gesetzten
            # session_state-Wert nach der ersten Erstellung zuverlässig (live getestet: "Alle
            # aufklappen" hat die Expander sichtbar nicht geöffnet) - st.toggle reagiert auf
            # genau dasselbe Muster (session_state[key] vor der Widget-Erstellung setzen)
            # zuverlässig, siehe main.card.show_answer_toggle als Ersatz für st.expander hier.
            answer_key = f"{ANSWER_KEY_PREFIX}{card_key}"
            if st.toggle(t("main.card.show_answer_toggle"), key=answer_key):
                st.markdown(row["response"])

        if row.get("reasoning"):
            with st.expander(t("common.reasoning"), key=f"reasoning_{card_key}"):
                st.markdown(row["reasoning"])

        if row.get("injected_context"):
            rag_label = t("main.card.rag_summary", count=len(row.get("retrieved_sources", [])))
            with st.expander(rag_label, key=f"rag_{card_key}"):
                for source in row.get("retrieved_sources", []):
                    st.markdown(f"- {source}")

        with st.expander(t("main.card.parameters_expander"), key=f"params_{card_key}"):
            params_line = (
                f"temperature={sp.get('temperature')}, top_p={sp.get('top_p')}, "
                f"max_tokens={sp.get('max_tokens')}, seed={seed_display}"
            )
            if sp.get("dropped_param"):
                params_line += t("main.card.param_dropped_suffix", param=sp["dropped_param"])
            st.caption(params_line)
            st.caption(f"{t('main.card.prompt_label')}: {row.get('prompt_text') or t('common.unknown_prompt')}")


def _card_key(row: dict) -> str:
    return f"{row['run_id']}_{row['prompt_id']}_{row['model_id']}"


def _classify_outcome(result, exc) -> str:
    """ok / timeout / abgebrochen / fehler - für Status-Badges und die Live-Statuszeile."""
    error = exc if exc is not None else (None if result is None or result.ok else result.error)
    if error is None:
        return "ok"
    if isinstance(error, StreamCancelled):
        return "abgebrochen"
    if isinstance(error, TimeoutError):
        return "timeout"
    return "fehler"


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


def load_settings() -> dict:
    """{"prompts", "selected_models", "model_prices"} - nie API-Keys, die bleiben nur im Session-State."""
    if not os.path.exists(SETTINGS_PATH):
        return {}
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_settings() -> None:
    data = {
        "prompts": st.session_state.prompts,
        "selected_models": st.session_state.selected_models,
        "model_prices": st.session_state.model_prices,
    }
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


_saved_settings = load_settings()
if "prompts" not in st.session_state:
    # p1: Zero-Shot (direkte Frage, keine Beispiele) - Technik-Etikett passt zum Prompt.
    # p2: echtes Few-Shot (drei vorgemachte Beispiele vor der eigentlichen Aufgabe), siehe
    # README-Abschnitt "Nutzung" - vorher stand hier "Schreibe eine Python-Funktion für
    # Fibonacci." mit dem Etikett "Few-Shot Prompting", obwohl der Prompt gar keine Beispiele
    # enthielt und damit eigentlich Zero-Shot war.
    st.session_state.prompts = _saved_settings.get("prompts") or [
        {"id": "p1", "text": "Erkläre RAG in 3 Sätzen.", "technique": "Zero-Shot Prompting"},
        {
            "id": "p2",
            "text": (
                "Klassifiziere die Stimmung (positiv/negativ/neutral) der folgenden Aussage.\n\n"
                "Beispiel 1:\n"
                "Aussage: \"Der Support hat mir super schnell geholfen, bin begeistert!\"\n"
                "Stimmung: positiv\n\n"
                "Beispiel 2:\n"
                "Aussage: \"Die Lieferung kam drei Wochen zu spät und niemand hat reagiert.\"\n"
                "Stimmung: negativ\n\n"
                "Beispiel 3:\n"
                "Aussage: \"Die Bestellung ist heute angekommen, Inhalt wie beschrieben.\"\n"
                "Stimmung: neutral\n\n"
                "Jetzt du:\n"
                "Aussage: \"Die App ist ok, aber der Login hängt sich ständig auf.\"\n"
                "Stimmung:"
            ),
            "technique": "Few-Shot Prompting",
        },
    ]
if "results" not in st.session_state:
    st.session_state.results = []
if "unavailable_models" not in st.session_state:
    st.session_state.unavailable_models = set()
if "selected_models" not in st.session_state:
    st.session_state.selected_models = _saved_settings.get("selected_models", [])
if "model_prices" not in st.session_state:
    st.session_state.model_prices = _saved_settings.get("model_prices", {})
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
    """Kurze, übersetzte Fehlermeldung ohne Account-/Function-IDs - Details gehen ins Terminal-Log."""
    if isinstance(e, StreamCancelled):
        return t("error.cancelled")
    if isinstance(e, NoFirstTokenTimeout):
        return t("error.no_first_token", seconds=f"{e.elapsed_s:.0f}")
    if isinstance(e, NoFurtherTokenTimeout):
        return t("error.no_further_token", seconds=f"{e.elapsed_s:.0f}")
    if isinstance(e, TimeoutError):  # sonstiger eigener Stream-Timeout, kein Server-Fehler
        return f"{t('error.no_further_token', seconds='?')} ({e})"
    if isinstance(e, AuthenticationError):
        return t("error.auth")
    if isinstance(e, RateLimitError):
        return t("error.rate_limit")
    if isinstance(e, NotFoundError):
        return t("error.not_found")
    if isinstance(e, APIStatusError) and e.status_code == 410:
        return t("error.gone")
    if isinstance(e, APIStatusError):
        return t("error.status", status=e.status_code)
    if isinstance(e, APITimeoutError):
        return t("error.transport_timeout")
    if isinstance(e, APIConnectionError):
        return t("error.connection")
    if isinstance(e, APIError):
        return t("error.api")
    return t("error.unknown")


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
    return RagIndex(
        api_key=api_key, base_url=NVIDIA_BASE_URL, embed_model=embed_model,
        persist_dir=os.path.join(DATA_DIR, "rag_store"),
    )


@st.cache_data(ttl=3600, show_spinner="Modellkatalog wird geladen ...")
def _load_chat_models(api_key: str) -> list:
    client = OpenAI(base_url=NVIDIA_BASE_URL, api_key=api_key, timeout=CATALOG_TIMEOUT_S, max_retries=0)
    return fetch_chat_models(client)


@st.cache_data(ttl=3600, show_spinner=False)
def _load_embedding_models(api_key: str) -> list:
    client = OpenAI(base_url=NVIDIA_BASE_URL, api_key=api_key, timeout=CATALOG_TIMEOUT_S, max_retries=0)
    return fetch_embedding_models(client)


# ---------------- Sidebar: API-Key ----------------
st.sidebar.header(t("sidebar.api_key.header"))
nvidia_key = st.sidebar.text_input(
    t("sidebar.api_key.label"),
    type="password",
    placeholder="nvapi-...",
    key="nvidia_api_key",
    help=t("sidebar.api_key.help"),
)

# ---------------- Sidebar: Timeouts ----------------
st.sidebar.divider()
st.sidebar.subheader(t("sidebar.timeouts.header"))
st.sidebar.caption(t("sidebar.timeouts.caption"))
first_token_timeout_s = st.sidebar.number_input(
    t("sidebar.timeouts.first_token_label"), min_value=10, max_value=600, value=300, step=10,
)
inter_token_timeout_s = st.sidebar.number_input(
    t("sidebar.timeouts.inter_token_label"), min_value=5, max_value=300, value=60, step=5,
)
chat_client_timeout_s = first_token_timeout_s + 30  # Transport-Timeout muss größer sein als unser eigenes

# ---------------- Sidebar: Verbindungstest ----------------
st.sidebar.divider()
st.sidebar.subheader(t("sidebar.test.header"))
st.sidebar.caption(t("sidebar.test.caption"))
if st.sidebar.button(t("sidebar.test.button"), disabled=not nvidia_key):
    client = OpenAI(base_url=NVIDIA_BASE_URL, api_key=nvidia_key, timeout=chat_client_timeout_s, max_retries=0)
    try:
        chat_models = fetch_chat_models(client)  # ungecacht - der Test soll den Key gerade neu prüfen
    except Exception as e:
        st.sidebar.error(describe_api_error(e))
    else:
        st.sidebar.success(t("sidebar.test.key_valid", count=len(chat_models)))

        with st.sidebar.expander(t("sidebar.test.catalog_diagnostics")):
            namespace_counts = Counter(m.split("/", 1)[0] for m in chat_models if "/" in m)
            without_namespace = [m for m in chat_models if "/" not in m]
            st.write(
                t("sidebar.test.namespaces_label") + " "
                + ", ".join(f"{ns}: {count}" for ns, count in sorted(namespace_counts.items()))
            )
            if without_namespace:
                st.write(t("sidebar.test.without_namespace_label", count=len(without_namespace)), without_namespace)
            st.write(t("sidebar.test.all_ids_label"))
            st.code("\n".join(sorted(chat_models)))

        chat_models_by_recency = fetch_chat_models_by_recency(client)
        preferred = [st.session_state.last_successful_test_model] if st.session_state.last_successful_test_model else []
        candidates = pick_quick_test_candidates(chat_models_by_recency, limit=5, preferred=preferred)
        if not candidates:
            st.sidebar.warning(t("sidebar.test.no_model_found"))
        else:
            status_box = st.sidebar.empty()
            text_box = st.sidebar.empty()
            tried, result, test_model = [], None, None

            def _on_progress(elapsed_s: float, partial_text: str, got_first_token: bool) -> None:
                if not got_first_token:
                    status_box.caption(t("sidebar.test.queue_status", elapsed=elapsed_s))
                else:
                    status_box.caption(t("sidebar.test.generating_status", elapsed=elapsed_s))
                if partial_text:
                    text_box.markdown(t("sidebar.test.running_prefix", text=partial_text))

            sent_params = {"temperature": 0.2, "max_tokens": 20}
            for candidate in candidates:
                tried.append(candidate)
                print(f"[{datetime.now(timezone.utc).isoformat()}] START {candidate} (Verbindungstest)", flush=True)
                result = call_chat_streaming(
                    client, candidate,
                    [{"role": "user", "content": t("sidebar.test.prompt")}],
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
                st.sidebar.caption(t("sidebar.test.unavailable_trying_next", model=candidate))

            status_box.empty()
            text_box.empty()
            test_sent_params = {
                "temperature": sent_params["temperature"], "max_tokens": sent_params["max_tokens"],
                "top_p": None, "seed": None, "dropped_param": None,
            }
            if result.ok:
                st.session_state.last_successful_test_model = test_model
                st.sidebar.success(t("sidebar.test.answered", model=test_model, duration=result.duration_s))
                if len(tried) > 1:
                    st.sidebar.caption(t("sidebar.test.tried_unavailable", models=", ".join(tried[:-1])))
                test_row = {
                    "model_id": test_model, "ok": True, "response": result.content, "reasoning": result.reasoning,
                    "tokens_in": result.tokens_in, "tokens_out": result.tokens_out,
                    "reasoning_tokens": result.reasoning_tokens, "ttft_s": result.ttft_s,
                    "generation_s": result.generation_s,
                    "tokens_per_s": (
                        round(result.tokens_out / result.generation_s, 1)
                        if result.tokens_out and result.generation_s else None
                    ),
                    "cost_usd": None, "finish_reason": result.finish_reason, "outcome": "ok",
                    "sent_params": test_sent_params, "injected_context": False, "retrieved_sources": [],
                    "is_best": False, "stars": None, "prompt_text": t("sidebar.test.prompt"),
                }
            else:
                st.sidebar.error(describe_api_error(result.error))
                test_row = {
                    "model_id": test_model, "ok": False, "response": describe_api_error(result.error),
                    "reasoning": "", "tokens_in": None, "tokens_out": None, "reasoning_tokens": None,
                    "ttft_s": result.ttft_s, "generation_s": result.generation_s, "tokens_per_s": None,
                    "cost_usd": None, "finish_reason": result.finish_reason,
                    "outcome": _classify_outcome(result, None),
                    "sent_params": test_sent_params, "injected_context": False, "retrieved_sources": [],
                    "is_best": False, "stars": None, "prompt_text": t("sidebar.test.prompt"),
                }
            _render_card(st.sidebar.container(border=True), test_row, f"test_{test_model}")

# ---------------- Sidebar: Verfügbarkeit ----------------
st.sidebar.divider()
st.sidebar.subheader(t("sidebar.availability.header"))
availability_run_active = st.session_state.availability_run is not None
last_checked = st.session_state.availability_data.get("checked_at")
if last_checked:
    st.sidebar.caption(t("sidebar.availability.last_checked", timestamp=last_checked))
else:
    st.sidebar.caption(t("sidebar.availability.never_checked"))

if st.sidebar.button(
    t("sidebar.availability.button"), disabled=availability_run_active or not nvidia_key,
    help=t("sidebar.availability.help"),
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

@st.fragment(run_every=0.5)
def _availability_progress_fragment() -> None:
    """Pollt nur sich selbst (run_every), statt mit time.sleep()+st.rerun() die ganze App

    bei jedem Tick neu zu zeichnen - läuft nur, solange Futures offen sind (siehe Aufrufstelle
    unten), und löst bei Abschluss genau einen vollen Rerun aus (st.rerun(scope="app")).
    """
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
        avail_run["done_count"] / avail_run["total"],
        text=t("sidebar.availability.progress", done=avail_run["done_count"], total=avail_run["total"]),
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
        st.sidebar.success(t("sidebar.availability.result", available=n_avail, unavailable=n_unavail, slow=n_slow))
        st.rerun(scope="app")


if st.session_state.availability_run is not None:
    _availability_progress_fragment()

# ---------------- Sidebar: LLM Pricing ----------------
st.sidebar.divider()


def _clean_text_cell(value) -> str | None:
    """Leere/NaN-Zellen aus dem data_editor als None, nicht als String "None"/"nan"."""
    if pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


@st.dialog(t("sidebar.pricing.dialog_title"), width="large")
def _pricing_dialog() -> None:
    st.caption(t("sidebar.pricing.caption"))
    col_model, col_input, col_output, col_source, col_updated, col_free = (
        t("sidebar.pricing.col_model"), t("sidebar.pricing.col_input"), t("sidebar.pricing.col_output"),
        t("sidebar.pricing.col_source"), t("sidebar.pricing.col_updated"), t("sidebar.pricing.col_free"),
    )
    models_dict = st.session_state.pricing_data
    rows = [
        {col_model: m, col_input: v.get("input"), col_output: v.get("output"),
         col_source: v.get("source") or "", col_updated: v.get("updated") or "", col_free: bool(v.get("free"))}
        for m, v in sorted(models_dict.items())
    ]
    pricing_df = pd.DataFrame(rows, columns=[col_model, col_input, col_output, col_source, col_updated, col_free])
    edited = st.data_editor(
        pricing_df, num_rows="dynamic", use_container_width=True, key="pricing_editor",
        column_config={
            col_input: st.column_config.NumberColumn(format="%.4f"),
            col_output: st.column_config.NumberColumn(format="%.4f"),
            col_updated: st.column_config.TextColumn(help=t("sidebar.pricing.col_updated_help")),
            col_free: st.column_config.CheckboxColumn(help=t("sidebar.pricing.col_free_help"), default=False),
        },
    )
    col_save, col_close = st.columns(2)
    if col_save.button(t("sidebar.pricing.save"), type="primary", use_container_width=True):
        new_models = {}
        for _, r in edited.iterrows():
            model_name = str(r[col_model] or "").strip()
            if not model_name:
                continue
            new_models[model_name] = {
                "input": float(r[col_input]) if pd.notna(r[col_input]) else None,
                "output": float(r[col_output]) if pd.notna(r[col_output]) else None,
                "source": _clean_text_cell(r[col_source]),
                "updated": _clean_text_cell(r[col_updated]),
                "free": bool(r[col_free]) if pd.notna(r[col_free]) else False,
            }
        st.session_state.pricing_data = new_models
        save_pricing_file(new_models)
        # Bereits ausgewaehlte Modelle nicht erst beim naechsten Entfernen+Hinzufuegen
        # aktualisieren - ein gerade gespeicherter Preis gilt sofort auch fuer sie. Die
        # number_input-Widgets unten (key=f"price_in_{model_id}") ignorieren ab ihrer ersten
        # Erstellung jedes neue value= - ohne das direkte Ueberschreiben hier wuerden sie den
        # gerade gespeicherten Preis im naechsten Rerun sofort wieder auf den alten Stand ziehen.
        for model_id in st.session_state.selected_models:
            priced = new_models.get(model_id)
            if priced and (priced.get("free") or (priced.get("input") is not None and priced.get("output") is not None)):
                st.session_state.model_prices[model_id] = {
                    "input": priced.get("input") or 0.0, "output": priced.get("output") or 0.0,
                    "free": priced.get("free", False),
                }
                st.session_state[f"price_in_{model_id}"] = priced.get("input") or 0.0
                st.session_state[f"price_out_{model_id}"] = priced.get("output") or 0.0
        st.rerun()
    if col_close.button(t("sidebar.pricing.close"), use_container_width=True):
        st.rerun()


if st.sidebar.button(t("sidebar.pricing.button")):
    _pricing_dialog()

# ---------------- Sidebar: RAG ----------------
st.sidebar.header(t("sidebar.rag.header"))
use_rag = st.sidebar.checkbox(t("sidebar.rag.checkbox"), value=False)
index = None
rag_ready = False
top_k = 4

if not use_rag:
    st.sidebar.caption(t("sidebar.rag.disabled_caption"))
elif not nvidia_key:
    st.sidebar.caption(t("sidebar.rag.no_key_caption"))
else:
    try:
        embedding_models = _load_embedding_models(nvidia_key)
    except Exception as e:
        st.sidebar.error(describe_api_error(e))
        embedding_models = []
    if not embedding_models:
        st.sidebar.warning(t("sidebar.rag.no_embed_model"))
    else:
        embed_model = st.sidebar.selectbox(t("sidebar.rag.embed_model_label"), embedding_models, key="embed_model_pick")
        try:
            index = get_index(nvidia_key, embed_model)
        except EmbedModelMismatch as e:
            st.sidebar.error(t("sidebar.rag.embed_mismatch", stored=e.stored_model, requested=e.requested_model))
            if st.sidebar.button(
                t("sidebar.rag.embed_mismatch_clear_button", requested=embed_model), use_container_width=True,
            ):
                clear_persisted_collection(os.path.join(DATA_DIR, "rag_store"), embed_model=embed_model)
                get_index.clear()  # verworfene RagIndex-Instanzen (alte Collection-Metadaten) nicht weiter cachen
                st.rerun()
            index = None
        else:
            top_k = st.sidebar.slider(t("sidebar.rag.topk_label"), 1, 10, 4)
            uploads = st.sidebar.file_uploader(
                t("sidebar.rag.upload_label"), type=["pdf", "txt", "md"], accept_multiple_files=True,
            )
            col_build, col_clear = st.sidebar.columns(2)
            if col_build.button(t("sidebar.rag.build_button"), disabled=not uploads, use_container_width=True):
                with st.sidebar, st.spinner(t("sidebar.rag.build_spinner")):
                    for f in uploads:
                        try:
                            index.add_document(f.name, f.getvalue())
                        except Exception as e:
                            st.sidebar.error(f"{f.name}: {describe_api_error(e)}")
            if col_clear.button(t("sidebar.rag.clear_button"), use_container_width=True):
                index.clear()

            for name, n in index.sources().items():
                st.sidebar.caption(t("sidebar.rag.source_line", name=name, count=n))

            rag_ready = index.document_count() > 0
            if not rag_ready:
                st.sidebar.caption(t("sidebar.rag.not_indexed_caption"))

st.sidebar.divider()
st.sidebar.caption(t("sidebar.footer"))

# ---------------- Modelle ----------------
st.title("AiVersus")
st.subheader(t("main.models.header"))

if not nvidia_key:
    st.caption(t("main.models.no_key_caption"))
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
    st.caption(t("main.models.hidden_caption", models=", ".join(sorted(hidden))))

slow_suffix = t("main.models.slow_suffix")
col_pick, col_add = st.columns([5, 1])
model_pick = col_pick.selectbox(
    t("main.models.add_label"), addable_choices, index=None, placeholder=t("main.models.add_placeholder"),
    key="model_picker", label_visibility="collapsed",
    format_func=lambda m: f"{m}{slow_suffix}" if m in slow_models else m,
)
if col_add.button(t("main.models.add_button"), disabled=not model_pick, use_container_width=True):
    st.session_state.selected_models.append(model_pick)
    priced = st.session_state.pricing_data.get(model_pick)
    if priced and (priced.get("free") or (priced.get("input") is not None and priced.get("output") is not None)):
        st.session_state.model_prices[model_pick] = {
            "input": priced.get("input") or 0.0, "output": priced.get("output") or 0.0,
            "free": priced.get("free", False),
        }
    else:
        st.session_state.model_prices[model_pick] = {"input": 0.0, "output": 0.0, "free": False}
    st.rerun()

if st.session_state.selected_models:
    if len(st.session_state.selected_models) >= 5:
        st.caption(t("main.models.many_models_caption"))
    header_dot, header_name, header_in, header_out, header_del = st.columns([0.4, 3, 1.3, 1.3, 0.5])
    header_name.caption(t("main.models.col_model"))
    header_in.caption(t("main.models.col_input"))
    header_out.caption(t("main.models.col_output"))

    to_remove = None
    for model_id in st.session_state.selected_models:
        col_dot, col_name, col_in, col_out, col_del = st.columns([0.4, 3, 1.3, 1.3, 0.5])
        col_dot.markdown(
            f"<span style='color:{model_color(model_id)}; font-size:22px;'>●</span>", unsafe_allow_html=True,
        )
        col_name.write(model_id)
        price = st.session_state.model_prices.setdefault(model_id, {"input": 0.0, "output": 0.0, "free": False})
        price["input"] = col_in.number_input(
            t("main.models.col_input"), value=price["input"], step=0.01, format="%.4f",
            key=f"price_in_{model_id}", label_visibility="collapsed",
        )
        price["output"] = col_out.number_input(
            t("main.models.col_output"), value=price["output"], step=0.01, format="%.4f",
            key=f"price_out_{model_id}", label_visibility="collapsed",
        )
        if col_del.button("✕", key=f"del_model_{model_id}"):
            to_remove = model_id
    if to_remove is not None:
        st.session_state.selected_models.remove(to_remove)
        st.session_state.model_prices.pop(to_remove, None)
        st.rerun()
else:
    st.caption(t("main.models.none_added_caption"))

selected = st.session_state.selected_models

# ---------------- Prompt-Suite ----------------
st.subheader(t("main.prompts.header"))

other_technique = t("main.prompts.other_technique")
to_delete = None
for i, p in enumerate(st.session_state.prompts):
    col_text, col_tech, col_del = st.columns([6, 3, 1])
    p["text"] = col_text.text_area(p["id"], value=p["text"], key=f"text_{p['id']}")
    choice = col_tech.selectbox(
        t("main.prompts.technique_label"), TECHNIQUES,
        index=TECHNIQUES.index(p["technique"]) if p["technique"] in TECHNIQUES else len(TECHNIQUES) - 1,
        key=f"tech_{p['id']}",
    )
    p["technique"] = (
        col_tech.text_input(t("main.prompts.custom_label"), value="", key=f"own_{p['id']}")
        if choice == other_technique else choice
    )
    col_del.write("")
    col_del.write("")
    if col_del.button("✕", key=f"del_{p['id']}"):
        to_delete = i
if to_delete is not None:
    st.session_state.prompts.pop(to_delete)
    st.rerun()

if st.button(t("main.prompts.add_button")):
    st.session_state.prompts.append(
        {"id": f"p{len(st.session_state.prompts) + 1}", "text": "", "technique": "Zero-Shot Prompting"}
    )
    st.rerun()

save_settings()  # Prompt-Suite, Modelle und Preise sind an dieser Stelle fuer diesen Lauf final
st.divider()
prompts = [p for p in st.session_state.prompts if p["text"].strip()]
st.write(t("main.summary", models=len(selected), prompts=len(prompts), calls=len(selected) * len(prompts)))

if not nvidia_key:
    st.warning(t("main.warning_no_key"))
if use_rag and not rag_ready:
    st.warning(t("main.warning_rag_not_ready"))

# ---------------- Parameter (für alle Modelle gleich) ----------------
st.subheader(t("main.parameters.header"))
col_temp, col_top_p, col_max_tokens = st.columns(3)
temperature = col_temp.number_input("temperature", min_value=0.0, max_value=2.0, value=0.7, step=0.1)
top_p = col_top_p.number_input("top_p", min_value=0.0, max_value=1.0, value=1.0, step=0.05)
max_tokens = col_max_tokens.number_input("max_tokens", min_value=1, max_value=8192, value=4096, step=1)

system_prompt = st.text_area(
    t("main.parameters.system_prompt_label"), value="", placeholder=t("main.parameters.system_prompt_placeholder"),
)

col_seed_on, col_seed_val = st.columns([1, 2])
use_seed = col_seed_on.checkbox(t("main.parameters.seed_checkbox"), value=False)
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
    kostenlos. Ohne explizites Free-Tier-Kennzeichen (im Preis-Dialog gesetzt) gilt 0.0/0.0
    weiterhin als "kein Preis eingetragen" (Heuristik, da das der Vorgabewert ohne Treffer
    ist); ist "free" gesetzt, sind die Kosten unabhängig von den Zahlenfeldern 0.0.
    """
    price = st.session_state.model_prices.get(model_id, {"input": 0.0, "output": 0.0, "free": False})
    if price.get("free"):
        return 0.0
    if price["input"] == 0.0 and price["output"] == 0.0:
        return None
    if tokens_in is None or tokens_out is None:
        return None
    return round((tokens_in * price["input"] + tokens_out * price["output"]) / 1_000_000, 6)


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
        "prompt_text": prompt["text"],
        "technique": prompt["technique"],
        "injected_context": bool(retrieved_chunks),
        "retrieved_sources": [f"{c.source}#{c.chunk_index}" for c in retrieved_chunks],
        "sent_params": _actual_sent_params(result),
        "stars": None,
        "is_best": False,
        "outcome": _classify_outcome(result, exc),
        "finish_reason": result.finish_reason if result is not None else None,
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
    t("main.run.start_button"), type="primary",
    disabled=run_active or not (selected and prompts and nvidia_key),
)
stop_clicked = col_stop.button(t("main.run.stop_button"), disabled=not run_active)

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
        with st.spinner(t("main.run.rag_spinner")):
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

@st.fragment(run_every=0.4)
def _benchmark_progress_fragment() -> None:
    """Pollt nur sich selbst (run_every), statt mit time.sleep()+st.rerun() die ganze App

    bei jedem Tick neu zu zeichnen - läuft nur, solange Futures offen sind (siehe Aufrufstelle
    unten), und löst bei Abschluss genau einen vollen Rerun aus (st.rerun(scope="app")).
    """
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

    st.progress(
        run["done_count"] / run["total"],
        text=t("main.run.progress", done=run["done_count"], total=run["total"]),
    )
    lines = []
    with run["progress_lock"]:
        for model_id, prompt in run["futures"].values():
            info = run["task_progress"].get((model_id, prompt["id"]))
            if info is None:
                lines.append(t("main.run.status.waiting_for_slot", model=model_id, prompt=prompt["id"]))
            elif info["done"]:
                label = t(f"main.run.status_label.{info.get('status', 'ok')}")
                detail = f" - {info['detail']}" if info.get("status") not in (None, "ok") and info.get("detail") else ""
                lines.append(t(
                    "main.run.status.done", model=model_id, prompt=prompt["id"],
                    label=label, elapsed=info["elapsed"], detail=detail,
                ))
            elif not info["first_token"]:
                lines.append(t("main.run.status.queue", model=model_id, prompt=prompt["id"], elapsed=info["elapsed"]))
            else:
                lines.append(t("main.run.status.generating", model=model_id, prompt=prompt["id"], elapsed=info["elapsed"]))
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
                "warning", t("main.run.message.cancelled", done=run["done_count"], total=run["total"]),
            )
        else:
            st.session_state.last_run_message = (
                "success", t("main.run.message.done", done=run["done_count"], total=run["total"]),
            )
        st.session_state.run = None
        st.rerun(scope="app")  # Start/Stop-Button-Zustand sofort neu zeichnen, nicht erst beim nächsten Klick


if st.session_state.run is not None:
    _benchmark_progress_fragment()


# ---------------- Ergebnisse ----------------
if st.session_state.results:
    st.subheader(t("main.results.header"))

    dropped_by_model = {
        r["model_id"] for r in st.session_state.results if r["sent_params"].get("dropped_param")
    }
    if dropped_by_model:
        st.caption(t("main.results.dropped_param_caption", models=", ".join(sorted(dropped_by_model))))

    col_expand, col_collapse = st.columns(2)
    if col_expand.button(t("main.results.expand_all"), use_container_width=True):
        for r in st.session_state.results:
            st.session_state[f"{ANSWER_KEY_PREFIX}{_card_key(r)}"] = True
        st.rerun()
    if col_collapse.button(t("main.results.collapse_all"), use_container_width=True):
        for r in st.session_state.results:
            st.session_state[f"{ANSWER_KEY_PREFIX}{_card_key(r)}"] = False
        st.rerun()

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
        grid_cols = None
        for i, r in enumerate(rows_for_prompt):
            if i % 3 == 0:
                grid_cols = st.columns(3)
            with grid_cols[i % 3]:
                _render_card(st.container(border=True), r, _card_key(r))

        model_ids_here = [r["model_id"] for r in rows_for_prompt]
        current_best_model = next((r["model_id"] for r in rows_for_prompt if r.get("is_best")), None)
        none_option = t("main.results.best_answer_none")
        best_options = [none_option] + model_ids_here
        best_choice = st.radio(
            t("main.results.best_answer_label"), best_options,
            index=best_options.index(current_best_model) if current_best_model in best_options else 0,
            horizontal=True, key=f"best_{run_id_for_rating}_{prompt_id}",
        )
        winner = best_choice if best_choice != none_option else None
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
        t("main.results.cost_unknown_note", count=unknown_cost_count) if unknown_cost_count else ""
    )
    st.caption(t("main.results.cost_caption", cost=f"{known_cost.sum():.6f}", note=cost_note))

    with st.expander(t("main.results.table_expander")):
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
st.subheader(t("main.timeline.header"))
known = store.known_models()
if not known:
    st.caption(t("main.timeline.no_runs_caption"))
else:
    chosen = st.multiselect(t("main.timeline.models_label"), known, default=known[:3])
    # tokens_per_s zuerst (= Standard ohne explizites index=) - bessere Modellvergleichs-Metrik
    # als generation_s, da sie Output-Laenge und Zeit in einer Zahl zusammenfuehrt.
    TIMELINE_METRICS = ["tokens_per_s", "generation_s", "ttft_s", "latency_s", "tokens_out", "tokens_in", "cost_usd"]
    metric = st.selectbox(
        t("main.timeline.metric_label"), TIMELINE_METRICS,
        format_func=lambda m: t(f"main.timeline.metric.{m}"),
        help=t("main.timeline.metric_help"),
    )
    if chosen:
        hist = store.load_for_models(chosen)
        hist = hist.dropna(subset=[metric])
        if hist.empty:
            st.caption(t("main.timeline.no_values_caption"))
        else:
            # Jede Zeile (run_id, model_id, prompt_id) ist bereits EIN Punkt (Primärschlüssel
            # in runs.db) - keine Aggregation mehr nötig. Eine Linie darf aber nur Punkte mit
            # gleichem (prompt_text, temperature, top_p, max_tokens) verbinden, sonst würde
            # z.B. ein Zero-Shot- mit einem Few-Shot-Lauf desselben Modells oder ein Lauf mit
            # max_tokens=1024 mit einem mit max_tokens=4096 verglichen, obwohl das nicht
            # vergleichbar ist. "detail" splittet die Linie pro Kombination, "color" bleibt
            # trotzdem das Modell (Farben konsistent mit dem Rest der App).
            def _compare_params(raw) -> tuple:
                try:
                    parsed = json.loads(raw) if raw else {}
                except (TypeError, ValueError):
                    parsed = {}
                return parsed.get("temperature"), parsed.get("top_p"), parsed.get("max_tokens")

            cmp_params = hist["sent_params"].apply(_compare_params)
            hist = hist.assign(
                _cmp_temperature=[p[0] for p in cmp_params],
                _cmp_top_p=[p[1] for p in cmp_params],
                _cmp_max_tokens=[p[2] for p in cmp_params],
            )
            hist["series_key"] = (
                hist["prompt_text"].fillna("?") + " | T=" + hist["_cmp_temperature"].astype(str)
                + " top_p=" + hist["_cmp_top_p"].astype(str) + " max_tokens=" + hist["_cmp_max_tokens"].astype(str)
            )
            series_per_model = hist.groupby("model_id")["series_key"].nunique()
            mixed_models = sorted(series_per_model[series_per_model > 1].index)
            if mixed_models:
                st.caption(t("main.timeline.mixed_params_caption", models=", ".join(mixed_models)))

            y_max = float(hist[metric].max())
            st.altair_chart(
                alt.Chart(hist)
                .mark_line(point=True)
                .encode(
                    # Wenige, lesbare Ticks statt einem Label pro Minute (Default von Altair
                    # bei dicht beieinander liegenden Zeitstempeln) - ca. 6 reichen, um den
                    # Zeitraum einzuordnen, ohne dass sich die Achse überlappt.
                    x=alt.X("timestamp:T", axis=alt.Axis(format="%d.%m. %H:%M", tickCount=6)),
                    y=alt.Y(f"{metric}:Q", scale=alt.Scale(domain=[0, y_max * 1.1 if y_max > 0 else 1])),
                    color="model_id:N",
                    detail="series_key:N",
                    tooltip=["model_id", "prompt_id", "prompt_text", f"{metric}:Q", "timestamp:T"],
                )
                .properties(height=320),
                use_container_width=True,
            )
            st.caption(t("main.timeline.footer_caption", count=store.run_count()))

    st.markdown(t("main.timeline.wins_header"))
    wins = store.wins_per_model()
    if wins.empty:
        st.caption(t("main.timeline.no_wins_caption"))
    else:
        st.bar_chart(wins.set_index("model_id")["wins"])
