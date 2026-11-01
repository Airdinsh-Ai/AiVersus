# -*- coding: utf-8 -*-
#
# AiVersus – NVIDIA-Build-Modellkatalog (Evo V0.4)
# © 2026 Airdinsh (Erdinç Arslan) · MIT License · Masterschool AI Engineering Track
# Signlab@gmx.de · https://Airdinsh.com
#

"""
Lädt den Chat-Modellkatalog live von NVIDIA Build (models.list()) und baut daraus
die Dropdown-Reihenfolge: Top 10 bekannteste Modellfamilien (je nach Namensmuster
das aktuell neueste Modell, alphabetisch), Trennlinie, Rest alphabetisch.

Bewusst keine fest eingetragenen Modell-IDs: NVIDIA Build entfernt/ersetzt Modelle
(siehe meta/llama-3.1-8b-instruct, inzwischen 410 Gone) - alles kommt live aus dem Katalog.
"""

import re

from openai import OpenAI

# Nicht-Chat-Modelle, die trotzdem im Katalog auftauchen: Embedding/Rerank sowie
# Guard-/Safety-/Moderation-, Dokument-Parse- und Reward-Modelle (keine normalen
# Chat-Antworten) und reine Bild-zu-Text-Modelle (OCR/Caption).
EXCLUDE_PATTERNS = (
    "embed", "rerank", "retriev",
    "guard", "safety", "moderation", "nemoguard",
    "parse", "reward",
    "ocr", "caption",
)
QUICK_TEST_HINTS = ("8b", "3b", "mini", "small", "lite", "nano")
SEPARATOR = "──────────"

# Anzeigename -> (erwartete Namespace-Präfixe "org/", mögliche Namensmuster in der Modell-ID).
# ACHTUNG: Namespace-Präfixe und Namensmuster sind Annahmen nach dem üblichen NVIDIA-Build-
# Schema "org/modell" - gegen den echten Katalog (Katalog-Diagnose) zu verifizieren.
# Die Org-Einschränkung verhindert, dass z.B. "nvidia/llama-3.1-nemotron-70b-instruct"
# fälschlich den Llama-Slot gewinnt statt eines echten Meta-Llama-Modells. Bei Mistral
# sind mehrere Namensmuster nötig, weil Mistral AIs Flaggschiff "mixtral" heißt, nicht
# "mistral" - eine reine Teilstring-Suche nach "mistral" würde es verfehlen.
TOP_FAMILIES = {
    "DeepSeek": (("deepseek-ai",), ("deepseek",)),
    "Gemma": (("google",), ("gemma",)),
    "GLM": (("zai-org", "thudm", "zhipuai"), ("glm",)),
    "gpt-oss": (("openai",), ("gpt-oss",)),
    "Kimi": (("moonshotai",), ("kimi",)),
    "Llama": (("meta",), ("llama",)),
    "Mistral": (("mistralai",), ("mistral", "mixtral", "pixtral")),
    "Nemotron": (("nvidia",), ("nemotron",)),
    "Phi": (("microsoft",), ("phi",)),
    "Qwen": (("qwen", "alibaba"), ("qwen",)),
}


def _is_chat_model(model_id: str) -> bool:
    lowered = model_id.lower()
    return not any(pattern in lowered for pattern in EXCLUDE_PATTERNS)


def _has_token(model_id: str, keyword: str) -> bool:
    """`keyword` als eigenes Namenssegment - verhindert Fehltreffer wie 'recurrentgemma' für 'gemma'."""
    return re.search(rf"(?<![a-z]){re.escape(keyword)}(?![a-z])", model_id.lower()) is not None


def _natural_key(model_id: str):
    """Versions-/Größenangaben numerisch vergleichen (3.3 > 3.1, 70b > 8b) statt alphabetisch."""
    tokens = re.split(r"(\d+\.\d+|\d+)", model_id.lower())
    return [float(t) if re.fullmatch(r"\d+(\.\d+)?", t) else t for t in tokens]


def fetch_chat_models(client: OpenAI) -> list:
    """Alle Chat-Modell-IDs von NVIDIA Build, Nicht-Chat-Modelle (siehe EXCLUDE_PATTERNS) ausgefiltert."""
    response = client.models.list()
    return sorted(m.id for m in response.data if _is_chat_model(m.id))


def latest_per_family(chat_models: list) -> dict:
    """{Anzeigename: Modell-ID} - je Top-Familie das laut Namensmuster neueste Modell.

    Eingrenzung auf den erwarteten Hersteller-Namespace plus Wortgrenzen-Suche, damit
    weder eine Nemotron-Finetune von Llama den Llama-Slot gewinnt noch z.B.
    "recurrentgemma" den Gemma-Slot.
    """
    picks = {}
    for label, (orgs, keywords) in TOP_FAMILIES.items():
        matches = [
            m for m in chat_models
            if any(m.lower().startswith(f"{org}/") for org in orgs)
            and any(_has_token(m, kw) for kw in keywords)
        ]
        if matches:
            picks[label] = max(matches, key=_natural_key)
    return picks


def build_dropdown_options(chat_models: list) -> list:
    """Top 10 (alphabetisch nach Anzeigename), Trennlinie, Rest (alphabetisch)."""
    if not chat_models:
        return []
    top = latest_per_family(chat_models)
    top_ids = set(top.values())
    top_sorted = [top[label] for label in sorted(top, key=str.lower)]
    rest_sorted = sorted(m for m in chat_models if m not in top_ids)
    if not top_sorted:
        return rest_sorted
    if not rest_sorted:
        return top_sorted
    return top_sorted + [SEPARATOR] + rest_sorted


def pick_quick_test_candidates(chat_models: list, limit: int = 5) -> list:
    """Bis zu `limit` kandidaten für den Verbindungstest, kleine/schnelle Modelle zuerst.

    Mehrere Kandidaten statt einer festen ID: Taucht ein Modell im Katalog auf, ist aber
    für den Account nicht freigeschaltet (404), probiert der Aufrufer den nächsten.
    """
    if not chat_models:
        return []
    ranked, seen = [], set()
    for hint in QUICK_TEST_HINTS:
        for m in sorted(m for m in chat_models if hint in m.lower()):
            if m not in seen:
                ranked.append(m)
                seen.add(m)
    for m in sorted(chat_models):
        if m not in seen:
            ranked.append(m)
            seen.add(m)
    return ranked[:limit]


def pick_quick_test_model(chat_models: list) -> str | None:
    """Ein kleines/schnelles Modell aus dem Katalog für den Verbindungstest - keine feste ID."""
    candidates = pick_quick_test_candidates(chat_models, limit=1)
    return candidates[0] if candidates else None
