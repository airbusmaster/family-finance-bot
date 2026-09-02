# -*- coding: utf-8 -*-
"""Точка входа: TG_TOKEN=<токен> python3 -m finbot"""

import json
import logging
import os
import time

from . import db
from .handlers import handle_callback, handle_message
from .telegram import api

log = logging.getLogger("finbot")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not os.environ.get("TG_TOKEN"):
        raise SystemExit("Нужен TG_TOKEN (токен бота от BotFather) в переменных окружения")

    db.init_db()
    api("setMyCommands", commands=[
        {"command": "balance", "description": "💰 Баланс месяца"},
        {"command": "help", "description": "❓ Как пользоваться"},
    ])
    log.info("started")

    offset = int(db.state_get("offset", 0))
    while True:
        updates = api("getUpdates", offset=offset, timeout=50,
                      allowed_updates=["message", "callback_query"])
        if updates is None:
            time.sleep(3)
            continue
        for upd in updates:
            offset = upd["update_id"] + 1
            db.state_set("offset", offset)
            try:
                if "message" in upd:
                    handle_message(upd["message"])
                elif "callback_query" in upd:
                    handle_callback(upd["callback_query"])
            except Exception:
                log.exception("update failed: %s", json.dumps(upd)[:400])


if __name__ == "__main__":
    main()
