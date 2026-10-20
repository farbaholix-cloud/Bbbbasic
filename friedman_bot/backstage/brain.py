"""
Мозг Backstage — вызовы Claude через официальный SDK (anthropic) по ключу API.

Отличие от системы Фридмана: там боты звали `claude` CLI по личной подписке
владельца. Для платформы, которой пользуются клиенты агентства, нужен ключ
Claude API (console.anthropic.com) с предоплаченным балансом — каждый вызов
считается в долларах и записывается в usage по клиенту.

Два способа работы:
  • по подписке (по умолчанию, пока нет ключа API) — через `claude` CLI с OAuth-токеном
    владельца, как боты Фридмана. Ничего не докупается, лимиты — лимиты подписки.
  • по ключу Claude API — если в .env задан ANTHROPIC_API_KEY: расход в $ по клиентам,
    месячные бюджеты, самые мощные модели.

Модели в режиме API (меняются в .env или для отдельного клиента в админке):
  BACKSTAGE_MODEL_CHAT  — повседневный чат с командой, по умолчанию claude-sonnet-5-5
                          (в разы дешевле Opus, для переписки с командой хватает)
  BACKSTAGE_MODEL_DEEP  — «Глубокий анализ», по умолчанию claude-opus-5-5;
                          claude-fable-5-1 мощнее, но вдвое дороже — включается через .env
"""
import os
import re
import json
import base64
import logging
import time
from datetime import datetime

try:
    import anthropic
except ImportError:  # библиотека ещё ставится — панель работает, чат ответит ошибкой
    anthropic = None

import store
import i18n

log = logging.getLogger("backstage.brain")

HERE = os.path.dirname(os.path.abspath(__file__))
AGENTS_DIR = os.path.join(HERE, "agents")
PACKS_DIR = os.path.join(HERE, "packs")

MODEL_CHAT = os.environ.get("BACKSTAGE_MODEL_CHAT", "claude-sonnet-5-5")
MODEL_DEEP = os.environ.get("BACKSTAGE_MODEL_DEEP", "claude-opus-5-5")
EFFORT_CHAT = os.environ.get("BACKSTAGE_EFFORT_CHAT", "medium")
EFFORT_DEEP = os.environ.get("BACKSTAGE_EFFORT_DEEP", "high")

# ─── Экономия токенов ────────────────────────────────────────────────────────
# История: последние N сообщений, длинные ответы обрезаются — старые разборы
# по 5 000 знаков иначе едут в каждый следующий запрос.
HIST_MSGS = int(os.environ.get("BACKSTAGE_HISTORY_MSGS", "10"))
HIST_CHARS = int(os.environ.get("BACKSTAGE_HISTORY_CHARS", "1500"))
# Веб-поиск — самое дорогое: в обычном чате он есть только у тех, чья работа —
# искать (скаут и грантрайтер); в глубоком анализе — у всей команды.
CHAT_WEB_AGENTS = set(os.environ.get("BACKSTAGE_CHAT_WEB", "ruben,hanna,tarik,chuck").split(","))
MAX_ASKS_CHAT = int(os.environ.get("BACKSTAGE_MAX_ASKS_CHAT", "2"))
MAX_ASKS_DEEP = int(os.environ.get("BACKSTAGE_MAX_ASKS_DEEP", "4"))
SPECIALIST_ANSWER_CHARS = 3500
MAX_TOOL_ROUNDS = 12

# $ за 1M токенов: вход, выход, чтение кэша. Запись в кэш (5 мин) = 1.25 × вход.
PRICES = {
    "claude-fable-5-1": (10.0, 50.0, 0.25),
    "claude-fable-5":   (10.0, 50.0, 0.25),
    "claude-opus-5-5":  (4.0, 20.0, 0.20),
    "claude-opus-5":    (5.0, 25.0, 0.50),
    "claude-opus-4-8":  (5.0, 25.0, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
}
WEB_SEARCH_PRICE = 10.0 / 1000  # $ за один поисковый запрос

FALLBACK_BETA = "server-side-fallback-2026-07-01"
WEB_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 8}

AGENTS = json.load(open(os.path.join(AGENTS_DIR, "agents.json"), encoding="utf-8"))

_client = None


def client():
    global _client
    if anthropic is None:
        raise RuntimeError("библиотека anthropic ещё не установлена на сервере — попробуй через пару минут")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("команда ещё не подключена — владельцу нужно прислать Секретарю ключ Claude API (sk-ant-…)")
    if _client is None:
        # Ключ берётся из ANTHROPIC_API_KEY (.env рядом с сервером)
        _client = anthropic.Anthropic(max_retries=3)
    return _client


class BudgetExceeded(Exception):
    pass


CLAUDE_BIN = os.environ.get("CLAUDE_BIN") or os.path.expanduser("~/.local/bin/claude")
CLI_MODEL_CHAT = os.environ.get("BACKSTAGE_CLI_MODEL_CHAT", "sonnet")
CLI_MODEL_DEEP = os.environ.get("BACKSTAGE_CLI_MODEL_DEEP", "opus")


def backend():
    """'api' — есть ключ Claude API; иначе 'cli' — работаем по подписке владельца."""
    return "api" if os.environ.get("ANTHROPIC_API_KEY") else "cli"


# ─── Системный промпт агента ─────────────────────────────────────────────────

def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def _packs(agent_id):
    """Справочные материалы: packs/_all/*.md — всем агентам, packs/<agent>/*.md — одному.
    Сюда кладутся обезличенные базы знаний (например, справочник немецкого права
    из legal_kb Фридмана без личных данных)."""
    out = []
    for sub in ("_all", agent_id):
        d = os.path.join(PACKS_DIR, sub)
        if os.path.isdir(d):
            for fn in sorted(os.listdir(d)):
                if fn.endswith(".md"):
                    out.append(f"## Справочник: {fn[:-3]}\n\n{_read(os.path.join(d, fn))}")
    return "\n\n".join(out)


