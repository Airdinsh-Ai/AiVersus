# -*- coding: utf-8 -*-
#
# AiVersus – Streaming-Chat-Aufruf mit Live-Fortschritt (Evo V0.4)
# © 2026 Airdinsh (Erdinç Arslan) · MIT License · Masterschool AI Engineering Track
# Signlab@gmx.de · https://Airdinsh.com
#

"""
Chat-Aufruf über stream=True in einem Hintergrund-Thread: Der Hauptthread bleibt
frei, um die Wartezeit live anzuzeigen (on_progress-Callback).

Zwei getrennte Zeitüberschreitungen, weil NVIDIA Build (Freikontingent) vor dem
ersten Token mehrere Minuten Warteschlange haben kann, danach aber normal streamt:
- first_token_timeout_s: Geduld bis zum ersten Token (Warteschlange inklusive).
- inter_token_timeout_s: Geduld zwischen zwei Token, sobald das Streaming läuft.
Reasoning-Modelle (z.B. gpt-oss) schicken ihr "Denken" oft als eigenes Feld
(delta.reasoning_content/delta.reasoning), nicht als delta.content - das zählt
hier ebenfalls als Lebenszeichen und wird separat in `reasoning` gesammelt.

Nicht jedes NVIDIA-Build-Modell versteht jeden OpenAI-Parameter (z.B. seed oder
stream_options). Ein 400 mit einem erkannten Parameter führt zu genau einem
Retry ohne diesen Parameter - ChatCallResult.used_params/dropped_param zeigen,
was am Ende tatsächlich gesendet wurde.

Ein optionales `cancel_event` (threading.Event) erlaubt den Abbruch von außen:
wird es gesetzt, schließt call_chat_streaming den offenen Stream aktiv
(stream.close()) und gibt ein ChatCallResult mit StreamCancelled als error zurück.
"""

import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from openai import BadRequestError


class StreamCancelled(Exception):
    """Der Call wurde über cancel_event von außen abgebrochen (Stop-Button)."""


class NoFirstTokenTimeout(TimeoutError):
    """Kein erstes Token innerhalb first_token_timeout_s - strukturiert statt freiem Text,

    damit die UI (app.py) die Meldung selbst übersetzen kann (EN/DE, siehe i18n.py).
    """

    def __init__(self, elapsed_s: float):
        self.elapsed_s = elapsed_s
        super().__init__(f"no first token after {elapsed_s:.0f}s")


class NoFurtherTokenTimeout(TimeoutError):
    """Kein weiteres Token innerhalb inter_token_timeout_s - strukturiert statt freiem Text."""

    def __init__(self, elapsed_s: float):
        self.elapsed_s = elapsed_s
        super().__init__(f"no further token for {elapsed_s:.0f}s")


@dataclass
class ChatCallResult:
    ok: bool
    content: str
    reasoning: str
    tokens_in: Optional[int]
    tokens_out: Optional[int]
    reasoning_tokens: Optional[int]
    finish_reason: Optional[str]
    error: Optional[Exception]
    duration_s: float
    ttft_s: Optional[float]  # Time To First Token - enthält die NVIDIA-Warteschlange
    generation_s: Optional[float]  # duration_s - ttft_s, für eine unverzerrte Tokens/s-Rechnung
    used_params: dict = field(default_factory=dict)  # tatsächlich gesendete Parameter (inkl. stream_options)
    dropped_param: Optional[str] = None  # gesetzt, wenn ein Parameter nach 400 entfernt wurde


def _error_message_and_param(e: Exception) -> tuple:
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or ""), error.get("param")
    return str(e), None


def _find_offending_param(e: Exception, sent_params: dict) -> Optional[str]:
    """Welcher gesendete Parameter laut 400-Antwort abgelehnt wurde - None, wenn keiner erkannt wird."""
    message, param_field = _error_message_and_param(e)
    haystack = f"{param_field or ''} {message}".lower()
    for key in sent_params:
        names = ["stream_options", "include_usage"] if key == "stream_options" else [key]
        if any(name.lower() in haystack for name in names):
            return key
    return None


