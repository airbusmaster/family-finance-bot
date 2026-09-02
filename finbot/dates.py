# -*- coding: utf-8 -*-
"""Даты и месяцы. Всё время в боте — московское."""

from datetime import datetime, timedelta, timezone

MSK = timezone(timedelta(hours=3))

MONTH_RU = ["январь", "февраль", "март", "апрель", "май", "июнь",
            "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]
MONTH_RU_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня",
                "июля", "августа", "сентября", "октября", "ноября", "декабря"]


def now_msk() -> datetime:
    return datetime.now(MSK)


def cur_month() -> str:
    return now_msk().strftime("%Y-%m")


def month_title(month: str) -> str:
    y, m = month.split("-")
    return f"{MONTH_RU[int(m) - 1].capitalize()} {y}"


def shift_month(month: str, delta: int) -> str:
    y, m = int(month[:4]), int(month[5:7])
    m += delta
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return f"{y}-{m:02d}"