def system_prompt(agent_id):
    """Стабильная часть — одинакова для всех клиентов и между ходами, поэтому
    кэшируется (cache_control). Всё изменчивое (дата, дашборд, профиль) идёт
    в последнее сообщение пользователя, чтобы не ломать префикс кэша."""
    a = AGENTS[agent_id]
    team = "\n".join(f"- {v['name']} ({k}) — {v['role']}" for k, v in AGENTS.items())
    parts = [
        _read(os.path.join(AGENTS_DIR, "_common.md")),
        f"## Состав команды\n\n{team}",
        f"## Твоя роль: {a['name']}, {a['role']}\n\n" + _read(os.path.join(AGENTS_DIR, f"{agent_id}.md")),
        _packs(agent_id),
    ]
    return [{"type": "text", "text": "\n\n".join(p for p in parts if p),
             "cache_control": {"type": "ephemeral"}}]


def _compact_widget(w):
    """Виджет для контекста: только то, что нужно агенту, без хвостов истории."""
    d = w["data"] or {}
    if w["kind"] == "list":
        items = d.get("items") or []
        d = {"items": [i for i in items if not i.get("done")][-15:], "done_count": sum(1 for i in items if i.get("done"))}
    elif w["kind"] == "chart":
        d = {"labels": (d.get("labels") or [])[-12:],
             "series": [{"name": x.get("name"), "values": (x.get("values") or [])[-12:]} for x in d.get("series") or []]}
    elif w["kind"] == "table":
        d = {"rows": (d.get("rows") or [])[-15:]}
    elif w["kind"] == "board":
        d = {"cards": (d.get("cards") or [])[-30:]}
    s = json.dumps(d, ensure_ascii=False)
    if len(s) > 1200:
        s = s[:1200] + "…"
    return f'- id={w["id"]} [{w["kind"]}] «{w["title"]}» config={json.dumps(w["config"], ensure_ascii=False)} data={s}'


def survey_text(c):
    """Подробная анкета клиента — сжатое резюме (собирается при сохранении)."""
    try:
        return (json.loads(c.get("survey") or "{}").get("summary") or "")[:3500]
    except Exception:
        return ""


def context_block(c, agent_id, lite=False):
    """lite — для специалистов и второго прохода Майи: профиль и анкета, а дашборд
    только списком id и названий (без данных), без базы опыта."""
    widgets = store.list_widgets(c["id"])
    sv = survey_text(c)
    lines = [
        i18n.lang_rule(c.get("lang")),
        f"СЕГОДНЯ: {datetime.now().strftime('%Y-%m-%d, %A')}",
        f"КЛИЕНТ: {c['name']}",
        f"ПРОФИЛЬ ПРАКТИКИ:\n{c['profile'] or '(не заполнен — узнай у клиента и предложи сохранить в заметку «Профиль практики»)'}",
    ]
    if sv:
        lines.append("ПОДРОБНАЯ АНКЕТА КЛИЕНТА:\n" + sv)
    if lite:
        lines.append("ДАШБОРД (id и названия):\n" + ("\n".join(f'- id={w["id"]} [{w["kind"]}] «{w["title"]}»' for w in widgets) or "(пусто)"))
    else:
        lines.append("ДАШБОРД КЛИЕНТА:\n" + ("\n".join(_compact_widget(w) for w in widgets) or "(пусто)"))
        ins = store.insights_for(c["id"], limit=12)
        if ins:
            lines.append("БАЗА ОПЫТА (свои выводы клиента и общий плейбук агентства):\n" + "\n".join(
                f"- [{'общий' if i['shared'] else 'свой'}] {i['title']}: {i['body'][:240]}" for i in ins))
        if agent_id in ("maya", "hanna", "ben"):
            apps = [a for a in store.list_apps(c["id"]) if a["status"] not in ("won", "rejected")][:10]
            if apps:
                lines.append("ЗАЯВКИ В РАБОТЕ:\n" + "\n".join(
                    f"- id={a['id']} {a['title']} ({a['org']}) · {a['status']} · {a['deadline'] or '—'}" for a in apps))
            files = store.list_files(c["id"])[:12]
            if files:
                lines.append("МАТЕРИАЛЫ КЛИЕНТА (сейф): " + "; ".join(f"{f['name']} [{f['kind']}]" for f in files))
        if agent_id == "chuck":
            try:
                import security
                rep = security.last_report(c)
                if security.client_site(c) and (time.time() - rep.get("ts", 0) > 86400):
                    security.run_client(c, force=True)  # свежий пассивный отчёт перед разговором (без ИИ, секунды)
                    rep = security.last_report(c)
                if rep.get("site"):
                    lines.append(f"ПАССИВНАЯ ПРОВЕРКА САЙТА {rep['site']} ({rep.get('date')}): " + (
                        "; ".join(i18n.sec_line("en", f) for f in rep.get("findings", [])) or "no findings"))
            except Exception as e:
                log.warning("chuck context: %s", e)
        if agent_id in ("ruben", "hanna"):
            # уже найденное радаром: сначала смотри сюда, а не ищи заново (дешевле и быстрее)
            try:
                import proactive
                opps = store.match_opportunities(-1, proactive.crafts(c), proactive.regions(proactive.country(c)), 8,
                                                 datetime.now().strftime("%Y-%m-%d"))
            except Exception:
                opps = []
            if opps:
                lines.append("РАДАР (общий каталог агентства, уже проверено):\n" + "\n".join(
                    f"- {o['title']} ({o['org']}) · {o['deadline'] or 'rolling'} · {o['url']}" for o in opps))
        if backend() == "api":
            budget = c["monthly_budget"] or 0
            lines.append(f"БЮДЖЕТ ИИ: потрачено ${store.spent_this_month(c['id']):.2f} из ${budget:.2f} в этом месяце.")
    lines.append(f"REMINDER: reply in {i18n.LANG_NAME[i18n.norm(c.get('lang'))]}. Be concise: no filler, no repeating the question.")
    return "\n\n".join(lines)


def trim_history(hist):
    out = []
    for m in (hist or [])[-HIST_MSGS:]:
        t = m["text"]
        out.append({**m, "text": t if len(t) <= HIST_CHARS else t[:HIST_CHARS] + " […]"})
    return out


def web_allowed(agent_id, deep):
    a = AGENTS[agent_id]
    if deep:
        return bool(a.get("web") or a.get("lead"))
    return agent_id in CHAT_WEB_AGENTS


# ─── Инструменты ─────────────────────────────────────────────────────────────

def _obj(props, required):
    return {"type": "object", "properties": props, "required": required}


