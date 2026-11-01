# -*- coding: utf-8 -*-
#
# AiVersus – Streaming-Chat-Aufruf mit Live-Fortschritt (Evo V0.4)
# © 2026 Airdinsh (Erdinç Arslan) · MIT License · Masterschool AI Engineering Track
# Signlab@gmx.de · https://Airdinsh.com
#

"""
Chat-Aufruf über stream=True in einem Hintergrund-Thread: Der Hauptthread bleibt
frei, um die Wartezeit live anzuzeigen (on_progress-Callback), und kann abbrechen,
wenn zu lange kein neues Token kommt - statt auf die volle Gesamt-Zeitüberschreitung
des Clients zu warten (das Verhalten, das zum hängenden Benchmark-Lauf führte).
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
    finish_reason: Optional[str]
    error: Optional[Exception]
    duration_s: float


def call_chat_streaming(
    client,
    model_id: str,
    messages: list,
    on_progress: Optional[Callable[[float, str], None]] = None,
    max_wait_without_token_s: float = 45.0,
    max_total_s: float = 180.0,
    **params,
) -> ChatCallResult:
    """Streamt eine Chat-Antwort in einem Hintergrund-Thread.

    `on_progress(elapsed_s, partial_text)` wird regelmäßig im Hauptthread aufgerufen,
    solange der Call läuft - für eine Live-Anzeige ("wartet seit X s"). Bricht ab,
    wenn `max_wait_without_token_s` lang kein neues Chunk kommt oder nach `max_total_s`
    insgesamt, statt stillschweigend bis zum vollen Client-Timeout zu hängen.

    Reasoning-Modelle (z.B. gpt-oss) schicken ihr "Denken" oft als eigenes Feld
    (delta.reasoning_content/delta.reasoning), nicht als delta.content - das zählt
    hier ebenfalls als Lebenszeichen und wird separat in `reasoning` gesammelt.
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
    last_token_at = start
    error: Optional[Exception] = None

    while True:
        now = time.perf_counter()
        elapsed_total = now - start
        elapsed_since_token = now - last_token_at

        if elapsed_total >= max_total_s:
            error = TimeoutError(f"Gesamt-Zeitüberschreitung nach {elapsed_total:.0f} s.")
            break
        if elapsed_since_token >= max_wait_without_token_s:
            error = TimeoutError(f"Kein Token seit {elapsed_since_token:.0f} s.")
            break

        wait = max(0.2, min(1.0, max_wait_without_token_s - elapsed_since_token))
        try:
            kind, payload = q.get(timeout=wait)
        except queue.Empty:
            if on_progress:
                on_progress(elapsed_total, "".join(content_parts))
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
            last_token_at = time.perf_counter()  # Lebenszeichen - auch reines Reasoning zählt
        if choice is not None and choice.finish_reason:
            finish_reason = choice.finish_reason
        if getattr(payload, "usage", None):
            usage = payload.usage
        if on_progress:
            on_progress(now - start, "".join(content_parts))

    duration_s = round(time.perf_counter() - start, 3)
    content = "".join(content_parts)
    reasoning = "".join(reasoning_parts)
    if error is not None:
        return ChatCallResult(False, content, reasoning, None, None, finish_reason, error, duration_s)
    return ChatCallResult(
        True, content, reasoning,
        usage.prompt_tokens if usage else None,
        usage.completion_tokens if usage else None,
        finish_reason, None, duration_s,
    )
