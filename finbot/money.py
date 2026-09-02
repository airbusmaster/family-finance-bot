# -*- coding: utf-8 -*-
"""Деньги и разбор сумм. Все суммы храним в копейках (int) — никакого float в расчётах."""

import re

# «450», «1 200», «1200,50», «1.5к», «10к», «2 млн», «1,2 млн»
_AMOUNT_RE = re.compile(
    r"(?<![\w.,])(\d[\d ]*(?:[.,]\d{1,2})?)\s*(к|k|тыс\.?|т\.?р\.?|млн\.?|m)?(?![\w])",
    re.IGNORECASE,
)

_MULT = {
    "к": 1000, "k": 1000, "тыс": 1000, "тыс.": 1000,
    "тр": 1000, "т.р": 1000, "т.р.": 1000, "тр.": 1000,
    "млн": 1_000_000, "млн.": 1_000_000, "m": 1_000_000,
}


def parse_amount(text: str):
    """Находит первую сумму в тексте.

    Возвращает (kopecks:int, rest:str) — сумма в копейках и текст без неё,
    либо (None, text), если суммы нет.
    """
    m = _AMOUNT_RE.search(text)
    if not m:
        return None, text
    num, suffix = m.group(1), (m.group(2) or "")
    num = num.replace(" ", "").replace(",", ".")
    mult = _MULT.get(suffix.lower().replace(" ", ""), 1)
    if "." in num:
        whole, frac = num.split(".", 1)
        frac = (frac + "00")[:2]
        kop = int(whole or 0) * 100 + int(frac)
    else:
        kop = int(num) * 100
    kop *= mult
    if kop <= 0:
        return None, text
    rest = (text[: m.start()] + " " + text[m.end():]).strip()
    rest = re.sub(r"\s+", " ", rest)
    return kop, rest


def fmt(kop: int, sign: bool = False) -> str:
    """1234550 -> «12 345,50 ₽», копейки печатаем только если они есть."""
    neg = kop < 0
    kop = abs(kop)
    rub, k = divmod(kop, 100)
    s = f"{rub:,}".replace(",", " ")
    if k:
        s += f",{k:02d}"
    prefix = "−" if neg else ("+" if sign else "")
    return f"{prefix}{s} ₽"