DASH_TOOLS = [
    {"name": "dashboard_add_widget",
     "description": "Создать виджет на дашборде клиента. kind: kpi | chart | table | board | list | note. "
                    "Форматы data: kpi {value, delta}; chart {labels:[...], series:[{name, values:[...]}]}; "
                    "table {rows:[[...]]}; board {cards:[{id, col, text}]}; list {items:[{id, text, date, done}]}; "
                    "note {text}. Форматы config: kpi {unit, goal}; chart {type: line|bar|pie|doughnut, unit}; "
                    "table {columns:[...]}; board {columns:[...]}.",
     "input_schema": _obj({
         "kind": {"type": "string", "enum": list(store.WIDGET_KINDS)},
         "title": {"type": "string"},
         "size": {"type": "string", "enum": ["s", "m", "l"]},
         "config": {"type": "object"},
         "data": {"type": "object"}}, ["kind", "title"])},
    {"name": "dashboard_update_widget",
     "description": "Изменить виджет: заголовок, config и/или data целиком (передавай полный новый объект).",
     "input_schema": _obj({
         "widget_id": {"type": "integer"}, "title": {"type": "string"},
         "size": {"type": "string", "enum": ["s", "m", "l"]},
         "config": {"type": "object"}, "data": {"type": "object"}}, ["widget_id"])},
    {"name": "dashboard_delete_widget",
     "description": "Удалить виджет. Только если клиент явно попросил.",
     "input_schema": _obj({"widget_id": {"type": "integer"}}, ["widget_id"])},
    {"name": "board_add_card",
     "description": "Добавить карточку на доску проектов. column — индекс колонки (0 — первая).",
     "input_schema": _obj({"widget_id": {"type": "integer"}, "text": {"type": "string"},
                           "column": {"type": "integer"}}, ["widget_id", "text"])},
    {"name": "board_move_card",
     "description": "Переложить карточку доски в другую колонку.",
     "input_schema": _obj({"widget_id": {"type": "integer"}, "card_id": {"type": "integer"},
                           "column": {"type": "integer"}}, ["widget_id", "card_id", "column"])},
    {"name": "list_add_item",
     "description": "Добавить пункт в список (дедлайн, заявка, задача). date — YYYY-MM-DD, если есть.",
     "input_schema": _obj({"widget_id": {"type": "integer"}, "text": {"type": "string"},
                           "date": {"type": "string"}}, ["widget_id", "text"])},
    {"name": "chart_add_point",
     "description": "Добавить или обновить точку графика: подпись по оси X (например «2026-10») и значение серии.",
     "input_schema": _obj({"widget_id": {"type": "integer"}, "label": {"type": "string"},
                           "value": {"type": "number"}, "series": {"type": "string"}},
                          ["widget_id", "label", "value"])},
    {"name": "kpi_set",
     "description": "Обновить значение KPI.",
     "input_schema": _obj({"widget_id": {"type": "integer"}, "value": {"type": "number"},
                           "delta": {"type": "string"}}, ["widget_id", "value"])},
    {"name": "table_add_row",
     "description": "Добавить строку в таблицу (ячейки по порядку колонок).",
     "input_schema": _obj({"widget_id": {"type": "integer"},
                           "cells": {"type": "array", "items": {"type": "string"}}}, ["widget_id", "cells"])},
    {"name": "save_insight",
     "description": "Сохранить вывод в базу опыта агентства: коротко, обезличенно (без имён, сумм договоров "
                    "и контактов клиента), с тегами через запятую.",
     "input_schema": _obj({"title": {"type": "string"}, "body": {"type": "string"},
                           "tags": {"type": "string"}}, ["title", "body"])},
    {"name": "opportunity_add",
     "description": "Сохранить найденную в интернете возможность (конкурс, грант, резиденцию, open call, заказ) в общий "
                    "каталог агентства — её увидят радар и другие клиенты с тем же ремеслом. Только проверенные, с действующей ссылкой.",
     "input_schema": _obj({"title": {"type": "string"}, "org": {"type": "string"}, "url": {"type": "string"},
                           "deadline": {"type": "string"}, "amount": {"type": "string"},
                           "region": {"type": "string", "enum": ["de", "at", "ch", "ua", "eu", "intl"]},
                           "summary": {"type": "string"}}, ["title", "url"])},
    {"name": "email_draft",
     "description": "Подготовить письмо внешнему адресату (фонд, организатор, заказчик, пресса). Письмо НЕ уходит: "
                    "клиент видит черновик под твоим ответом, правит и сам нажимает «Отправить». Адрес бери с официального "
                    "сайта (контакты, Impressum); не нашёл — оставь to пустым и скажи об этом. Пиши на языке адресата.",
     "input_schema": _obj({"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"},
                           "app_id": {"type": "integer"}}, ["subject", "body"])},
    {"name": "app_save",
     "description": "Учёт заявок клиента (вкладка «Заявки» в рабочей папке). Без id — новая заявка, с id — обновить. "
                    "status: idea | preparing | submitted | won | rejected. Заводи, когда клиент решил подаваться.",
     "input_schema": _obj({"id": {"type": "integer"}, "title": {"type": "string"}, "org": {"type": "string"},
                           "url": {"type": "string"}, "deadline": {"type": "string"}, "status": {"type": "string"},
                           "note": {"type": "string"}}, [])},
]

ASK_TOOL = {
    "name": "ask_specialist",
    "description": "Поручить задачу специалисту команды и получить его ответ. Специалист не видит переписку — "
                   "передай всю нужную информацию в task. agent: " +
                   ", ".join(f"{k} ({v['role']})" for k, v in AGENTS.items() if not v.get("lead")),
    "input_schema": _obj({"agent": {"type": "string", "enum": [k for k, v in AGENTS.items() if not v.get("lead")]},
                          "task": {"type": "string"}}, ["agent", "task"]),
}


def tools_for(agent_id, allow_delegate=True, web=True):
    t = list(DASH_TOOLS)
    if AGENTS[agent_id].get("lead") and allow_delegate:
        t.append(ASK_TOOL)
    if web:
        t.append(dict(WEB_TOOL))
    return t


def _wid(cid, inp, kind=None):
    w = store.get_widget(cid, int(inp["widget_id"]))
    if not w:
        raise ValueError(f"виджет {inp['widget_id']} не найден")
    if kind and w["kind"] != kind:
        raise ValueError(f"виджет {w['id']} — это {w['kind']}, а не {kind}")
    return w


