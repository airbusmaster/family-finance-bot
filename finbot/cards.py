# -*- coding: utf-8 -*-
"""Отрисовка: карточки операций, баланс, выписка, долги. Только текст и клавиатуры,
никакой отправки — этим занимаются handlers."""

from . import db
from .categories import CATEGORIES, CAT_TITLE
from .dates import month_title, shift_month
from .money import fmt


def tx_card(tx):
    u = db.get_user(tx["user_id"])
    name = u["name"] if u else "?"
    if tx["kind"] == "income":
        text = (f"💵 Доход {fmt(tx['amount_kop'])}"
                + (f" — {tx['description']}" if tx["description"] else "")
                + f"\n{name} · {month_title(tx['month'])}")
        markup = {"inline_keyboard": [[
            {"text": "🗑 Удалить", "callback_data": f"del:{tx['id']}"},
            {"text": "✅ Внести", "callback_data": f"done:{tx['id']}"},
        ]]}
    else:
        text = (f"➖ {fmt(tx['amount_kop'])}"
                + (f" — {tx['description']}" if tx["description"] else "")
                + f"\n{CAT_TITLE[tx['category']]} · {name}")
        markup = {"inline_keyboard": [[
            {"text": "✏️ Категория", "callback_data": f"pick:{tx['id']}"},
            {"text": "🗑 Удалить", "callback_data": f"del:{tx['id']}"},
            {"text": "✅ Внести", "callback_data": f"done:{tx['id']}"},
        ]]}
    return text, markup


def cat_keyboard(tx_id: int):
    rows, row = [], []
    for key, title in CATEGORIES:
        row.append({"text": title, "callback_data": f"cat:{tx_id}:{key}"})
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return {"inline_keyboard": rows}


def balance_text(month: str, user_id=None) -> str:
    """Баланс месяца: user_id — личный, None — вся семья с разбивкой по людям."""
    inc, exp = db.month_totals(month, user_id)
    if user_id:
        u = db.get_user(user_id)
        who = u["name"] if u else "?"
    else:
        who = "вся семья"
    lines = [f"💰 <b>{month_title(month)} · {who}</b>", ""]
    lines.append(f"Доходы:  <b>{fmt(inc)}</b>")
    lines.append(f"Расходы: <b>{fmt(exp)}</b>")
    lines.append(f"Остаток: <b>{fmt(inc - exp, sign=True)}</b>")
    us = db.users()
    if user_id is None and len(us) > 1:
        lines.append("")
        lines.append("По людям:")
        for u in us:
            ui, ue = db.month_totals(month, u["tg_id"])
            lines.append(f"  {u['name']}: доходы {fmt(ui)}, расходы {fmt(ue)}")
    open_debts = db.debts_open()
    if open_debts:
        total_rem = sum(d["principal_kop"] - d["paid_kop"] for d in open_debts)
        lines.append("")
        lines.append(f"💳 Открытых долгов: {len(open_debts)} на {fmt(total_rem)}")
    return "\n".join(lines)


def _scope_row(prefix: str, month: str, user_id):
    """Ряд переключателей «Вся семья / Имя / Имя»; текущий выбор помечен точками."""
    row = [{"text": ("· Вся семья ·" if not user_id else "Вся семья"),
            "callback_data": f"{prefix}:all:{month}"}]
    for u in db.users():
        mark = "· " + u["name"] + " ·" if user_id == u["tg_id"] else u["name"]
        row.append({"text": mark, "callback_data": f"{prefix}:{u['tg_id']}:{month}"})
    return row


def _nav_row(prefix: str, month: str, user_id):
    scope = str(user_id) if user_id else "all"
    return [
        {"text": "◀️ " + month_title(shift_month(month, -1)),
         "callback_data": f"{prefix}:{scope}:{shift_month(month, -1)}"},
        {"text": month_title(shift_month(month, 1)) + " ▶️",
         "callback_data": f"{prefix}:{scope}:{shift_month(month, 1)}"},
    ]


