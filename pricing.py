# -*- coding: utf-8 -*-
#
# AiVersus – Preistabelle (Evo V0.3)
# © 2026 Airdinsh (Erdinç Arslan) · MIT License · Masterschool AI Engineering Track
# Signlab@gmx.de · https://Airdinsh.com
#

"""
Preise in USD pro 1 Million Tokens (Input, Output) — Grundlage für "Total Cost".

ACHTUNG: Richtwerte, keine live abgefragten Preise. Vor der Abgabe gegen die
aktuellen Anbieter-Seiten prüfen:
  OpenAI:  https://openai.com/api/pricing/
  Google:  https://ai.google.dev/gemini-api/docs/pricing
"""

PRICING_USD_PER_1M_TOKENS = {
    "openai:gpt-4o-mini": (0.15, 0.60),
    "openai:gpt-4.1-mini": (0.40, 1.60),
    "openai:gpt-5-mini": (0.25, 2.00),
    "google:gemini-2.5-flash": (0.30, 2.50),
    "google:gemini-2.5-pro": (1.25, 10.00),
}


def estimate_cost_usd(model_id: str, tokens_in, tokens_out) -> float:
    """Geschätzte Kosten eines Aufrufs in USD. 0.0, wenn Tokens oder Preis fehlen."""
    if tokens_in is None or tokens_out is None or model_id not in PRICING_USD_PER_1M_TOKENS:
        return 0.0
    price_in, price_out = PRICING_USD_PER_1M_TOKENS[model_id]
    return round((tokens_in * price_in + tokens_out * price_out) / 1_000_000, 6)
