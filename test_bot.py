# -*- coding: utf-8 -*-
"""Тесты на разбор сумм и верность расчётов. Запуск: python3 test_bot.py"""

import os
import tempfile

os.environ["FIN_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")

from finbot import db
from finbot.categories import builtin_category
from finbot.money import fmt, parse_amount
from finbot.parsing import (parse_debt_add, parse_debt_pay, parse_debt_set,
                            is_income, parse_edit, parse_month_word)

FAILED = []


def check(name, got, expected):
    if got != expected:
        FAILED.append(f"{name}: получили {got!r}, ждали {expected!r}")
    else:
        print(f"  ok: {name}")


# ---------- разбор сумм ----------
print("Разбор сумм:")
check("450 такси", parse_amount("450 такси"), (45000, "такси"))
check("такси 450", parse_amount("такси 450"), (45000, "такси"))
check("1 200 продукты", parse_amount("1 200 продукты"), (120000, "продукты"))
check("210.000 точка-тысячи", parse_amount("210.000 - зарплата сотрудникам"), (21000000, "- зарплата сотрудникам"))
check("1.200.000", parse_amount("1.200.000 аренда"), (120000000, "аренда"))
check("1200,50 без копеек", parse_amount("1200,50 аптека"), (120050 * 100, "аптека"))
check("450. в конце", parse_amount("такси 450."), (45000, "такси ."))
check("2.5 млн", parse_amount("2.5 млн долг"), (250000000, "долг"))
check("1,5к", parse_amount("1,5к продукты"), (150000, "продукты"))
check("10к", parse_amount("10к подарок"), (1000000, "подарок"))
check("2 млн", parse_amount("долг ипотека 2 млн"), (200000000, "долг ипотека"))
check("40 тыс", parse_amount("аванс 40 тыс"), (4000000, "аванс"))
check("+150000 зарплата", parse_amount("+150000 зарплата"), (15000000, "+ зарплата"))
check("без суммы", parse_amount("просто текст"), (None, "просто текст"))
check("ноль не сумма", parse_amount("0 такси"), (None, "0 такси"))

# ---------- форматирование ----------
print("Форматирование:")
check("fmt 45000", fmt(45000), "450 ₽")
check("fmt 120050", fmt(120050), "1 200,50 ₽")
check("fmt 15000000", fmt(15000000), "150 000 ₽")
check("fmt минус", fmt(-104800_00), "−104 800 ₽")
check("fmt плюс", fmt(104800_00, sign=True), "+104 800 ₽")

# ---------- категории ----------
print("Категории:")
check("такси", builtin_category("такси до дома"), "transport")
check("пятёрочка", builtin_category("пятёрочка"), "products")
check("аптека", builtin_category("аптека ригла"), "health")
check("шаурма", builtin_category("шаурма"), "cafe")
check("неизвестное", builtin_category("абракадабра"), "other")

# ---------- доход/долг ----------
print("Разбор команд:")
check("+ это доход", is_income("+5000 подарок"), True)
check("зарплата это доход", is_income("зарплата 150к"), True)
check("такси не доход", is_income("такси 450"), False)
check("зарплата сотрудникам не доход", is_income("зарплата сотрудникам 210000"), False)
check("зп сотрудникам категория", builtin_category("зп сотрудникам"), "staff")
check("зарплата сотрудникам категория", builtin_category("зарплата сотрудникам"), "staff")
check("долг иван", parse_debt_add("долг Иван 50000 за ремонт"), ("Иван", 5000000, "ремонт"))
check("долг без суммы", parse_debt_add("долг Иван"), "noamount")
check("погасил", parse_debt_pay("погасил Иван 10000"), ("Иван", 1000000))
check("не долг", parse_debt_add("такси 450"), None)

# ---------- расчёты по базе ----------
print("Расчёты по базе:")
db.init_db()
db.try_join(1, "Саша")
db.try_join(2, "Аня")
check("третий не входит", db.try_join(3, "Гость"), None)

M = "2026-09"
db.add_tx(1, "income", 150000_00, "other", "зарплата", M)
db.add_tx(1, "expense", 450_00, "transport", "такси", M)
db.add_tx(1, "expense", 1200_50, "products", "продукты", M)
db.add_tx(2, "expense", 320_00, "cafe", "шаурма", M)
tid = db.add_tx(2, "expense", 999_00, "other", "ошибка", M)
db.delete_tx(tid)  # удалённое не считается
db.add_tx(1, "expense", 5000_00, "fun", "кино", "2026-08")  # другой месяц

inc, exp = db.month_totals(M)
check("доход месяца", inc, 150000_00)
check("расход месяца (без удалённой и чужого месяца)", exp, 450_00 + 1200_50 + 320_00)
inc1, exp1 = db.month_totals(M, 1)
check("расход Саши", exp1, 450_00 + 1200_50)
inc2, exp2 = db.month_totals(M, 2)
check("расход Ани", exp2, 320_00)
check("сумма по людям = общей", exp1 + exp2, exp)

