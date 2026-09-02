# -*- coding: utf-8 -*-
"""Бэкап finance.db через sqlite backup API (база в WAL — cp ненадёжен).
Ротация по дню недели: finance-1.db … finance-7.db. Запуск кроном."""

import datetime
import os
import sqlite3

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "finance.db")
DST = os.path.join(BASE, "backup", f"finance-{datetime.datetime.now().strftime('%u')}.db")

os.makedirs(os.path.dirname(DST), exist_ok=True)
src = sqlite3.connect(SRC)
dst = sqlite3.connect(DST)
with dst:
    src.backup(dst)
dst.close()
src.close()
print(f"ok {DST}")
