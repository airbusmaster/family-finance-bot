# -*- coding: utf-8 -*-
"""Обработка входящих сообщений и нажатий кнопок."""

from . import db
from .cards import (balance_markup, balance_text, cat_keyboard, debts_markup,
                    debts_text, describe_changes, statement_markup,
                    statement_text, tx_card)
from .categories import CAT_TITLE, builtin_category
from .dates import cur_month
from .money import fmt, parse_amount
from .parsing import (is_income, parse_debt_add, parse_debt_pay, parse_debt_set,
                      parse_edit, strip_income_words)
from .telegram import api, edit, send

HELP = (
    "Как пользоваться:\n\n"
    "<b>Трата</b> — просто напиши сумму и на что:\n"
    "  <code>450 такси</code> или <code>такси 450</code>\n"
    "  <code>1,5к продукты</code>, <code>шаурма 320</code>\n"
    "Категория подставится сама, её можно поправить кнопкой — я запомню.\n\n"
    "<b>Исправить запись</b> — ответь (reply) на её карточку:\n"
    "  <code>540</code> — новая сумма, <code>такси в аэропорт</code> — описание,\n"
    "  <code>это Аня</code> — чья трата, <code>август</code> — в какой месяц.\n"
    "Или <code>исправь 540</code> — поправит твою последнюю запись.\n\n"
    "<b>Доход</b> — с плюсом или словом:\n"
    "  <code>+150000 зарплата</code>\n"
    "  <code>аванс 40к</code>\n\n"
    "<b>Долг</b> — добавить обязательство:\n"
    "  <code>долг Иван 50000 за ремонт</code>\n"
    "<b>Погашение</b>:\n"
    "  <code>погасил Иван 10000</code>\n"
    "  или кнопка «Погасить» в списке долгов.\n"
    "<b>Сверка с банком</b> — по кредитам часть платежа уходит в проценты, "
    "поэтому раз в месяц сверяй остаток:\n"
    "  <code>остаток Банк 1280000</code>\n\n"
    "<b>Кнопки внизу</b>: Баланс — итог месяца, Выписка — траты по категориям "
    "(вся семья или по одному), Долги — остатки по обязательствам.\n\n"
    "Своё имя в отчётах: <code>/имя Саша</code>"
)

# ожидания ввода: user_id -> ("debt_pay", debt_id)
pending: dict[int, tuple] = {}


def categorize(description: str) -> str:
    return db.learned_category(description) or builtin_category(description)


def notify_partner(author_id, text):
    for u in db.users():
        if u["tg_id"] != author_id:
            send(u["tg_id"], text)


def apply_edit(chat_id, editor_id, tx, text, card_message_id=None):
    """Общий путь правки: разобрать, применить, перерисовать карточку, уведомить."""
    fields = parse_edit(text, [(x["tg_id"], x["name"]) for x in db.users()])
    if fields is None:
        send(chat_id, "Что поменять? Ответом на карточку: сумма (<code>540</code>), "
                      "описание, <code>это Аня</code> или месяц (<code>август</code>).")
        return
    if "error" in fields:
        send(chat_id, fields["error"])
        return
    if "description" in fields and tx["kind"] == "expense":
        fields["category"] = categorize(fields["description"])
    changed = db.update_tx(tx["id"], editor_id, **fields)
    if not changed:
        send(chat_id, "Так и было — ничего не поменял.")
        return
    new_tx = db.get_tx(tx["id"])
    card, markup = tx_card(new_tx)
    note = "✏️ " + describe_changes(tx, changed)
    if card_message_id:
        edit(chat_id, card_message_id, card + "\n\n" + note, markup=markup)
    else:
        r = send(chat_id, card + "\n\n" + note, markup=markup)
        if r:
            db.remember_card(chat_id, r["message_id"], tx["id"])
    u = db.get_user(editor_id)
    notify_partner(editor_id, f"✏️ {u['name']} исправил запись: {describe_changes(tx, changed)}")


def do_debt_payment(chat_id, uid, debt_id, kop):
    d = db.get_debt(debt_id)
    if d is None or d["closed"]:
        send(chat_id, "Этот долг уже закрыт.")
        return
    remaining_before = d["principal_kop"] - d["paid_kop"]
    if kop > remaining_before:
        send(chat_id, f"По долгу «{d['title']}» осталось {fmt(remaining_before)} — "
                      f"это меньше платежа {fmt(kop)}. Запишу погашение ровно на остаток.")
        kop = remaining_before
    remaining = db.pay_debt(debt_id, uid, kop)
    u = db.get_user(uid)
    if remaining <= 0:
        text = f"🎉 Долг «{d['title']}» полностью погашен!"
    else:
        text = (f"✅ Погашение по «{d['title']}»: {fmt(kop)}\n"
                f"Осталось: <b>{fmt(remaining)}</b> из {fmt(d['principal_kop'])}")
    send(chat_id, text)
    notify_partner(uid, f"💳 {u['name']} погасил {fmt(kop)} по «{d['title']}». "
                   + ("Долг закрыт 🎉" if remaining <= 0 else f"Осталось {fmt(remaining)}."))