def run_tool(c, agent_id, name, inp, ctx):
    cid = c["id"]
    if name == "dashboard_add_widget":
        wid = store.add_widget(cid, inp["kind"], inp["title"], inp.get("config"), inp.get("data"), inp.get("size", "m"))
        ctx["changed"] = True
        return f"создан виджет id={wid}"
    if name == "dashboard_update_widget":
        _wid(cid, inp)
        store.update_widget(cid, int(inp["widget_id"]), inp.get("title"), inp.get("config"), inp.get("data"), inp.get("size"))
        ctx["changed"] = True
        return "виджет обновлён"
    if name == "dashboard_delete_widget":
        _wid(cid, inp)
        store.delete_widget(cid, int(inp["widget_id"]))
        ctx["changed"] = True
        return "виджет удалён"
    if name == "board_add_card":
        w = _wid(cid, inp, "board")
        cards = w["data"].get("cards", [])
        new_id = max([x.get("id", 0) for x in cards] + [0]) + 1
        col = max(0, min(int(inp.get("column", 0)), len(w["config"].get("columns", [1])) - 1))
        cards.append({"id": new_id, "col": col, "text": inp["text"]})
        store.update_widget(cid, w["id"], data={**w["data"], "cards": cards})
        ctx["changed"] = True
        return f"карточка id={new_id} добавлена"
    if name == "board_move_card":
        w = _wid(cid, inp, "board")
        cards = w["data"].get("cards", [])
        for card in cards:
            if card.get("id") == int(inp["card_id"]):
                card["col"] = int(inp["column"])
                store.update_widget(cid, w["id"], data={**w["data"], "cards": cards})
                ctx["changed"] = True
                return "карточка перенесена"
        raise ValueError("карточка не найдена")
    if name == "list_add_item":
        w = _wid(cid, inp, "list")
        items = w["data"].get("items", [])
        new_id = max([x.get("id", 0) for x in items] + [0]) + 1
        items.append({"id": new_id, "text": inp["text"], "date": inp.get("date", ""), "done": False})
        store.update_widget(cid, w["id"], data={**w["data"], "items": items})
        ctx["changed"] = True
        return f"пункт id={new_id} добавлен"
    if name == "chart_add_point":
        w = _wid(cid, inp, "chart")
        d = w["data"]
        labels = d.setdefault("labels", [])
        series = d.setdefault("series", [])
        sname = inp.get("series") or (series[0]["name"] if series else "Значение")
        s = next((x for x in series if x["name"] == sname), None)
        if s is None:
            s = {"name": sname, "values": [None] * len(labels)}
            series.append(s)
        if inp["label"] not in labels:
            labels.append(inp["label"])
            for x in series:
                x.setdefault("values", []).append(None)
        i = labels.index(inp["label"])
        while len(s["values"]) < len(labels):
            s["values"].append(None)
        s["values"][i] = inp["value"]
        if all(re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", str(x)) for x in labels):
            # даты по оси X держим по порядку, даже если точку добавили задним числом
            order = sorted(range(len(labels)), key=lambda j: labels[j])
            d["labels"] = [labels[j] for j in order]
            for x in series:
                x["values"] = [(x["values"] + [None] * len(labels))[j] for j in order]
        store.update_widget(cid, w["id"], data=d)
        ctx["changed"] = True
        return "точка добавлена"
    if name == "kpi_set":
        w = _wid(cid, inp, "kpi")
        store.update_widget(cid, w["id"], data={**w["data"], "value": inp["value"], "delta": inp.get("delta", "")})
        ctx["changed"] = True
        return "KPI обновлён"
    if name == "table_add_row":
        w = _wid(cid, inp, "table")
        rows = w["data"].get("rows", [])
        rows.append([str(x) for x in inp["cells"]])
        store.update_widget(cid, w["id"], data={**w["data"], "rows": rows})
        ctx["changed"] = True
        return "строка добавлена"
    if name == "save_insight":
        iid = store.add_insight(cid, agent_id, inp["title"], inp["body"], inp.get("tags", ""))
        return f"сохранено в базу опыта (id={iid})"
    if name == "opportunity_add":
        d = str(inp.get("deadline") or "")
        if d and (not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) or d < datetime.now().strftime("%Y-%m-%d")):
            inp = {**inp, "deadline": ""}
        crafts = [x for x in (c.get("craft") or "").split(",") if x] or ["other"]
        oid = store.add_opportunity(inp, crafts[0], inp.get("region") or "intl")
        for extra in crafts[1:]:
            store.add_opportunity(inp, extra, inp.get("region") or "intl")
        store.mark_delivered(cid, [oid])  # клиент уже знает о ней из чата — радар не пришлёт повторно
        return f"возможность id={oid} в каталоге"
    if name == "email_draft":
        to = str(inp.get("to") or "").strip()
        if to and not re.fullmatch(r"[^@\s,;]+@[^@\s,;]+\.[a-z]{2,}", to, re.I):
            to = ""
        eid = store.add_email(cid, agent_id, to, str(inp.get("subject") or ""), str(inp.get("body") or ""),
                              inp.get("app_id") or 0)
        ctx.setdefault("emails", []).append(eid)
        return f"черновик письма id={eid} ждёт согласования клиента (сам не отправляй и не говори, что отправлено)"
    if name == "app_save":
        aid = store.save_app(cid, inp)
        ctx["changed"] = True
        return f"заявка id={aid} сохранена"
    if name == "ask_specialist":
        sub = inp["agent"]
        if sub not in AGENTS or AGENTS[sub].get("lead"):
            raise ValueError("нет такого специалиста")
        limit = MAX_ASKS_DEEP if ctx.get("deep") else MAX_ASKS_CHAT
        if over_request_cap():
            raise ValueError("потолок токенов на этот ответ исчерпан — сведи итог из того, что есть")
        if len(ctx.get("consulted", [])) >= limit:
            raise ValueError(f"лимит: не больше {limit} специалистов на один ответ — сведи итог сама")
        ctx.setdefault("consulted", []).append(sub)
        answer = run_agent(c, sub, inp["task"], history=[], model=ctx["model"], effort=ctx["effort"],
                           kind=f"specialist:{sub}", allow_delegate=False, ctx=ctx, lite=True)
        return answer[:SPECIALIST_ANSWER_CHARS]
    raise ValueError(f"неизвестный инструмент {name}")


# ─── Цикл агента ─────────────────────────────────────────────────────────────

