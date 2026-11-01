# -*- coding: utf-8 -*-
#
# AiVersus – Preistabelle (Evo V0.3)
# © 2026 Airdinsh (Erdinç Arslan) · MIT License · Masterschool AI Engineering Track
# Signlab@gmx.de · https://Airdinsh.com
#

"""
Preise in USD pro 1 Million Tokens (Input, Output) aus der allerersten Version
(OpenAI/Google Gemini direkt, vor der Umstellung auf NVIDIA Build).

Dient heute nur noch als Legacy-Fallback beim "Hinzufügen" eines Modells in app.py,
falls dessen ID zufällig hier auftaucht - praktisch nie, da NVIDIA-Build-IDs anders
aussehen ("org/modell" statt "anbieter:modell"). Die eigentliche, aktuelle Preisquelle
ist die editierbare, nutzergeführte Liste in pricing.json (siehe Sidebar "LLM Pricing"
und app.py: _cost_usd()).
"""

PRICING_USD_PER_1M_TOKENS = {
    "openai:gpt-4o-mini": (0.15, 0.60),
    "openai:gpt-4.1-mini": (0.40, 1.60),
    "openai:gpt-5-mini": (0.25, 2.00),
    "google:gemini-2.5-flash": (0.30, 2.50),
    "google:gemini-2.5-pro": (1.25, 10.00),
}
