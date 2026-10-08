"""Статистика коллектива: общая для сводки, бота и дашборда."""
from datetime import date, timedelta

import db

MONTHS_SHORT = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]


def _sum(sql, args=()):
    r = db.one(sql, args)
    return float(list(r.values())[0] or 0) if r else 0.0


def month_bounds(d):
    first = d.replace(day=1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    return first, nxt


def collect(today=None):
    today = today or date.today()
    t = today.isoformat()
    m0, m1 = month_bounds(today)
    pm0, _ = month_bounds(m0 - timedelta(days=1))
    # тот же отрезок прошлого месяца (1..сегодня) — честное сравнение «месяц к месяцу»
    pm_same = pm0 + (today - m0)
    y0 = today.replace(month=1, day=1)

    def inc(a, b):
        return _sum("SELECT SUM(amount) FROM transactions WHERE direction='in' AND date>=? AND date<?", (a, b))

    def out(a, b):
        return _sum("SELECT SUM(amount) FROM transactions WHERE direction='out' AND date>=? AND date<?", (a, b))

    tomorrow = (today + timedelta(days=1)).isoformat()
    s = {
        "date": t,
        "income_month": inc(m0.isoformat(), tomorrow),
        "expense_month": out(m0.isoformat(), tomorrow),
        "income_prev_same": inc(pm0.isoformat(), (pm_same + timedelta(days=1)).isoformat()),
        "income_year": inc(y0.isoformat(), tomorrow),
        "expense_year": out(y0.isoformat(), tomorrow),
        "income_yesterday": inc((today - timedelta(days=1)).isoformat(), t),
        "balance_all": inc("0000", "9999") - out("0000", "9999"),
    }
    s["profit_month"] = s["income_month"] - s["expense_month"]
    s["mom_pct"] = ((s["income_month"] / s["income_prev_same"] - 1) * 100) if s["income_prev_same"] else None

    # дебиторка: выполненные/подтверждённые проекты минус поступления по ним
    debt = db.rows("""SELECT p.id, p.title, p.date, p.budget, c.company, c.name,
                        p.budget - COALESCE((SELECT SUM(amount) FROM transactions WHERE project_id=p.id AND direction='in'),0) AS due
                      FROM projects p LEFT JOIN clients c ON c.id=p.client_id
                      WHERE p.status='выполнен' AND p.date<=? ORDER BY p.date""", (t,))
    debt = [x for x in debt if x["due"] > 1]
    s["receivables"] = sum(x["due"] for x in debt)
    s["debtors"] = debt

    s["dancers_active"] = int(_sum("SELECT COUNT(*) FROM dancers WHERE status='active'"))
    s["dancers_total"] = int(_sum("SELECT COUNT(*) FROM dancers"))
    s["dancers_tg"] = int(_sum("SELECT COUNT(*) FROM dancers WHERE tg_id IS NOT NULL AND status!='left'"))
    att = db.one("""SELECT AVG(a.present)*100 p FROM attendance a JOIN rehearsals r ON r.id=a.rehearsal_id
                    WHERE r.date>=? AND r.date<=?""", ((today - timedelta(days=30)).isoformat(), t))
    s["attendance_30"] = att["p"] or 0
    att_prev = db.one("""SELECT AVG(a.present)*100 p FROM attendance a JOIN rehearsals r ON r.id=a.rehearsal_id
                         WHERE r.date>=? AND r.date<?""", ((today - timedelta(days=60)).isoformat(),
                                                          (today - timedelta(days=30)).isoformat()))
    s["attendance_prev"] = att_prev["p"] or 0

    s["upcoming"] = db.rows("""SELECT p.id, p.title, p.date, p.venue, p.status, p.budget, p.dancers_needed, c.company, c.name,
                                 (SELECT COUNT(*) FROM assignments a WHERE a.project_id=p.id AND a.status IN ('yes','confirmed')) AS ready
                               FROM projects p LEFT JOIN clients c ON c.id=p.client_id
                               WHERE p.date>=? AND p.status IN ('подтверждён','переговоры') ORDER BY p.date LIMIT 6""", (t,))
    s["leads"] = int(_sum("SELECT COUNT(*) FROM projects WHERE status IN ('лид','переговоры') AND date>=?", (t,)))
    s["pipeline"] = _sum("SELECT SUM(budget) FROM projects WHERE status IN ('лид','переговоры','подтверждён') AND date>=?", (t,))
    s["followups"] = db.rows("""SELECT cm.next_step, cm.next_date, c.company, c.name FROM communications cm
                                JOIN clients c ON c.id=cm.client_id
                                WHERE cm.next_date IS NOT NULL AND cm.next_date<=? AND cm.next_date>=?
                                ORDER BY cm.next_date LIMIT 5""", ((today + timedelta(days=1)).isoformat(),
                                                                   (today - timedelta(days=7)).isoformat()))
    s["unread"] = int(_sum("SELECT COUNT(*) FROM messages WHERE direction='in' AND is_read=0"))
    s["rehearsals_today"] = db.rows("SELECT time, group_name, place FROM rehearsals WHERE date=? ORDER BY time", (t,))

    md = today.strftime("-%m-%d")
    s["birthdays"] = db.rows("""SELECT name, group_name, birthday FROM dancers WHERE status!='left'
                                AND substr(birthday,5)=? ORDER BY name""", (md,))
    week = [(today + timedelta(days=i)).strftime("-%m-%d") for i in range(1, 8)]
    s["birthdays_week"] = db.rows(f"""SELECT name, birthday FROM dancers WHERE status!='left'
                                     AND substr(birthday,5) IN ({','.join('?' * 7)})""", week)

    # помесячные поступления за 12 месяцев (для мини-графика в сводке)
    series = []
    cur = m0
    for _ in range(12):
        a, b = month_bounds(cur)
        series.append((MONTHS_SHORT[a.month - 1], inc(a.isoformat(), b.isoformat())))
        cur = a - timedelta(days=1)
    s["income_12m"] = list(reversed(series))

    # «из истории Inspire»: проекты в этот день в прошлые годы
    s["our_history"] = db.rows("""SELECT p.title, p.date, p.venue FROM projects p
                                  WHERE substr(p.date,5)=? AND p.date<? AND p.status='выполнен' ORDER BY p.date""",
                               (md, t))
    return s


def money(x, cur="€"):
    return f"{x:,.0f}".replace(",", " ") + " " + cur