def cost_of(model, u):
    pin, pout, pcache = PRICES.get(model, PRICES["claude-opus-5-5"])
    return (u["input"] * pin + u["output"] * pout + u["cache_read"] * pcache
            + u["cache_write"] * pin * 1.25) / 1e6 + u["web"] * WEB_SEARCH_PRICE


def _usage(resp):
    u = resp.usage
    stu = getattr(u, "server_tool_use", None)
    return {"input": u.input_tokens or 0, "output": u.output_tokens or 0,
            "cache_read": u.cache_read_input_tokens or 0, "cache_write": u.cache_creation_input_tokens or 0,
            "web": (getattr(stu, "web_search_requests", 0) or 0) if stu else 0}


FREE_DAILY_CHAT = int(os.environ.get("BACKSTAGE_FREE_DAILY_CHAT", "25"))
FREE_DAILY_DEEP = int(os.environ.get("BACKSTAGE_FREE_DAILY_DEEP", "2"))


import threading as _threading
_req = _threading.local()  # счётчик токенов текущего запроса клиента (один поток — один ответ)


def _log_usage(cid, kind, model, u, cost):
    """Все вызовы модели пишутся отсюда: и в базу, и в счётчик текущего запроса."""
    store.log_usage(cid, kind, model, u, cost)
    _req.tokens = getattr(_req, "tokens", 0) + u.get("input", 0) + u.get("output", 0) + u.get("cache_write", 0) \
        + u.get("cache_read", 0) // 10


def over_request_cap():
    cap = getattr(_req, "cap", 0)
    return bool(cap) and getattr(_req, "tokens", 0) >= cap


def check_platform(lang=None):
    """Общий потолок на день для всей платформы (включая радар) — иначе наплыв людей = неограниченный счёт."""
    import plans
    cp = plans.caps()
    if store.tokens_today(None) >= cp["platform_tokens_daily"] or (
            backend() == "api" and store.usd_today() >= cp["platform_usd_daily"]):
        raise BudgetExceeded(i18n.t(lang, "platform_pause"))


def check_quota(c, deep=False):
    """Бесплатные аккаунты (саморегистрация, демо) работают на подписке владельца —
    дневной лимит не даёт одному человеку или боту выжечь её за всех."""
    import plans
    check_platform(c.get("lang"))
    st = plans.status(c)
    if st["expired"]:
        raise BudgetExceeded(i18n.t(c.get("lang"), "trial_over"))
    if st["chat_daily"] is None:
        return
    if st.get("tokens_daily") and store.tokens_today(c["id"]) >= st["tokens_daily"]:
        raise BudgetExceeded(i18n.t(c.get("lang"), "quota_tokens"))
    used = store.requests_today(c["id"])
    if deep and used.get("deep", 0) >= st["deep_daily"]:
        raise BudgetExceeded(i18n.t(c.get("lang"), "quota_deep", n=st["deep_daily"]))
    if used.get("chat", 0) + used.get("deep", 0) >= st["chat_daily"]:
        raise BudgetExceeded(i18n.t(c.get("lang"), "quota_chat", n=st["chat_daily"]))


def check_budget(c):
    if backend() != "api":
        return  # по подписке денег не считаем — работаем в её лимитах
    import plans
    budget = float(c["monthly_budget"] or 0)
    if budget <= 0:  # 0 больше не значит «без лимита»: берём месячный потолок тарифа
        budget = float(plans.status(c).get("usd_month") or 0)
    if budget > 0 and store.spent_this_month(c["id"]) >= budget:
        raise BudgetExceeded(i18n.t(c.get("lang"), "budget_out", b=f"{budget:.2f}"))


def _call(model, effort, system, tools, messages, max_tokens):
    """Один запрос со стримингом (длинные ответы самой мощной модели идут минутами —
    стрим не даёт упасть по таймауту) и серверным фолбэком на случай отказа модели."""
    kw = dict(model=model, max_tokens=max_tokens, system=system, messages=messages,
              output_config={"effort": effort}, betas=[FALLBACK_BETA], fallbacks="default")
    if tools:
        kw["tools"] = tools
    try:
        with client().beta.messages.stream(**kw) as s:
            return s.get_final_message()
    except TypeError:
        # Старый SDK на сервере ещё не знает fallbacks/output_config — шлём их в теле запроса
        for k in ("output_config", "fallbacks", "betas"):
            kw.pop(k, None)
        with client().messages.stream(**kw, extra_headers={"anthropic-beta": FALLBACK_BETA},
                                      extra_body={"output_config": {"effort": effort}, "fallbacks": "default"}) as s:
            return s.get_final_message()


def run_agent(c, agent_id, user_text, history=None, model=None, effort=None, kind="chat",
              attachments=None, allow_delegate=True, ctx=None, max_tokens=16000, lite=False):
    """Один ход агента: контекст + история + сообщение → ответ текстом.
    Пишет расход по каждому запросу. Дашборд агент меняет через инструменты."""
    check_budget(c)
    model = model or c.get("model_chat") or MODEL_CHAT
    effort = effort or EFFORT_CHAT
    ctx = ctx if ctx is not None else {}
    ctx.setdefault("model", model)
    ctx.setdefault("effort", effort)
    ctx.setdefault("deep", kind == "deep")

    messages = []
    for m in trim_history(history):
        messages.append({"role": "user" if m["role"] == "user" else "assistant", "content": m["text"]})
    content = []
    for a in attachments or []:
        mt = a.get("media_type", "")
        if mt.startswith("image/"):
            content.append({"type": "image", "source": {"type": "base64", "media_type": mt, "data": a["data"]}})
        elif mt == "application/pdf":
            content.append({"type": "document", "title": a.get("name", "файл"),
                            "source": {"type": "base64", "media_type": mt, "data": a["data"]}})
        elif a.get("text") is not None:
            content.append({"type": "document", "title": a.get("name", "файл"),
                            "source": {"type": "text", "media_type": "text/plain", "data": a["text"]}})
    content.append({"type": "text", "text": f"<context>\n{context_block(c, agent_id, lite=lite)}\n</context>\n\n{user_text}"})
    messages.append({"role": "user", "content": content})

    system = system_prompt(agent_id)
    tools = tools_for(agent_id, allow_delegate=allow_delegate, web=web_allowed(agent_id, ctx["deep"]))
    resp = None
    capped = False
    for rnd in range(MAX_TOOL_ROUNDS):
        if rnd and over_request_cap():
            capped = True  # потолок токенов на один ответ — отдаём, что успели
            break
        try:
            resp = _call(model, effort, system, tools, messages, max_tokens)
        except Exception as e:
            if anthropic is None or not isinstance(e, anthropic.BadRequestError):
                raise
            # Модель без поддержки веб-поиска этой версии — повторяем без него
            if "web_search" in str(e) and any(t.get("name") == "web_search" for t in tools):
                log.warning("web_search не принят моделью %s, повтор без поиска: %s", model, e)
                tools = [t for t in tools if t.get("name") != "web_search"]
                continue
            raise
        u = _usage(resp)
        _log_usage(c["id"], kind, resp.model or model, u, cost_of(resp.model or model, u))
        messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason == "refusal":
            return i18n.t(c.get("lang"), "refused")
        if resp.stop_reason == "pause_turn":
            continue  # серверный поиск взял паузу — отправляем как есть, он продолжит
        if resp.stop_reason != "tool_use":
            break
        results = []
        for b in resp.content:
            if b.type != "tool_use":
                continue
            try:
                out = run_tool(c, agent_id, b.name, b.input, ctx)
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": str(out)})
            except BudgetExceeded:
                raise
            except Exception as e:
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": f"Ошибка: {e}", "is_error": True})
        messages.append({"role": "user", "content": results})
        check_budget(c)

    text = "\n\n".join(b.text for b in (resp.content if resp else []) if b.type == "text").strip()
    if capped:
        text += "\n\n" + i18n.t(c.get("lang"), "request_cap")
    if resp is not None and resp.stop_reason == "max_tokens":
        text += "\n\n" + i18n.t(c.get("lang"), "cut")
    return text or i18n.t(c.get("lang"), "empty_reply")


