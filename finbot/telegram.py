# -*- coding: utf-8 -*-
"""Тонкая обёртка над Telegram Bot API (stdlib, без зависимостей)."""

import json
import logging
import os
import urllib.request

log = logging.getLogger("finbot")

API_URL = f"https://api.telegram.org/bot{os.environ.get('TG_TOKEN', '')}/"

KB_MAIN = {
    "keyboard": [
        [{"text": "💰 Баланс"}, {"text": "📋 Выписка"}],
        [{"text": "💳 Долги"}, {"text": "❓ Помощь"}],
    ],
    "resize_keyboard": True,
    "is_persistent": True,
}


def api(method: str, **params):
    data = json.dumps(params).encode()
    req = urllib.request.Request(
        API_URL + method, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read()).get("result")
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:300]
        log.error("API %s failed: %s %s", method, e.code, body)
    except Exception as e:
        log.error("API %s failed: %s", method, e)
    return None


def send(chat_id, text, markup=None):
    p = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    p["reply_markup"] = markup if markup is not None else KB_MAIN
    return api("sendMessage", **p)


def edit(chat_id, message_id, text, markup=None):
    p = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    if markup is not None:
        p["reply_markup"] = markup
    return api("editMessageText", **p)