def handle_message(msg):
    chat_id = msg["chat"]["id"]
    from_user = msg.get("from", {})
    text = (msg.get("text") or "").strip()
    if not text:
        send(chat_id, "Пока понимаю только текст: сумма и описание, например <code>450 такси</code>.")
        return

    u = db.try_join(from_user.get("id"), from_user.get("first_name") or "Без имени")
    if u is None:
        send(chat_id, "Бот семейный, места заняты 🙂", markup={"remove_keyboard": True})
        return
    uid = u["tg_id"]

    # --- ожидание суммы погашения после кнопки «Погасить» ---
    if uid in pending:
        kind, debt_id = pending.pop(uid)
        if kind == "debt_pay":
            kop, _ = parse_amount(text)
            if kop is None:
                send(chat_id, "Не вижу суммы. Напиши число, например <code>10000</code>.")
                pending[uid] = (kind, debt_id)
                return
            do_debt_payment(chat_id, uid, debt_id, kop)
            return

    # --- правка reply-ем на карточку операции ---
    reply = msg.get("reply_to_message")
    if reply:
        tx_id = db.card_tx(chat_id, reply.get("message_id"))
        if tx_id:
            tx = db.get_tx(tx_id)
            if tx is None or tx["deleted"]:
                send(chat_id, "Эта запись уже удалена.")
                return
            apply_edit(chat_id, uid, tx, text, card_message_id=reply.get("message_id"))
            return

    low = text.lower()

    # --- «исправь …» — правка своей последней записи ---
    if low.startswith("исправь"):
        rest_text = text.split(maxsplit=1)[1] if len(text.split(maxsplit=1)) > 1 else ""
        tx = db.last_tx_of(uid)
        if tx is None:
            send(chat_id, "У тебя пока нет записей — нечего исправлять.")
            return
        if not rest_text.strip():
            send(chat_id, "Что исправить? Например: <code>исправь 540</code> (сумма), "
                          "<code>исправь такси в аэропорт</code> (описание), "
                          "<code>исправь это Аня</code>, <code>исправь август</code>.")
            return
        apply_edit(chat_id, uid, tx, rest_text)
        return

    # --- команды и кнопки ---
    if low in ("/start", "start"):
        send(chat_id, f"Привет, {u['name']}! Я веду семейный бюджет.\n\n" + HELP)
        return
    if low in ("❓ помощь", "/help", "помощь"):
        send(chat_id, HELP)
        return
    if low.startswith("/имя") or low.startswith("/name"):
        name = text.split(maxsplit=1)[1].strip() if len(text.split()) > 1 else ""
        if not name:
            send(chat_id, "Напиши так: <code>/имя Саша</code>")
            return
        db.rename_user(uid, name)
        send(chat_id, f"Готово, теперь ты в отчётах — <b>{name}</b>.")
        return
    if low in ("💰 баланс", "/баланс", "баланс", "/balance"):
        m = cur_month()
        send(chat_id, balance_text(m), markup=balance_markup(m))
        return
    if low in ("📋 выписка", "/выписка", "выписка"):
        m = cur_month()
        send(chat_id, statement_text(m), markup=statement_markup(m))
        return
    if low in ("💳 долги", "/долги", "долги"):
        send(chat_id, debts_text(), markup=debts_markup())
        return

    # --- долг: добавление ---
    r = parse_debt_add(text)
    if r == "noamount":
        send(chat_id, "Не вижу суммы долга. Пример: <code>долг Иван 50000 за ремонт</code>")
        return
    if r == "notitle":
        send(chat_id, "Кому долг? Пример: <code>долг Иван 50000 за ремонт</code>")
        return
    if r:
        title, kop, note = r
        db.add_debt(title, kop, note)
        send(chat_id, f"💳 Записал долг: <b>{title}</b> — {fmt(kop)}"
                      + (f" ({note})" if note else "")
                      + "\nПогашение: <code>погасил "
                      + title + " 10000</code> или кнопкой в «Долгах».")
        notify_partner(uid, f"💳 {u['name']} добавил долг: {title} — {fmt(kop)}")
        return

    # --- долг: погашение текстом ---
    r = parse_debt_pay(text)
    if r == "noamount":
        send(chat_id, "Не вижу суммы. Пример: <code>погасил Иван 10000</code>")
        return
    if r:
        query, kop = r
        d = db.find_debt(query) if query else None
        if d is None:
            ds = db.debts_open()
            if len(ds) == 1:
                d = ds[0]
            else:
                send(chat_id, "Не понял, какой долг гасим. Открой «💳 Долги» и нажми «Погасить».",
                     markup=debts_markup())
                return
        do_debt_payment(chat_id, uid, d["id"], kop)
        return

    # --- долг: сверка остатка с банком ---
    r = parse_debt_set(text)
    if r == "noamount":
        send(chat_id, "Не вижу суммы. Пример: <code>остаток Банк 1280000</code>")
        return
    if r:
        query, kop = r
        d = db.find_debt(query) if query else None
        if d is None:
            send(chat_id, "Не понял, по какому долгу сверка. Пример: <code>остаток Банк 1280000</code>",
                 markup=debts_markup())
            return
        old_rem = d["principal_kop"] - d["paid_kop"]
        db.set_debt_remaining(d["id"], kop)
        if kop <= 0:
            send(chat_id, f"🎉 Долг «{d['title']}» закрыт по сверке.")
        else:
            diff = old_rem - kop
            arrow = "⬇️" if diff > 0 else "⬆️"
            send(chat_id, f"🔄 Сверка «{d['title']}»: остаток теперь <b>{fmt(kop)}</b>\n"
                          f"(было {fmt(old_rem)}, {arrow} {fmt(abs(diff))})")
        notify_partner(uid, f"🔄 {u['name']} сверил «{d['title']}» с банком: остаток {fmt(max(kop, 0))}")
        return

    # --- доход / трата ---
    kop, rest = parse_amount(text)
    if kop is None:
        send(chat_id, "Не вижу суммы 🤔 Напиши, например: <code>450 такси</code>\n"
                      "Или нажми «❓ Помощь».")
        return

    if is_income(text):
        desc = strip_income_words(rest).strip("+ ").strip()
        tx_id = db.add_tx(uid, "income", kop, "other", desc, cur_month())
        tx = db.get_tx(tx_id)
        card, markup = tx_card(tx)
        r = send(chat_id, card, markup=markup)
        if r:
            db.remember_card(chat_id, r["message_id"], tx_id)
        notify_partner(uid, f"💵 {u['name']}: доход {fmt(kop)}" + (f" — {desc}" if desc else ""))
        return

    desc = rest.strip()
    cat = categorize(desc) if desc else "other"
    tx_id = db.add_tx(uid, "expense", kop, cat, desc, cur_month())
    tx = db.get_tx(tx_id)
    card, markup = tx_card(tx)
    r = send(chat_id, card, markup=markup)
    if r:
        db.remember_card(chat_id, r["message_id"], tx_id)
    notify_partner(uid, f"➖ {u['name']}: {fmt(kop)}" + (f" — {desc}" if desc else "")
                   + f" · {CAT_TITLE[cat]}")