def chat(client_id, agent_id, text, attachments=None, deep=False, display=None):
    """Точка входа для веб-панели и Telegram-моста. Сохраняет переписку."""
    import plans
    c = store.get_client(client_id)
    check_quota(c, deep)
    if agent_id not in AGENTS:
        agent_id = "maya"
    cp = plans.caps()
    _req.tokens, _req.cap = 0, cp["request_tokens_deep" if deep else "request_tokens_chat"]
    try:
        return _chat(c, client_id, agent_id, text, attachments, deep, display)
    finally:
        _req.cap = 0  # фоновые задачи (радар) в этом потоке потолком запроса не ограничиваем


def _chat(c, client_id, agent_id, text, attachments, deep, display):
    hist = store.history(client_id, agent_id, limit=HIST_MSGS)
    note = ""
    if attachments:
        note = "\n\n📎 " + ", ".join(a.get("name", i18n.t(c.get("lang"), "file")) for a in attachments)
    store.add_message(client_id, agent_id, "user", (display or text) + note, {"deep": deep})
    ctx = {}
    if backend() == "cli":
        model = CLI_MODEL_DEEP if deep else CLI_MODEL_CHAT
        answer = cli_agent(c, agent_id, text, hist, deep=deep, attachments=attachments, ctx=ctx)
    elif deep:
        model = c.get("model_deep") or MODEL_DEEP
        answer = run_agent(c, agent_id, text, hist, model=model, effort=EFFORT_DEEP, kind="deep",
                           attachments=attachments, ctx=ctx, max_tokens=32000)
    else:
        model = c.get("model_chat") or MODEL_CHAT
        answer = run_agent(c, agent_id, text, hist, model=model, kind="chat", attachments=attachments, ctx=ctx)
    store.add_message(client_id, agent_id, "assistant", answer,
                      {"model": model, "consulted": ctx.get("consulted", []), "changed": ctx.get("changed", False),
                       "emails": ctx.get("emails", [])})
    return {"text": answer, "consulted": ctx.get("consulted", []), "changed": ctx.get("changed", False), "model": model,
            "emails": ctx.get("emails", [])}


CRAFTS = {
    "animation": "анимация и мультфильмы", "illustration": "иллюстрация", "painting": "живопись и графика",
    "mural": "муралы и граффити", "music": "музыка и DJ", "dance": "танцы и хореография",
    "theatre": "театр и перформанс", "film": "кино и видео", "photo": "фотография", "design": "дизайн",
    "fashion": "мода и костюм", "writing": "литература и сценарии", "other": "творческая практика",
}

POTENTIAL_PROMPT = """Run a deep first analysis of my practice (this is the "Potential check").

1. Rate the potential of working with the team on a 10-point scale and explain the rating.
2. Propose a team line-up for my project: which agents to put on which tasks in the first 90 days.
3. Search the web for funding sources and commissions that look promising for me at first glance: name, what it is, amount, deadline, link. At least five.
4. Put the plan into my dashboard: project cards on the board, deadlines in the list, the KPIs that matter. Don't delete anything unless necessary.
5. Save the 2–3 key takeaways to the knowledge base.

Finish with three steps for this week. Reply in my language (see LANGUAGE in the context)."""


# ─── Режим подписки: claude CLI ──────────────────────────────────────────────
# CLI не умеет вызывать наши инструменты дашборда, поэтому агент отвечает JSON:
# {"reply": "...", "actions": [...]} — действия те же, что у инструментов API.
# Майя может поручить работу специалистам (action "ask"): они отвечают, и Майя
# делает второй проход уже с их ответами.