cats = {r["category"]: r["s"] for r in db.month_by_category(M)}
check("категории месяца", cats,
      {"products": 1200_50, "transport": 450_00, "cafe": 320_00})
check("сумма категорий = расходу", sum(cats.values()), exp)

# ---------- долги ----------
print("Долги:")
did = db.add_debt("Иван", 50000_00, "ремонт")
rem = db.pay_debt(did, 1, 10000_00)
check("остаток после 10к", rem, 40000_00)
rem = db.pay_debt(did, 2, 15000_00)
check("остаток после ещё 15к", rem, 25000_00)
d = db.get_debt(did)
check("погашено суммарно", d["paid_kop"], 25000_00)
check("долг ещё открыт", d["closed"], 0)
rem = db.pay_debt(did, 1, 25000_00)
check("закрыт в ноль", rem, 0)
check("после закрытия — closed", db.get_debt(did)["closed"], 1)
check("в открытых его нет", [x["id"] for x in db.debts_open()], [])

# ---------- сверка остатка ----------
print("Сверка остатка:")
check("парсинг сверки", parse_debt_set("остаток Банк 1280000"), ("Банк", 128000000))
check("сверка без суммы", parse_debt_set("остаток Банк"), "noamount")
check("не сверка", parse_debt_set("такси 450"), None)
did2 = db.add_debt("Банк", 1500000_00, "тест")
db.pay_debt(did2, 1, 50000_00)  # платёж 50 000, но тело у банка уменьшилось лишь на 500
db.set_debt_remaining(did2, 1499500_00)  # сверка по факту банка
d2 = db.get_debt(did2)
check("остаток после сверки", d2["principal_kop"] - d2["paid_kop"], 1499500_00)
check("сверка вверх тоже работает", d2["principal_kop"], 50000_00 + 1499500_00)
db.set_debt_remaining(did2, 0)
check("сверка в ноль закрывает", db.get_debt(did2)["closed"], 1)

# ---------- обучение категорий ----------
print("Обучение:")
db.learn_rule("вкусвилл заречный", "products")
check("выученное правило", db.learned_category("вкусвилл на юго-западной"), "products")
check("невыученное", db.learned_category("абракадабра"), None)

# ---------- правка записей ----------
print("Правка записей:")
US = [(1, "Саша"), (2, "Аня")]
check("правка суммы", parse_edit("540", US), {"amount_kop": 54000})
check("правка описания", parse_edit("такси в аэропорт", US),
      {"description": "такси в аэропорт"})
check("сумма+описание", parse_edit("540 такси в аэропорт", US),
      {"amount_kop": 54000, "description": "такси в аэропорт"})
check("смена владельца", parse_edit("это Аня", US), {"user_id": 2})
check("владелец по началу имени", parse_edit("это ан", US), {"user_id": 2})
check("неизвестный владелец", "error" in (parse_edit("это Вася", US) or {}), True)
check("перенос в август", parse_edit("август", US), {"month": "2026-08"})
check("родительный падеж", parse_edit("августа", US), {"month": "2026-08"})
check("месяц с годом", parse_edit("декабрь 2025", US), {"month": "2025-12"})
check("будущий месяц = прошлый год", parse_month_word("декабрь"), "2025-12")
check("пусто", parse_edit("  ", US), None)

tid = db.add_tx(1, "expense", 450_00, "transport", "такси", M)
old = db.get_tx(tid)
changed = db.update_tx(tid, 1, amount_kop=540_00, description="такси в аэропорт")
check("изменённые поля", changed, {"amount_kop": 540_00, "description": "такси в аэропорт"})
t = db.get_tx(tid)
check("сумма обновилась", t["amount_kop"], 540_00)
check("итог месяца пересчитался", db.month_totals(M, 1)[1],
      exp1 + 540_00)  # exp1 — расходы Саши до этой записи
check("повторная правка тем же — пусто", db.update_tx(tid, 1, amount_kop=540_00), {})
logrow = db.conn().execute("SELECT * FROM tx_log WHERE tx_id=?", (tid,)).fetchone()
check("журнал: старое", "45000" in logrow["old_json"], True)
check("журнал: новое", "54000" in logrow["new_json"], True)
changed = db.update_tx(tid, 2, user_id=2, month="2026-08")
check("владелец и месяц", changed, {"user_id": 2, "month": "2026-08"})
check("ушло из сентября", db.month_totals(M, 1)[1], exp1)
check("пришло Ане в август", db.month_totals("2026-08", 2)[1], 540_00)

db.remember_card(100, 555, tid)
check("карточка -> запись", db.card_tx(100, 555), tid)
check("чужая карточка", db.card_tx(100, 556), None)
check("последняя запись Саши", db.last_tx_of(1)["id"] != tid, True)

# ---------- зеркальные карточки и личный баланс ----------
print()
print("Зеркальные карточки и личный баланс:")
from finbot import cards, handlers, telegram