def handle_callback(cb):
    data = cb.get("data", "")
    msg = cb.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    message_id = msg.get("message_id")
    uid = cb.get("from", {}).get("id")
    api("answerCallbackQuery", callback_query_id=cb["id"])
    if not chat_id:
        return

    if data.startswith("bal:"):
        m = data[4:]
        edit(chat_id, message_id, balance_text(m), markup=balance_markup(m))
        return

    if data.startswith("st:"):
        _, scope, m = data.split(":")
        user_id = None if scope == "all" else int(scope)
        edit(chat_id, message_id, statement_text(m, user_id), markup=statement_markup(m, user_id))
        return

    if data.startswith("pick:"):
        tx_id = int(data[5:])
        edit(chat_id, message_id, "Выбери категорию:", markup=cat_keyboard(tx_id))
        return

    if data.startswith("cat:"):
        _, tx_id, cat = data.split(":")
        tx_id = int(tx_id)
        tx = db.get_tx(tx_id)
        if tx is None or tx["deleted"]:
            edit(chat_id, message_id, "Запись уже удалена.")
            return
        db.set_tx_category(tx_id, cat)
        if tx["description"]:
            db.learn_rule(tx["description"], cat)
        tx = db.get_tx(tx_id)
        card, markup = tx_card(tx)
        edit(chat_id, message_id, card + "\n\n✏️ Запомнил — дальше буду ставить сам.", markup=markup)
        return

    if data.startswith("del:"):
        tx_id = int(data[4:])
        tx = db.get_tx(tx_id)
        if tx:
            db.delete_tx(tx_id)
            edit(chat_id, message_id, f"🗑 Удалено: {fmt(tx['amount_kop'])}"
                 + (f" — {tx['description']}" if tx["description"] else ""))
        return

    if data.startswith("done:"):
        tx_id = int(data[5:])
        tx = db.get_tx(tx_id)
        if tx is None or tx["deleted"]:
            edit(chat_id, message_id, "Запись уже удалена.")
            return
        card, _ = tx_card(tx)
        edit(chat_id, message_id, card + "\n✅ Внесено")  # без markup — кнопки убираются
        m = tx["month"]
        send(chat_id, balance_text(m), markup=balance_markup(m))
        return

    if data.startswith("pay:"):
        debt_id = int(data[4:])
        d = db.get_debt(debt_id)
        if d is None or d["closed"]:
            send(chat_id, "Этот долг уже закрыт.")
            return
        rem = d["principal_kop"] - d["paid_kop"]
        pending[uid] = ("debt_pay", debt_id)
        send(chat_id, f"Сколько гасим по «{d['title']}»? Осталось {fmt(rem)}.\n"
                      f"Просто напиши сумму числом.")
        return

    if data == "debthelp":
        send(chat_id, "Добавь долг одной строкой:\n<code>долг Иван 50000 за ремонт</code>\n"
                      "<code>долг ипотека 2,5 млн</code>")
        return