CLI_FORMAT = """ФОРМАТ ОТВЕТА — строго один JSON-объект, без текста вокруг и без ```:
{"reply": "ответ клиенту (markdown можно)", "actions": [ ... ]}
actions — изменения дашборда и базы опыта, пустой список, если менять нечего. Виды:
{"type":"dashboard_add_widget","kind":"kpi|chart|table|board|list|note","title":"...","size":"s|m|l","config":{...},"data":{...}}
{"type":"dashboard_update_widget","widget_id":1,"title":"...","config":{...},"data":{...}}
{"type":"dashboard_delete_widget","widget_id":1}
{"type":"board_add_card","widget_id":1,"text":"...","column":0}
{"type":"board_move_card","widget_id":1,"card_id":2,"column":1}
{"type":"list_add_item","widget_id":1,"text":"...","date":"YYYY-MM-DD"}
{"type":"chart_add_point","widget_id":1,"label":"2026-10","value":100,"series":"..."}
{"type":"kpi_set","widget_id":1,"value":100,"delta":"..."}
{"type":"table_add_row","widget_id":1,"cells":["...","..."]}
{"type":"save_insight","title":"...","body":"...","tags":"..."}
{"type":"opportunity_add","title":"...","org":"...","url":"https://...","deadline":"YYYY-MM-DD","amount":"...","region":"de|at|ch|ua|eu|intl","summary":"одна фраза по-английски"} — найденную и проверенную возможность в общий каталог
{"type":"email_draft","to":"адрес@организации","subject":"...","body":"полный текст письма с подписью клиента","app_id":0} — письмо внешнему адресату: НЕ отправляется, клиент согласует и отправляет сам
{"type":"app_save","title":"...","org":"...","url":"...","deadline":"YYYY-MM-DD","status":"idea|preparing|submitted|won|rejected"} — заявка в учёт; с "id" — обновить
Форматы data: kpi {value, delta}; chart {labels:[...], series:[{name, values:[...]}]}; table {rows:[[...]]};
board {cards:[{id, col, text}]}; list {items:[{id, text, date, done}]}; note {text}.
config: kpi {unit, goal}; chart {type: line|bar|pie|doughnut, unit}; table {columns:[...]}; board {columns:[...]}."""

CLI_ASK = """
Ты можешь поручить задачу специалистам: {"type":"ask","agent":"ruben|hanna|konrad|noa|tarik|iris|ben|chuck","task":"всё нужное для задачи"}.
Если поручаешь — в reply коротко скажи, кого зовёшь; их ответы придут тебе следующим сообщением, и ты сведёшь итог."""


def _parse_cli_json(text):
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.strip("`")
        t = t[t.find("{"):]
    a, b = t.find("{"), t.rfind("}")
    if a >= 0 and b > a:
        try:
            obj = json.loads(t[a:b + 1])
            if isinstance(obj, dict) and "reply" in obj:
                acts = obj.get("actions") or []
                return str(obj.get("reply") or ""), [x for x in acts if isinstance(x, dict)]
        except Exception:
            pass
    return t, []  # модель ответила простым текстом — показываем как есть


_CLI_LEAN = [os.environ.get("BACKSTAGE_CLI_LEAN", "1") == "1"]
_CLI_CWD = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cli_cwd")


def _cli_argv(system, tools, model, turns, lean):
    """lean — главный рычаг экономии по подписке: свой системный промпт ВМЕСТО
    стандартного промпта Claude Code (а не в дополнение к нему), только нужные
    инструменты вместо полутора десятков, без MCP-серверов и навыков."""
    argv = [CLAUDE_BIN, "-p", "--model", model, "--output-format", "json", "--max-turns", str(turns)]
    if lean:
        argv += ["--system-prompt", system, "--strict-mcp-config", "--disable-slash-commands",
                 "--tools", ",".join(tools)]
        if tools:
            argv += ["--allowedTools", ",".join(tools)]
    else:
        argv += ["--append-system-prompt", system]
        argv += ["--allowedTools", ",".join(tools)] if tools else ["--tools", ""]
    return argv


def _cli_call(c, kind, system, prompt, tools, model, timeout, turns=None):
    import subprocess
    if not os.path.exists(CLAUDE_BIN):
        raise RuntimeError("не найден claude CLI на сервере (~/.local/bin/claude)")
    turns = turns or (8 if tools else 2)
    env = {**os.environ, "PATH": os.path.expanduser("~/.local/bin") + ":" + os.environ.get("PATH", "")}
    os.makedirs(_CLI_CWD, exist_ok=True)  # пустая папка: CLI не подхватывает CLAUDE.md проекта
    for _ in range(2):
        argv = _cli_argv(system, tools, model, turns, _CLI_LEAN[0])
        # промпт — через stdin: большой текст в argv даёт E2BIG (урок ботов Фридмана)
        p = subprocess.run(argv, input=prompt, capture_output=True, text=True, timeout=timeout, env=env, cwd=_CLI_CWD)
        err = (p.stderr or "") + (p.stdout or "")[:300]
        if p.returncode != 0 and _CLI_LEAN[0] and ("unknown option" in err or "Unknown option" in err
                                                     or "unrecognized" in err):
            log.warning("claude CLI не знает экономных флагов — работаю по-старому: %s", err[-200:])
            _CLI_LEAN[0] = False
            continue
        break
    out = (p.stdout or "").strip()
    try:
        j = json.loads(out)
    except Exception:
        if p.returncode != 0:
            raise RuntimeError(f"claude CLI: {(p.stderr or out)[-300:]}")
        return out
    u = j.get("usage") or {}
    _log_usage(c["id"], kind, f"cli:{model}", {
        "input": u.get("input_tokens", 0) or 0, "output": u.get("output_tokens", 0) or 0,
        "cache_read": u.get("cache_read_input_tokens", 0) or 0,
        "cache_write": u.get("cache_creation_input_tokens", 0) or 0, "web": 0},
        float(j.get("total_cost_usd") or 0))  # условная цена: по подписке не списывается
    if j.get("is_error") and not j.get("result"):
        raise RuntimeError(f"claude CLI: {j.get('subtype') or 'ошибка'}")
    return j.get("result") or ""


def _cli_system(agent_id, lead):
    text = system_prompt(agent_id)[0]["text"]
    text += "\n\n## Как отвечать в этой панели\n\n" + CLI_FORMAT + (CLI_ASK if lead else "")
    return text


def _history_text(hist):
    if not hist:
        return ""
    lines = [("КЛИЕНТ: " if m["role"] == "user" else "ТЫ: ") + m["text"] for m in trim_history(hist)]
    return "ПРЕДЫДУЩАЯ ПЕРЕПИСКА:\n" + "\n\n".join(lines) + "\n\n"


def _apply(c, agent_id, actions, ctx, notes):
    for a in actions:
        name = a.get("type")
        if name == "ask":
            continue
        try:
            run_tool(c, agent_id, name, a, ctx)
        except Exception as e:  # noqa: BLE001
            notes.append(f"не вышло {name}: {e}")


