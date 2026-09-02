# -*- coding: utf-8 -*-
"""Разбор пользовательских сообщений: траты, доходы, долги, правки.
Чистые функции без обращений к сети — всё покрыто тестами."""

import re

from .dates import MONTH_RU, MONTH_RU_GEN, now_msk
from .money import parse_amount

INCOME_WORDS = ("доход", "зарплата", "аванс", "премия", "пришло", "прибыль", "поступление")
# «зарплата сотрудникам» — это расход, а не наш доход
STAFF_WORDS = ("сотрудник", "персонал", "работник")
DEBT_ADD_WORDS = ("долг", "займ", "кредит")
DEBT_PAY_WORDS = ("погасил", "погасила", "вернул", "вернула", "погашение", "оплатил долг", "оплатила долг")
DEBT_SET_WORDS = ("остаток", "сверка")


def parse_debt_add(text: str):
    """«долг Иван 50000 за ремонт» -> (title, kop, note) или None."""
    first = text.split()[0].lower() if text.split() else ""
    if first not in DEBT_ADD_WORDS:
        return None
    kop, rest = parse_amount(text)
    if kop is None:
        return "noamount"
    words = rest.split()[1:]  # без слова «долг»
    if not words:
        return "notitle"
    title = words[0].capitalize()
    note = " ".join(words[1:])
    note = re.sub(r"^(за|на|по)\s+", "", note)
    return title, kop, note


def parse_debt_pay(text: str):
    """«погасил Иван 10000» -> (query, kop) или None."""
    low = text.lower()
    if not any(low.startswith(w) for w in DEBT_PAY_WORDS):
        return None
    kop, rest = parse_amount(text)
    if kop is None:
        return "noamount"
    words = rest.split()[1:]
    query = " ".join(words) if words else ""
    return query, kop


def parse_debt_set(text: str):
    """«остаток Банк 1280000» -> (query, kop) или None. Сверка остатка с банком."""
    low = text.lower()
    if not any(low.startswith(w) for w in DEBT_SET_WORDS):
        return None
    kop, rest = parse_amount(text)
    if kop is None:
        return "noamount"
    words = rest.split()[1:]
    return (" ".join(words), kop)


def parse_month_word(text: str):
    """«август» / «августа» / «август 2026» -> 'YYYY-MM' или None.
    Без года: месяц в будущем считаем прошлогодним (правят прошлое, не будущее)."""
    m = re.fullmatch(r"([а-яё]+)(?:\s+(\d{4}))?", text.lower().strip())
    if not m:
        return None
    word, year = m.group(1), m.group(2)
    if word in MONTH_RU:
        num = MONTH_RU.index(word) + 1
    elif word in MONTH_RU_GEN:
        num = MONTH_RU_GEN.index(word) + 1
    else:
        return None
    if year:
        return f"{year}-{num:02d}"
    now = now_msk()
    y = now.year if num <= now.month else now.year - 1
    return f"{y}-{num:02d}"


def parse_edit(text: str, users_list):
    """Разбор правки (reply на карточку или «исправь …»).

    users_list — [(tg_id, name), ...]. Возвращает dict полей для update_tx,
    {"error": ...} если поняли намерение, но не смогли, или None если пусто.
    Правила: «это Аня» — смена владельца; название месяца — перенос;
    число — новая сумма; текст — новое описание (категория пересчитается)."""
    t = text.strip()
    if not t:
        return None

    m = re.fullmatch(r"это\s+(.+)", t, re.IGNORECASE)
    if m:
        q = m.group(1).lower().strip()
        for tg_id, name in users_list:
            n = name.lower()
            if n.startswith(q) or q.startswith(n):
                return {"user_id": tg_id}
        return {"error": "Не знаю такого члена семьи. Сейчас есть: "
                + ", ".join(n for _, n in users_list)}

    month = parse_month_word(t)
    if month:
        return {"month": month}

    kop, rest = parse_amount(t)
    fields = {}
    if kop is not None:
        fields["amount_kop"] = kop
    desc = rest.strip("+ ").strip() if kop is not None else t
    if desc:
        fields["description"] = desc
    if not fields:
        return None
    return fields


def is_income(text: str) -> bool:
    t = text.strip()
    if t.startswith("+"):
        return True
    low = t.lower()
    if any(w in low for w in STAFF_WORDS):
        return False
    first = low.split()[0] if low.split() else ""
    return any(first.startswith(w) for w in INCOME_WORDS)


def strip_income_words(desc: str) -> str:
    words = desc.split()
    if words and any(words[0].lower().startswith(w) for w in INCOME_WORDS):
        # «зарплата», «аванс» оставляем как описание, «доход» — убираем
        if words[0].lower().startswith("доход"):
            words = words[1:]
    return " ".join(words)
