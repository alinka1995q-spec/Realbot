"""Простой i18n: грузим дефолтные тексты из JSON-файлов, оверрайды - из BotText в БД."""

import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

LOCALES_DIR = Path(__file__).parent / "locales"
SUPPORTED_LANGS = ("ru", "kg")
DEFAULT_LANG = "ru"


@lru_cache(maxsize=8)
def _load_locale(lang: str) -> dict[str, str]:
    file = LOCALES_DIR / f"{lang}.json"
    if not file.exists():
        return {}
    with file.open("r", encoding="utf-8") as f:
        return json.load(f)


class I18N:
    def __init__(self) -> None:
        self._overrides: dict[tuple[str, str], str] = {}

    def reload_overrides(self, items: list[tuple[str, str, str]]) -> None:
        """items: список (key, lang, value)."""
        self._overrides = {(k, lang): v for k, lang, v in items}

    def t(self, key: str, lang: Optional[str] = None, **kwargs) -> str:
        lang = lang if lang in SUPPORTED_LANGS else DEFAULT_LANG
        # 1) override из БД
        val = self._overrides.get((key, lang))
        # 2) дефолт текущего языка
        if val is None:
            val = _load_locale(lang).get(key)
        # 3) дефолт основного языка
        if val is None and lang != DEFAULT_LANG:
            val = _load_locale(DEFAULT_LANG).get(key)
        # 4) сам ключ как маркер
        if val is None:
            return f"⟨{key}⟩"
        try:
            return val.format(**kwargs) if kwargs else val
        except (KeyError, IndexError):
            return val


i18n = I18N()