SENT, EDITED = [], []
_counter = [1000]


def fake_send(chat_id, text, markup=None):
    _counter[0] += 1
    SENT.append((chat_id, text, markup))
    return {"message_id": _counter[0]}


def fake_edit(chat_id, message_id, text, markup=None):
    EDITED.append((chat_id, message_id, text, markup))
    return {}


handlers.send, handlers.edit = fake_send, fake_edit
handlers.api = lambda *a, **k: None
handlers.cur_month = lambda: M

# users 1 и 2 существуют. Саша (1) вносит трату.
handlers.handle_message({"chat": {"id": 1}, "from": {"id": 1, "first_name": "Саша"}, "text": "320 шаурма"})
check("карточка автору и партнёру", [c for c, _, _ in SENT], [1, 2])
check("партнёр видит, кто внёс", "внёс" in SENT[1][1], True)
new_id = db.card_tx(1, 1001)
check("карточка автора привязана", new_id is not None, True)
check("зеркальная карточка привязана к той же записи", db.card_tx(2, 1002), new_id)
check("cards_of_tx: две карточки", len(db.cards_of_tx(new_id)), 2)

# Саша правит сумму reply-ем — карточка партнёра перерисовывается
SENT.clear(); EDITED.clear()
handlers.handle_message({"chat": {"id": 1}, "from": {"id": 1, "first_name": "Саша"},
                         "text": "350", "reply_to_message": {"message_id": 1001}})
check("правка: своя карточка перерисована", (1, 1001) in [(c, m) for c, m, _, _ in EDITED], True)
check("правка: карточка партнёра перерисована", (2, 1002) in [(c, m) for c, m, _, _ in EDITED], True)
check("партнёру не шлём текстовое уведомление", SENT, [])
check("в карточке партнёра новая сумма", "350 ₽" in [t for c, m, t, _ in EDITED if c == 2][0], True)

# Аня (2) правит по зеркальной карточке — у Саши тоже обновится
SENT.clear(); EDITED.clear()
handlers.handle_message({"chat": {"id": 2}, "from": {"id": 2, "first_name": "Аня"},
                         "text": "шаурма и кола", "reply_to_message": {"message_id": 1002}})
check("правка партнёром: обе карточки", sorted((c, m) for c, m, _, _ in EDITED), [(1, 1001), (2, 1002)])
check("описание обновилось", db.get_tx(new_id)["description"], "шаурма и кола")

# смена категории кнопкой у автора -> зеркало у партнёра
EDITED.clear()
handlers.handle_callback({"id": "x", "data": f"cat:{new_id}:products", "from": {"id": 1},
                          "message": {"chat": {"id": 1}, "message_id": 1001}})
check("категория: карточка партнёра перерисована", (2, 1002) in [(c, m) for c, m, _, _ in EDITED], True)
check("категория: в зеркале видна", "Продукты" in [t for c, m, t, _ in EDITED if c == 2][0], True)

# удаление у партнёра -> у автора карточка помечена удалённой
EDITED.clear()
handlers.handle_callback({"id": "x", "data": f"del:{new_id}", "from": {"id": 2},
                          "message": {"chat": {"id": 2}, "message_id": 1002}})
check("удаление: карточка автора перерисована", (1, 1001) in [(c, m) for c, m, _, _ in EDITED], True)
check("удаление: помечено", "Удалено" in [t for c, m, t, _ in EDITED if c == 1][0], True)
check("удаление: запись помечена deleted", db.get_tx(new_id)["deleted"], 1)

# личный баланс
SENT.clear()
handlers.handle_message({"chat": {"id": 2}, "from": {"id": 2, "first_name": "Аня"}, "text": "💰 Баланс"})
check("баланс — семейный по умолчанию", "вся семья" in SENT[0][1].splitlines()[0], True)
check("баланс — с разбивкой по людям", "По людям" in SENT[0][1], True)
check("баланс — есть переключатель на человека",
      SENT[0][2]["inline_keyboard"][0][1]["callback_data"], f"bal:1:{M}")
check("личный баланс — без разбивки", "По людям" in cards.balance_text(M, 2), False)
SENT.clear()
handlers.handle_message({"chat": {"id": 1}, "from": {"id": 1, "first_name": "Саша"}, "text": "📋 Выписка"})
check("выписка — семейная по умолчанию", "вся семья" in SENT[0][1].splitlines()[0], True)
EDITED.clear()
handlers.handle_callback({"id": "x", "data": f"bal:{M}", "from": {"id": 1},
                          "message": {"chat": {"id": 1}, "message_id": 5}})
check("старая кнопка bal:месяц не ломается", "вся семья" in EDITED[0][2], True)

print()
if FAILED:
    print("ПРОВАЛЕНО:")
    for f in FAILED:
        print("  " + f)
    raise SystemExit(1)
print("Все тесты прошли ✅")
