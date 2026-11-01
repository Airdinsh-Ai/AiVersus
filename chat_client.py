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
"""

import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional


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


def call_chat_streaming(
    client,
    model_id: str,
    messages: list,
    on_progress: Optional[Callable[[float, str, bool], None]] = None,
    first_token_timeout_s: float = 300.0,
    inter_token_timeout_s: float = 60.0,
    **params,
) -> ChatCallResult:
    """Streamt eine Chat-Antwort in einem Hintergrund-Thread.

    `on_progress(elapsed_s, partial_text, got_first_token)` wird regelmäßig im
    Hauptthread aufgerufen, solange der Call läuft - für eine Live-Anzeige
    ("in der Warteschlange" vor dem ersten Token, danach "wartet seit X s").
    """
    q: "queue.Queue" = queue.Queue()

    def producer() -> None:
        try:
            stream = client.chat.completions.create(
                model=model_id, messages=messages, stream=True,
                stream_options={"include_usage": True}, **params,
            )
            for chunk in stream:
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
        now = time.perf_counter()
        elapsed_total = now - start
        if first_token_at is None:
            elapsed_since_token, limit = elapsed_total, first_token_timeout_s
        else:
            elapsed_since_token, limit = now - last_token_at, inter_token_timeout_s

        if elapsed_since_token >= limit:
            if first_token_at is None:
                error = TimeoutError(f"Kein erstes Token nach {elapsed_since_token:.0f} s (Warteschlange?).")
            else:
                error = TimeoutError(f"Kein weiteres Token seit {elapsed_since_token:.0f} s.")
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
        )
    return ChatCallResult(
        True, content, reasoning, tokens_in, tokens_out, reasoning_tokens,
        finish_reason, None, duration_s, ttft_s, generation_s,
    )
