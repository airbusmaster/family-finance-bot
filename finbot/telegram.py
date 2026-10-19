# -*- coding: utf-8 -*-
"""Тонкая обёртка над Telegram Bot API (stdlib, без зависимостей)."""

import json
import logging
import os
import socket
import time
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


# С VPS IPv6 до api.telegram.org не работает (проверено 19.10.2026), а при сбое
# IPv4 стандартный клиент ждал бы полный таймаут ещё и на IPv6-адресе.
# Оставляем только IPv4 в рамках процесса бота.
_getaddrinfo = socket.getaddrinfo


def _getaddrinfo_v4(host, port, family=0, *args, **kw):
    res = _getaddrinfo(host, port, family, *args, **kw)
    v4 = [r for r in res if r[0] == socket.AF_INET]
    return v4 or res


socket.getaddrinfo = _getaddrinfo_v4

# Повторы при сетевых сбоях (обрыв, таймаут): ответ на API-ошибку (4xx/5xx)
# не повторяем. Паузы между попытками, сек.
RETRY_DELAYS = (2, 5)


def api(method: str, **params):
    data = json.dumps(params).encode()
    req = urllib.request.Request(
        API_URL + method, data=data, headers={"Content-Type": "application/json"}
    )
    # getUpdates держит long-poll до 50 с, остальным методам хватает 20 с
    timeout = 60 if method == "getUpdates" else 20
    attempts = 1 + len(RETRY_DELAYS)
    for i in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read()).get("result")
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:300]
            log.error("API %s failed: %s %s", method, e.code, body)
            return None
        except Exception as e:
            if i + 1 < attempts:
                log.warning("API %s: %s — повтор %d/%d через %d с",
                            method, e, i + 1, len(RETRY_DELAYS), RETRY_DELAYS[i])
                time.sleep(RETRY_DELAYS[i])
            else:
                log.error("API %s failed after %d attempts: %s", method, attempts, e)
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
