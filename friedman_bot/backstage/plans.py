"""
Тарифы Backstage.

Пока оплата не настроена (ни у одного платного тарифа нет ссылки Stripe), всё
работает как раньше: бесплатно, с дневными лимитами. Как только владелец вставит
в админке ссылки оплаты, включается схема «пробный период → платный тариф».
Клиенты, которых владелец завёл сам (source=admin), тарифом не ограничиваются —
для них есть месячный бюджет ИИ.
"""

import os
import json
from datetime import datetime, timedelta

import store

DEFAULT_PLANS = {
    "trial": {"name": "Trial", "days": 14, "chat_daily": int(os.environ.get("BACKSTAGE_FREE_DAILY_CHAT", "25")),
              "deep_daily": int(os.environ.get("BACKSTAGE_FREE_DAILY_DEEP", "2")), "tokens_daily": 400_000, "usd_month": 3},
    "free": {"name": "Free", "chat_daily": int(os.environ.get("BACKSTAGE_FREE_DAILY_CHAT", "25")),
             "deep_daily": int(os.environ.get("BACKSTAGE_FREE_DAILY_DEEP", "2")), "tokens_daily": 400_000, "usd_month": 3},
    "basic": {"name": "Basic", "price": "19 € / month", "chat_daily": 60, "deep_daily": 4, "link": "",
              "tokens_daily": 1_500_000, "usd_month": 15},
    "pro": {"name": "Pro", "price": "49 € / month", "chat_daily": 200, "deep_daily": 12, "link": "",
            "tokens_daily": 5_000_000, "usd_month": 40},
}
# Потолки всей платформы и одного запроса — защита от «проснулся со счётом на тысячи»
DEFAULT_CAPS = {"platform_tokens_daily": 20_000_000, "platform_usd_daily": 20.0,
                "request_tokens_chat": 300_000, "request_tokens_deep": 1_000_000}


def caps():
    c = dict(DEFAULT_CAPS)
    try:
        c.update({k: v for k, v in json.loads(store.meta_get("caps", "") or "{}").items() if k in c})
    except Exception:
        pass
    return c
PAID = ("basic", "pro")
PERIOD_DAYS = 32  # оплаченный месяц + запас на задержку продления


def get_plans():
    plans = json.loads(json.dumps(DEFAULT_PLANS))
    try:
        for k, v in json.loads(store.meta_get("plans", "") or "{}").items():
            if k in plans and isinstance(v, dict):
                plans[k].update(v)
    except Exception:
        pass
    return plans


def payments_on(plans=None):
    plans = plans or get_plans()
    return any((plans[k].get("link") or "").startswith("https://") for k in PAID)


def status(c):
    """Текущий тариф клиента: {plan, name, until, days_left, expired, chat_daily, deep_daily}.
    chat_daily=None — без дневных лимитов."""
    plans = get_plans()
    today = datetime.now().strftime("%Y-%m-%d")
    plan, until = (c.get("plan") or ""), (c.get("plan_until") or "")
    if plan in PAID and until >= today:
        p = plans[plan]
        return {"plan": plan, "name": p["name"], "until": until, "expired": False,
                "chat_daily": p["chat_daily"], "deep_daily": p["deep_daily"],
                "tokens_daily": p.get("tokens_daily"), "usd_month": p.get("usd_month")}
    if (c.get("source") or "admin") == "admin" and not plan:
        return {"plan": "owner", "name": "Agency", "expired": False, "chat_daily": None, "deep_daily": None}
    on = payments_on(plans)
    t = plans["trial"]
    try:
        start = datetime.fromisoformat((c.get("created") or today)[:19])
    except ValueError:
        start = datetime.now()
    end = (start + timedelta(days=int(t.get("days") or 14))).strftime("%Y-%m-%d")
    if on and end >= today:
        left = (datetime.fromisoformat(end) - datetime.fromisoformat(today)).days
        return {"plan": "trial", "name": t["name"], "until": end, "days_left": left, "expired": False,
                "chat_daily": t["chat_daily"], "deep_daily": t["deep_daily"],
                "tokens_daily": t.get("tokens_daily"), "usd_month": t.get("usd_month")}
    if on:
        return {"plan": "expired", "name": t["name"], "until": end, "expired": True, "chat_daily": 0, "deep_daily": 0}
    f = plans["free"]
    return {"plan": "free", "name": f["name"], "expired": False, "chat_daily": f["chat_daily"], "deep_daily": f["deep_daily"],
            "tokens_daily": f.get("tokens_daily"), "usd_month": f.get("usd_month")}


def offers(c):
    """Платные тарифы для экрана выбора — со ссылкой оплаты, помеченной кодом клиента:
    по client_reference_id вебхук Stripe понимает, кому и какой тариф включить."""
    plans = get_plans()
    out = []
    for k in PAID:
        p = plans[k]
        link = (p.get("link") or "").strip()
        if not link.startswith("https://"):
            continue
        sep = "&" if "?" in link else "?"
        out.append({"id": k, "name": p["name"], "price": p.get("price", ""), "chat_daily": p["chat_daily"],
                    "deep_daily": p["deep_daily"], "url": f"{link}{sep}client_reference_id={c['slug']}__{k}"})
    return out


def activate(client_id, plan, days=PERIOD_DAYS):
    until = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    store.update_client(client_id, plan=plan, plan_until=until)
    return until
