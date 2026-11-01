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

EMBED_RERANK_PATTERNS = ("embed", "rerank", "retriev")
QUICK_TEST_HINTS = ("8b", "3b", "mini", "small", "lite", "nano")
SEPARATOR = "──────────"

# Anzeigename -> (erwartete Namespace-Präfixe "org/", Namensmuster in der Modell-ID).
# ACHTUNG: Die Namespace-Präfixe sind eine Annahme nach dem üblichen NVIDIA-Build-Schema
# "org/modell" - noch nicht gegen den echten Katalog verifiziert. Ohne die Org-Einschränkung
# matcht z.B. "nvidia/llama-3.1-nemotron-70b-instruct" sowohl "Llama" als auch "Nemotron"
# und gewinnt durch den Namespace-Alphabetvorteil ("nvidia" > "meta") fälschlich den
# Llama-Slot - deshalb wird pro Familie auf den erwarteten Hersteller-Namespace eingegrenzt.
TOP_FAMILIES = {
    "DeepSeek": (("deepseek-ai",), "deepseek"),
    "Gemma": (("google",), "gemma"),
    "GLM": (("zai-org", "thudm", "zhipuai"), "glm"),
    "gpt-oss": (("openai",), "gpt-oss"),
    "Kimi": (("moonshotai",), "kimi"),
    "Llama": (("meta",), "llama"),
    "Mistral": (("mistralai",), "mistral"),
    "Nemotron": (("nvidia",), "nemotron"),
    "Phi": (("microsoft",), "phi"),
    "Qwen": (("qwen", "alibaba"), "qwen"),
}


def _is_chat_model(model_id: str) -> bool:
    lowered = model_id.lower()
    return not any(pattern in lowered for pattern in EMBED_RERANK_PATTERNS)


def _natural_key(model_id: str):
    """Versions-/Größenangaben numerisch vergleichen (3.3 > 3.1, 70b > 8b) statt alphabetisch."""
    tokens = re.split(r"(\d+\.\d+|\d+)", model_id.lower())
    return [float(t) if re.fullmatch(r"\d+(\.\d+)?", t) else t for t in tokens]


def fetch_chat_models(client: OpenAI) -> list:
    """Alle Chat-Modell-IDs von NVIDIA Build, Embedding-/Rerank-Modelle ausgefiltert."""
    response = client.models.list()
    return sorted(m.id for m in response.data if _is_chat_model(m.id))


def latest_per_family(chat_models: list) -> dict:
    """{Anzeigename: Modell-ID} - je Top-Familie das laut Namensmuster neueste Modell.

    Eingrenzung auf den erwarteten Hersteller-Namespace, damit z.B. eine
    Nemotron-Finetune von Llama nicht versehentlich den Llama-Slot gewinnt.
    """
    picks = {}
    for label, (orgs, pattern) in TOP_FAMILIES.items():
        matches = [
            m for m in chat_models
            if pattern in m.lower() and any(m.lower().startswith(f"{org}/") for org in orgs)
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


def pick_quick_test_model(chat_models: list) -> str | None:
    """Ein kleines/schnelles Modell aus dem Katalog für den Verbindungstest - keine feste ID."""
    if not chat_models:
        return None
    for hint in QUICK_TEST_HINTS:
        matches = sorted(m for m in chat_models if hint in m.lower())
        if matches:
            return matches[0]
    return sorted(chat_models)[0]
