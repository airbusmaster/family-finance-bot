# -*- coding: utf-8 -*-
"""SQLite-хранилище. Все суммы — копейки (int), все итоги считает SQL по базе,
никаких промежуточных сумм в памяти — расчёт всегда сходится с данными."""

import json
import os
import sqlite3
import threading

# База лежит в корне проекта (рядом с пакетом), на сервере это /opt/family-finance-bot/finance.db
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("FIN_DB", os.path.join(_ROOT, "finance.db"))

_local = threading.local()


def conn() -> sqlite3.Connection:
    c = getattr(_local, "conn", None)
    if c is None:
        c = sqlite3.connect(DB_PATH, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=30000")
        c.execute("PRAGMA foreign_keys=ON")
        _local.conn = c
    return c


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    tg_id      INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    joined_ts  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tx (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(tg_id),
    kind        TEXT NOT NULL CHECK (kind IN ('expense', 'income')),
    amount_kop  INTEGER NOT NULL CHECK (amount_kop > 0),
    category    TEXT NOT NULL DEFAULT 'other',
    description TEXT NOT NULL DEFAULT '',
    month       TEXT NOT NULL,              -- 'YYYY-MM' по Москве на момент внесения
    ts          TEXT NOT NULL DEFAULT (datetime('now', '+3 hours')),  -- МСК
    deleted     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_tx_month ON tx(month, deleted);

CREATE TABLE IF NOT EXISTS debts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT NOT NULL,            -- кому/что: «Иван», «ипотека»
    principal_kop INTEGER NOT NULL CHECK (principal_kop > 0),
    note          TEXT NOT NULL DEFAULT '',
    created_ts    TEXT NOT NULL DEFAULT (datetime('now')),
    closed        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS debt_payments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    debt_id    INTEGER NOT NULL REFERENCES debts(id),
    user_id    INTEGER NOT NULL REFERENCES users(tg_id),
    amount_kop INTEGER NOT NULL CHECK (amount_kop > 0),
    ts         TEXT NOT NULL DEFAULT (datetime('now', '+3 hours'))  -- МСК
);

CREATE TABLE IF NOT EXISTS cat_rules (       -- выученные правила категоризации
    word     TEXT PRIMARY KEY,               -- первое слово описания, lower
    category TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS state (           -- мелкие ключи (offset поллинга и т.п.)
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS card_msgs (       -- карточка в чате -> операция (для правки reply-ем)
    chat_id    INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    tx_id      INTEGER NOT NULL,
    PRIMARY KEY (chat_id, message_id)
);

CREATE TABLE IF NOT EXISTS tx_log (          -- журнал правок: что было -> что стало
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    tx_id     INTEGER NOT NULL,
    editor_id INTEGER NOT NULL,
    old_json  TEXT NOT NULL,
    new_json  TEXT NOT NULL,
    ts        TEXT NOT NULL DEFAULT (datetime('now', '+3 hours'))  -- МСК
);
"""


def init_db():
    conn().executescript(SCHEMA)
    conn().commit()


# ---------- users ----------

MAX_USERS = int(os.environ.get("FIN_MAX_USERS", "2"))

# Белый список Telegram-ID (через запятую в env). Если задан — доступ ТОЛЬКО этим ID,
# правило «первые двое» отключается. Защищает даже при сбросе базы.
ALLOWED_IDS = {int(x) for x in os.environ.get("FIN_ALLOWED_IDS", "").replace(" ", "").split(",") if x}


def get_user(tg_id: int):
    return conn().execute("SELECT * FROM users WHERE tg_id=?", (tg_id,)).fetchone()


def users():
    return conn().execute("SELECT * FROM users ORDER BY joined_ts").fetchall()


def try_join(tg_id: int, name: str):
    """Если задан FIN_ALLOWED_IDS — пускаем только их. Иначе первые MAX_USERS
    написавших привязываются автоматически, дальше — закрыто."""
    if ALLOWED_IDS and tg_id not in ALLOWED_IDS:
        return None
    u = get_user(tg_id)
    if u:
        return u
    if not ALLOWED_IDS and len(users()) >= MAX_USERS:
        return None
    conn().execute("INSERT INTO users(tg_id, name) VALUES (?,?)", (tg_id, name))
    conn().commit()
    return get_user(tg_id)


def rename_user(tg_id: int, name: str):
    conn().execute("UPDATE users SET name=? WHERE tg_id=?", (name, tg_id))
    conn().commit()


# ---------- transactions ----------

def add_tx(user_id, kind, amount_kop, category, description, month):
    cur = conn().execute(
        "INSERT INTO tx(user_id, kind, amount_kop, category, description, month) "
        "VALUES (?,?,?,?,?,?)",
        (user_id, kind, amount_kop, category, description, month),
    )
    conn().commit()
    return cur.lastrowid


def get_tx(tx_id):
    return conn().execute("SELECT * FROM tx WHERE id=?", (tx_id,)).fetchone()


def set_tx_category(tx_id, category):
    conn().execute("UPDATE tx SET category=? WHERE id=?", (category, tx_id))
    conn().commit()


def delete_tx(tx_id):
    conn().execute("UPDATE tx SET deleted=1 WHERE id=?", (tx_id,))
    conn().commit()


def month_totals(month, user_id=None):
    """(income_kop, expense_kop) за месяц; user_id=None — по всем."""
    q = ("SELECT kind, COALESCE(SUM(amount_kop),0) s FROM tx "
         "WHERE month=? AND deleted=0")
    args = [month]
    if user_id:
        q += " AND user_id=?"
        args.append(user_id)
    q += " GROUP BY kind"
    res = {r["kind"]: r["s"] for r in conn().execute(q, args)}
    return res.get("income", 0), res.get("expense", 0)


def month_by_category(month, user_id=None):
    q = ("SELECT category, COALESCE(SUM(amount_kop),0) s FROM tx "
         "WHERE month=? AND deleted=0 AND kind='expense'")
    args = [month]
    if user_id:
        q += " AND user_id=?"
        args.append(user_id)
    q += " GROUP BY category ORDER BY s DESC"
    return conn().execute(q, args).fetchall()


def month_txs(month, user_id=None, limit=100):
    q = "SELECT * FROM tx WHERE month=? AND deleted=0"
    args = [month]
    if user_id:
        q += " AND user_id=?"
        args.append(user_id)
    q += " ORDER BY ts DESC, id DESC LIMIT ?"
    args.append(limit)
    return conn().execute(q, args).fetchall()


TX_EDITABLE = {"amount_kop", "description", "category", "user_id", "month"}


def update_tx(tx_id, editor_id, **fields):
    """Правит запись и пишет журнал. Возвращает dict реально изменённых полей."""
    old = get_tx(tx_id)
    if old is None:
        return {}
    fields = {k: v for k, v in fields.items() if k in TX_EDITABLE and old[k] != v}
    if not fields:
        return {}
    sets = ", ".join(f"{k}=?" for k in fields)
    conn().execute(f"UPDATE tx SET {sets} WHERE id=?", (*fields.values(), tx_id))
    conn().execute(
        "INSERT INTO tx_log(tx_id, editor_id, old_json, new_json) VALUES (?,?,?,?)",
        (tx_id, editor_id,
         json.dumps({k: old[k] for k in fields}, ensure_ascii=False),
         json.dumps(fields, ensure_ascii=False)),
    )
    conn().commit()
    return fields


def last_tx_of(user_id):
    return conn().execute(
        "SELECT * FROM tx WHERE user_id=? AND deleted=0 ORDER BY id DESC LIMIT 1",
        (user_id,),
    ).fetchone()


def remember_card(chat_id, message_id, tx_id):
    conn().execute(
        "INSERT INTO card_msgs(chat_id, message_id, tx_id) VALUES (?,?,?) "
        "ON CONFLICT(chat_id, message_id) DO UPDATE SET tx_id=excluded.tx_id",
        (chat_id, message_id, tx_id),
    )
    conn().commit()


def card_tx(chat_id, message_id):
    r = conn().execute(
        "SELECT tx_id FROM card_msgs WHERE chat_id=? AND message_id=?",
        (chat_id, message_id),
    ).fetchone()
    return r["tx_id"] if r else None


def cards_of_tx(tx_id):
    """Все карточки операции во всех чатах (у автора и у партнёра) — для перерисовки."""
    return conn().execute(
        "SELECT chat_id, message_id FROM card_msgs WHERE tx_id=? ORDER BY rowid",
        (tx_id,),
    ).fetchall()


# ---------- category rules ----------

def learned_category(description: str):
    word = (description.lower().split() or [""])[0]
    if not word:
        return None
    r = conn().execute("SELECT category FROM cat_rules WHERE word=?", (word,)).fetchone()
    return r["category"] if r else None


def learn_rule(description: str, category: str):
    word = (description.lower().split() or [""])[0]
    if len(word) < 3:  # по коротким словам не учимся — слишком шумно
        return
    conn().execute(
        "INSERT INTO cat_rules(word, category) VALUES (?,?) "
        "ON CONFLICT(word) DO UPDATE SET category=excluded.category",
        (word, category),
    )
    conn().commit()


# ---------- debts ----------

def add_debt(title, principal_kop, note=""):
    cur = conn().execute(
        "INSERT INTO debts(title, principal_kop, note) VALUES (?,?,?)",
        (title, principal_kop, note),
    )
    conn().commit()
    return cur.lastrowid


def debts_open():
    """Открытые долги с остатком: remaining = principal - SUM(payments)."""
    return conn().execute(
        "SELECT d.*, COALESCE((SELECT SUM(p.amount_kop) FROM debt_payments p "
        "WHERE p.debt_id=d.id), 0) AS paid_kop "
        "FROM debts d WHERE d.closed=0 ORDER BY d.created_ts"
    ).fetchall()


def get_debt(debt_id):
    return conn().execute(
        "SELECT d.*, COALESCE((SELECT SUM(p.amount_kop) FROM debt_payments p "
        "WHERE p.debt_id=d.id), 0) AS paid_kop FROM debts d WHERE d.id=?",
        (debt_id,),
    ).fetchone()


def find_debt(query: str):
    """Поиск открытого долга по началу названия (без регистра)."""
    q = query.lower().strip()
    for d in debts_open():
        if d["title"].lower().startswith(q) or q.startswith(d["title"].lower()):
            return d
    return None


def pay_debt(debt_id, user_id, amount_kop):
    """Погашение. Если остаток закрыт полностью — долг закрывается.
    Возвращает остаток после платежа."""
    conn().execute(
        "INSERT INTO debt_payments(debt_id, user_id, amount_kop) VALUES (?,?,?)",
        (debt_id, user_id, amount_kop),
    )
    d = get_debt(debt_id)
    remaining = d["principal_kop"] - d["paid_kop"]
    if remaining <= 0:
        conn().execute("UPDATE debts SET closed=1 WHERE id=?", (debt_id,))
    conn().commit()
    return remaining


def set_debt_remaining(debt_id, remaining_kop):
    """Сверка с банком: выставить текущий остаток как есть.
    principal подгоняется так, чтобы remaining = principal - paid."""
    d = get_debt(debt_id)
    new_principal = d["paid_kop"] + remaining_kop
    conn().execute("UPDATE debts SET principal_kop=?, closed=? WHERE id=?",
                   (max(new_principal, 1), 1 if remaining_kop <= 0 else 0, debt_id))
    conn().commit()


def close_debt(debt_id):
    conn().execute("UPDATE debts SET closed=1 WHERE id=?", (debt_id,))
    conn().commit()


# ---------- state ----------

def state_get(key, default=None):
    r = conn().execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
    return r["value"] if r else default


def state_set(key, value):
    conn().execute(
        "INSERT INTO state(key, value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )
    conn().commit()
