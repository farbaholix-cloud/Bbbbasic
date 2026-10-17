"""
Мозг Backstage — вызовы Claude через официальный SDK (anthropic) по ключу API.

Отличие от системы Фридмана: там боты звали `claude` CLI по личной подписке
владельца. Для платформы, которой пользуются клиенты агентства, нужен ключ
Claude API (console.anthropic.com) с предоплаченным балансом — каждый вызов
считается в долларах и записывается в usage по клиенту.

Модели (меняются в .env или для отдельного клиента в админке):
  BACKSTAGE_MODEL_CHAT  — повседневный чат с командой, по умолчанию claude-opus-5-5
  BACKSTAGE_MODEL_DEEP  — «Глубокий анализ», по умолчанию claude-fable-5-1,
                          самая мощная из общедоступных моделей Claude
"""
import os
import re
import json
import logging
from datetime import datetime

try:
    import anthropic
except ImportError:  # библиотека ещё ставится — панель работает, чат ответит ошибкой
    anthropic = None

import store

log = logging.getLogger("backstage.brain")

HERE = os.path.dirname(os.path.abspath(__file__))
AGENTS_DIR = os.path.join(HERE, "agents")
PACKS_DIR = os.path.join(HERE, "packs")

MODEL_CHAT = os.environ.get("BACKSTAGE_MODEL_CHAT", "claude-opus-5-5")
MODEL_DEEP = os.environ.get("BACKSTAGE_MODEL_DEEP", "claude-fable-5-1")
EFFORT_CHAT = os.environ.get("BACKSTAGE_EFFORT_CHAT", "high")
EFFORT_DEEP = os.environ.get("BACKSTAGE_EFFORT_DEEP", "xhigh")
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
    data = w["data"]
    s = json.dumps(data, ensure_ascii=False)
    if len(s) > 3000:  # большой виджет — показываем хвост, чтобы не раздувать контекст
        s = s[:3000] + "…"
    return f'- id={w["id"]} [{w["kind"]}] «{w["title"]}» config={json.dumps(w["config"], ensure_ascii=False)} data={s}'


def context_block(c, agent_id):
    widgets = store.list_widgets(c["id"])
    ins = store.insights_for(c["id"], limit=30)
    lines = [
        f"СЕГОДНЯ: {datetime.now().strftime('%Y-%m-%d, %A')}",
        f"КЛИЕНТ: {c['name']}",
        f"ПРОФИЛЬ ПРАКТИКИ:\n{c['profile'] or '(не заполнен — узнай у клиента и предложи сохранить в заметку «Профиль практики»)'}",
        "ДАШБОРД КЛИЕНТА:\n" + ("\n".join(_compact_widget(w) for w in widgets) or "(пусто)"),
    ]
    if ins:
        lines.append("БАЗА ОПЫТА (свои выводы клиента и общий плейбук агентства):\n" + "\n".join(
            f"- [{'общий' if i['shared'] else 'свой'}] {i['title']}: {i['body'][:400]}" for i in ins))
    budget = c["monthly_budget"] or 0
    lines.append(f"БЮДЖЕТ ИИ: потрачено ${store.spent_this_month(c['id']):.2f} из ${budget:.2f} в этом месяце.")
    return "\n\n".join(lines)


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
    if web and (AGENTS[agent_id].get("web") or AGENTS[agent_id].get("lead")):
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
    if name == "ask_specialist":
        sub = inp["agent"]
        if sub not in AGENTS or AGENTS[sub].get("lead"):
            raise ValueError("нет такого специалиста")
        ctx.setdefault("consulted", []).append(sub)
        answer = run_agent(c, sub, inp["task"], history=[], model=ctx["model"], effort=ctx["effort"],
                           kind=f"specialist:{sub}", allow_delegate=False, ctx=ctx)
        return answer
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


def check_budget(c):
    budget = float(c["monthly_budget"] or 0)
    if budget > 0 and store.spent_this_month(c["id"]) >= budget:
        raise BudgetExceeded(
            f"Месячный бюджет ИИ (${budget:.2f}) исчерпан. Владелец платформы может поднять лимит в админке.")


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
              attachments=None, allow_delegate=True, ctx=None, max_tokens=32000):
    """Один ход агента: контекст + история + сообщение → ответ текстом.
    Пишет расход по каждому запросу. Дашборд агент меняет через инструменты."""
    check_budget(c)
    model = model or c.get("model_chat") or MODEL_CHAT
    effort = effort or EFFORT_CHAT
    ctx = ctx if ctx is not None else {}
    ctx.setdefault("model", model)
    ctx.setdefault("effort", effort)

    messages = []
    for m in history or []:
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
    content.append({"type": "text", "text": f"<context>\n{context_block(c, agent_id)}\n</context>\n\n{user_text}"})
    messages.append({"role": "user", "content": content})

    system = system_prompt(agent_id)
    tools = tools_for(agent_id, allow_delegate=allow_delegate)
    resp = None
    for _ in range(MAX_TOOL_ROUNDS):
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
        store.log_usage(c["id"], kind, resp.model or model, u, cost_of(resp.model or model, u))
        messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason == "refusal":
            return "Эту просьбу модель отклонила. Попробуй переформулировать задачу."
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
    if resp is not None and resp.stop_reason == "max_tokens":
        text += "\n\n_(ответ упёрся в лимит длины — попроси продолжить)_"
    return text or "(пустой ответ)"


def chat(client_id, agent_id, text, attachments=None, deep=False):
    """Точка входа для веб-панели и Telegram-моста. Сохраняет переписку."""
    c = store.get_client(client_id)
    if agent_id not in AGENTS:
        agent_id = "maya"
    hist = store.history(client_id, agent_id, limit=24)
    note = ""
    if attachments:
        note = "\n\n📎 " + ", ".join(a.get("name", "файл") for a in attachments)
    store.add_message(client_id, agent_id, "user", text + note, {"deep": deep})
    ctx = {}
    if deep:
        model = c.get("model_deep") or MODEL_DEEP
        answer = run_agent(c, agent_id, text, hist, model=model, effort=EFFORT_DEEP, kind="deep",
                           attachments=attachments, ctx=ctx, max_tokens=64000)
    else:
        model = c.get("model_chat") or MODEL_CHAT
        answer = run_agent(c, agent_id, text, hist, model=model, kind="chat", attachments=attachments, ctx=ctx)
    store.add_message(client_id, agent_id, "assistant", answer,
                      {"model": model, "consulted": ctx.get("consulted", []), "changed": ctx.get("changed", False)})
    return {"text": answer, "consulted": ctx.get("consulted", []), "changed": ctx.get("changed", False), "model": model}


POTENTIAL_PROMPT = """Проведи глубокий первый анализ моей практики (это «Проверка потенциала»).

1. Оцени потенциал сотрудничества с командой по 10-балльной шкале и объясни оценку.
2. Предложи состав команды под мой проект: каких агентов и на какие задачи поставить в первые 90 дней.
3. Найди в интернете источники финансирования и заказов, которые на первый взгляд выглядят перспективными для меня: название, суть, сумма, дедлайн, ссылка. Минимум пять.
4. Перестрой мой дашборд под этот план: карточки проектов на доске, дедлайны в списке, нужные KPI. Ничего не удаляй без необходимости.
5. Сохрани 2–3 главных вывода в базу опыта.

В конце — три шага на эту неделю."""