def _call_once(
    client, model_id: str, messages: list,
    on_progress: Optional[Callable[[float, str, bool], None]],
    first_token_timeout_s: float, inter_token_timeout_s: float,
    params: dict,
    cancel_event: Optional[threading.Event] = None,
) -> ChatCallResult:
    q: "queue.Queue" = queue.Queue()
    stream_holder: dict = {}

    def producer() -> None:
        try:
            stream = client.chat.completions.create(model=model_id, messages=messages, stream=True, **params)
            stream_holder["stream"] = stream
            for chunk in stream:
                if cancel_event is not None and cancel_event.is_set():
                    try:
                        stream.close()
                    except Exception:
                        pass
                    q.put(("cancelled", None))
                    return
                q.put(("chunk", chunk))
            q.put(("done", None))
        except Exception as exc:  # landet im Hauptthread als Fehlerergebnis, kein Traceback in der UI
            q.put(("error", exc))

    start = time.perf_counter()
    threading.Thread(target=producer, daemon=True).start()

    content_parts: list = []
    reasoning_parts: list = []
    usage = None
    finish_reason = None
    first_token_at: Optional[float] = None
    last_token_at = start
    error: Optional[Exception] = None

    while True:
        if cancel_event is not None and cancel_event.is_set():
            stream_obj = stream_holder.get("stream")
            if stream_obj is not None:
                try:
                    stream_obj.close()  # weckt einen im Netzwerk-Read blockierten Producer-Thread auf
                except Exception:
                    pass
            error = StreamCancelled("Vom Nutzer abgebrochen.")
            break

        now = time.perf_counter()
        elapsed_total = now - start
        if first_token_at is None:
            elapsed_since_token, limit = elapsed_total, first_token_timeout_s
        else:
            elapsed_since_token, limit = now - last_token_at, inter_token_timeout_s

        if elapsed_since_token >= limit:
            if first_token_at is None:
                error = NoFirstTokenTimeout(elapsed_since_token)
            else:
                error = NoFurtherTokenTimeout(elapsed_since_token)
            break

        wait = max(0.2, min(1.0, limit - elapsed_since_token))
        try:
            kind, payload = q.get(timeout=wait)
        except queue.Empty:
            if on_progress:
                on_progress(elapsed_total, "".join(content_parts), first_token_at is not None)
            continue

        if kind == "error":
            error = payload
            break
        if kind == "cancelled":
            error = StreamCancelled("Vom Nutzer abgebrochen.")
            break
        if kind == "done":
            break

        choice = payload.choices[0] if payload.choices else None
        content_piece = None
        reasoning_piece = None
        if choice is not None and choice.delta is not None:
            content_piece = choice.delta.content
            reasoning_piece = (
                getattr(choice.delta, "reasoning_content", None)
                or getattr(choice.delta, "reasoning", None)
            )
        if content_piece:
            content_parts.append(content_piece)
        if reasoning_piece:
            reasoning_parts.append(reasoning_piece)
        if content_piece or reasoning_piece:
            token_at = time.perf_counter()
            if first_token_at is None:
                first_token_at = token_at
            last_token_at = token_at
        if choice is not None and choice.finish_reason:
            finish_reason = choice.finish_reason
        if getattr(payload, "usage", None):
            usage = payload.usage
        if on_progress:
            on_progress(now - start, "".join(content_parts), first_token_at is not None)

    duration_s = round(time.perf_counter() - start, 3)
    ttft_s = round(first_token_at - start, 3) if first_token_at is not None else None
    generation_s = round(duration_s - ttft_s, 3) if ttft_s is not None else None
    content = "".join(content_parts)
    reasoning = "".join(reasoning_parts)

    reasoning_tokens = None
    tokens_in = tokens_out = None
    if usage is not None:
        tokens_in, tokens_out = usage.prompt_tokens, usage.completion_tokens
        details = getattr(usage, "completion_tokens_details", None)
        if details is not None:
            reasoning_tokens = getattr(details, "reasoning_tokens", None)

    if error is not None:
        return ChatCallResult(
            False, content, reasoning, None, None, None, finish_reason, error, duration_s, ttft_s, generation_s,
            used_params=dict(params),
        )
    return ChatCallResult(
        True, content, reasoning, tokens_in, tokens_out, reasoning_tokens,
        finish_reason, None, duration_s, ttft_s, generation_s, used_params=dict(params),
    )


def call_chat_streaming(
    client,
    model_id: str,
    messages: list,
    on_progress: Optional[Callable[[float, str, bool], None]] = None,
    first_token_timeout_s: float = 300.0,
    inter_token_timeout_s: float = 60.0,
    cancel_event: Optional[threading.Event] = None,
    **params,
) -> ChatCallResult:
    """Streamt eine Chat-Antwort in einem Hintergrund-Thread.

    `on_progress(elapsed_s, partial_text, got_first_token)` wird regelmäßig im
    Hauptthread aufgerufen, solange der Call läuft - für eine Live-Anzeige
    ("in der Warteschlange" vor dem ersten Token, danach "wartet seit X s").

    Lehnt NVIDIA Build einen Parameter mit 400 ab (nicht jedes Modell versteht
    z.B. seed), wird genau einmal ohne diesen Parameter wiederholt.

    `cancel_event` gesetzt (Stop-Button): bricht sofort ab, schließt den Stream aktiv.
    """
    attempt_params = dict(params)
    attempt_params["stream_options"] = {"include_usage": True}

    result = _call_once(
        client, model_id, messages, on_progress, first_token_timeout_s, inter_token_timeout_s,
        attempt_params, cancel_event,
    )
    if result.ok or not isinstance(result.error, BadRequestError):
        return result

    offending = _find_offending_param(result.error, attempt_params)
    if offending is None:
        return result

    retry_params = dict(attempt_params)
    retry_params.pop(offending, None)
    retried = _call_once(
        client, model_id, messages, on_progress, first_token_timeout_s, inter_token_timeout_s,
        retry_params, cancel_event,
    )
    retried.dropped_param = offending
    return retried