def balance_markup(month: str, user_id=None):
    return {"inline_keyboard": [_scope_row("bal", month, user_id), _nav_row("bal", month, user_id)]}


def statement_text(month: str, user_id=None) -> str:
    if user_id:
        u = db.get_user(user_id)
        who = u["name"] if u else "?"
    else:
        who = "вся семья"
    inc, exp = db.month_totals(month, user_id)
    lines = [f"📋 <b>Выписка · {month_title(month)} · {who}</b>", ""]
    lines.append(f"Доходы {fmt(inc)} · Расходы {fmt(exp)}")

    cats = db.month_by_category(month, user_id)
    if cats:
        lines.append("")
        lines.append("<b>Расходы по категориям</b>")
        for r in cats:
            share = round(r["s"] * 100 / exp) if exp else 0
            lines.append(f"{CAT_TITLE.get(r['category'], r['category'])} — {fmt(r['s'])} ({share}%)")

    txs = db.month_txs(month, user_id, limit=15)
    if txs:
        lines.append("")
        lines.append("<b>Последние операции</b>")
        for t in txs:
            u = db.get_user(t["user_id"])
            day = t["ts"][8:10] + "." + t["ts"][5:7]
            sign = "+" if t["kind"] == "income" else "−"
            desc = t["description"] or CAT_TITLE.get(t["category"], "")
            lines.append(f"{day} · {u['name'] if u else '?'} · {sign}{fmt(t['amount_kop'])} · {desc}")
    if not cats and not txs:
        lines.append("")
        lines.append("Операций пока нет.")
    return "\n".join(lines)


def statement_markup(month: str, user_id=None):
    return {"inline_keyboard": [_scope_row("st", month, user_id), _nav_row("st", month, user_id)]}


def debts_text() -> str:
    ds = db.debts_open()
    if not ds:
        return "💳 Открытых долгов нет 🎉"
    lines = ["💳 <b>Долги</b>", ""]
    total = 0
    for d in ds:
        rem = d["principal_kop"] - d["paid_kop"]
        total += rem
        pct = round(d["paid_kop"] * 100 / d["principal_kop"])
        note = f" ({d['note']})" if d["note"] else ""
        lines.append(f"<b>{d['title']}</b>{note}")
        lines.append(f"  осталось {fmt(rem)} из {fmt(d['principal_kop'])} · погашено {pct}%")
        lines.append("")
    lines.append(f"Итого к погашению: <b>{fmt(total)}</b>")
    return "\n".join(lines)


def debts_markup():
    rows = [[{"text": f"➖ Погасить: {d['title']}", "callback_data": f"pay:{d['id']}"}]
            for d in db.debts_open()]
    rows.append([{"text": "➕ Добавить долг", "callback_data": "debthelp"}])
    return {"inline_keyboard": rows}


def describe_changes(old_tx, fields) -> str:
    """Человеческий список изменений: «сумма 450 ₽ → 540 ₽»."""
    parts = []
    if "amount_kop" in fields:
        parts.append(f"сумма {fmt(old_tx['amount_kop'])} → {fmt(fields['amount_kop'])}")
    if "description" in fields:
        parts.append(f"описание «{old_tx['description'] or '—'}» → «{fields['description']}»")
    if "category" in fields:
        parts.append(f"категория {CAT_TITLE.get(old_tx['category'], '—')} → {CAT_TITLE.get(fields['category'], '—')}")
    if "user_id" in fields:
        o, n = db.get_user(old_tx["user_id"]), db.get_user(fields["user_id"])
        parts.append(f"владелец {o['name'] if o else '?'} → {n['name'] if n else '?'}")
    if "month" in fields:
        parts.append(f"месяц {month_title(old_tx['month'])} → {month_title(fields['month'])}")
    return ", ".join(parts)