def cli_agent(c, agent_id, user_text, hist, deep=False, attachments=None, ctx=None, depth=0):
    import tempfile
    ctx = ctx if ctx is not None else {}
    lead = bool(AGENTS[agent_id].get("lead")) and depth == 0
    model = CLI_MODEL_DEEP if deep else CLI_MODEL_CHAT
    tools = ["WebSearch", "WebFetch"] if web_allowed(agent_id, deep) else []
    files = []
    extra = ""
    for a in attachments or []:
        if a.get("text") is not None:
            extra += f"\n\nВЛОЖЕНИЕ «{a.get('name', 'файл')}»:\n{a['text'][:60000]}"
        elif a.get("data"):
            ext = ".pdf" if a.get("media_type") == "application/pdf" else ".png" if "png" in a.get("media_type", "") else ".jpg"
            f = tempfile.NamedTemporaryFile(prefix="bs_att_", suffix=ext, delete=False)
            f.write(base64.b64decode(a["data"]))
            f.close()
            files.append(f.name)
    if files:
        tools.append("Read")
        extra += "\n\nКлиент приложил файлы — прочитай их инструментом Read: " + ", ".join(files)
    try:
        lite = depth > 0  # специалисту — профиль, анкета и задача, без всего дашборда и переписки
        prompt = (f"<context>\n{context_block(c, agent_id, lite=lite)}\n</context>\n\n{_history_text(hist)}"
                  f"НОВОЕ СООБЩЕНИЕ КЛИЕНТА:\n{user_text}{extra}")
        system = _cli_system(agent_id, lead)
        timeout = 900 if deep else 420
        turns = (14 if deep else 8) if tools else 2
        kind = ("deep" if deep else "chat") if depth == 0 else f"specialist:{agent_id}"
        reply, actions = _parse_cli_json(_cli_call(c, kind, system, prompt, tools, model, timeout, turns))
        notes = []
        _apply(c, agent_id, actions, ctx, notes)
        asks = [a for a in actions if a.get("type") == "ask" and a.get("agent") in AGENTS
                and not AGENTS[a["agent"]].get("lead")][:MAX_ASKS_DEEP if deep else MAX_ASKS_CHAT]
        if lead and asks:
            answers = []
            for a in asks:
                if over_request_cap():
                    break  # потолок токенов на ответ — дальше не зовём
                ctx.setdefault("consulted", []).append(a["agent"])
                sub = cli_agent(c, a["agent"], str(a.get("task", "")), [], deep=deep, ctx=ctx, depth=1)
                answers.append(f"### {AGENTS[a['agent']]['name']} ({AGENTS[a['agent']]['role']})\n{sub[:SPECIALIST_ANSWER_CHARS]}")
            # Второй проход — без повторной отправки всего дашборда и переписки: всё нужное уже в ответах
            prompt2 = (f"<context>\n{context_block(c, agent_id, lite=True)}\n</context>\n\n"
                       f"СООБЩЕНИЕ КЛИЕНТА:\n{user_text}\n\nТВОЙ ПЕРВЫЙ ОТВЕТ: {reply}\n\nОТВЕТЫ СПЕЦИАЛИСТОВ:\n\n"
                       + "\n\n".join(answers) +
                       "\n\nСведи итог для клиента. Действия из первого ответа уже применены — не повторяй их. "
                       "Новых поручений не давай. Новый поиск в интернете не нужен.")
            if over_request_cap() and not answers:
                return (reply.strip() + "\n\n" + i18n.t(c.get("lang"), "request_cap")).strip()
            reply, actions = _parse_cli_json(_cli_call(c, kind, system, prompt2, [], model, timeout, 2))
            _apply(c, agent_id, [a for a in actions if a.get("type") != "ask"], ctx, notes)
        if notes:
            log.warning("cli actions: %s", notes)
        return reply.strip() or i18n.t(c.get("lang"), "empty_reply")
    finally:
        for f in files:
            try:
                os.unlink(f)
            except OSError:
                pass


# ─── Радар возможностей: один поиск на связку «ремесло + страна» ─────────────

RADAR_MODEL_CLI = os.environ.get("BACKSTAGE_RADAR_MODEL", "sonnet")
COUNTRY_NAMES = {"de": "Germany", "at": "Austria", "ch": "Switzerland", "ua": "Ukraine",
                 "eu": "an EU country", "any": "any country (international and online opportunities)"}
RADAR_SYSTEM = """You are Ruben, the scout of Backstage — an AI team that runs the business side for creative people.
Find CURRENT opportunities with money or reach for the given craft and place: open calls, grants, stipends,
residencies, contests, festivals with submissions, tenders and commission calls. Only opportunities whose
deadline is in the future (or rolling). Check every link in your search results; never invent links or dates.
Answer with ONE JSON object and nothing else:
{"items": [{"title": "...", "org": "who runs it", "url": "https://...", "deadline": "YYYY-MM-DD or empty",
"amount": "money / prize / fee, short", "region": "de|at|ch|ua|eu|intl", "summary": "one English sentence: what and who can apply"}]}
6 to 10 items, the most valuable first."""


def radar_search(craft, country):
    """Список возможностей (dict) для ремесла и страны. Пишет расход на «платформу» (client_id 0)."""
    today = datetime.now().strftime("%Y-%m-%d")
    craft_name = i18n.CRAFTS["en"].get(craft, craft)
    prompt = (f"Today is {today}. Craft: {craft_name}. Artists based in {COUNTRY_NAMES.get(country, country)}."
              " Include opportunities open to them locally, EU-wide and internationally.")
    if backend() == "api":
        messages = [{"role": "user", "content": prompt}]
        text, resp = "", None
        for _ in range(6):
            resp = _call(MODEL_CHAT, EFFORT_CHAT, [{"type": "text", "text": RADAR_SYSTEM}], [dict(WEB_TOOL)],
                         messages, 8000)
            u = _usage(resp)
            _log_usage(0, f"radar:{craft}:{country}", resp.model or MODEL_CHAT, u, cost_of(resp.model or MODEL_CHAT, u))
            if resp.stop_reason != "pause_turn":
                break
            messages.append({"role": "assistant", "content": resp.content})
        text = "\n".join(b.text for b in resp.content if b.type == "text")
    else:
        text = _cli_call({"id": 0}, f"radar:{craft}:{country}", RADAR_SYSTEM, prompt,
                         ["WebSearch", "WebFetch"], RADAR_MODEL_CLI, 900, 16)
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        items = json.loads(m.group(0)).get("items") if m else []
    except Exception:
        items = []
    out = []
    for it in items or []:
        if not isinstance(it, dict) or not it.get("title"):
            continue
        d = str(it.get("deadline") or "")
        if d and (not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) or d < today):
            continue  # прошедшие и кривые даты не берём
        out.append(it)
    return out
