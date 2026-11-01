# -*- coding: utf-8 -*-
#
# AiVersus – Zweisprachigkeit (Evo V0.4)
# © 2026 Airdinsh (Erdinç Arslan) · MIT License · Masterschool AI Engineering Track
# Signlab@gmx.de · https://Airdinsh.com
#

"""
Lädt i18n/<lang>.json und baut daraus eine kleine t(key, **kwargs)-Funktion.
Englisch ist Standard und zugleich der Fallback, falls in der gewählten Sprache
(oder in Englisch selbst) ein Schlüssel fehlt - dann erscheint der Schlüssel
selbst, statt dass die Seite abstürzt.
"""

import json
from pathlib import Path

_DIR = Path(__file__).parent / "i18n"
_cache: dict = {}


def load_translations(lang: str) -> dict:
    if lang not in _cache:
        path = _DIR / f"{lang}.json"
        with open(path, "r", encoding="utf-8") as f:
            _cache[lang] = json.load(f)
    return _cache[lang]


def make_translator(lang: str):
    translations = load_translations(lang)
    fallback = translations if lang == "en" else load_translations("en")

    def t(key: str, **kwargs) -> str:
        text = translations.get(key, fallback.get(key, key))
        return text.format(**kwargs) if kwargs else text

    return t
