"""Импорт реального списка танцоров из CSV (Excel → «Сохранить как CSV»).

    python import_dancers.py dancers.csv

Колонки (первая строка — заголовки, разделитель ; или ,):
    name;group;style;phone;email;birthday;monthly_fee
Дата рождения — ДД.ММ.ГГГГ или ГГГГ-ММ-ДД. Каждому танцору создаётся личная ссылка-приглашение в бота.
"""
import csv
import sys
from datetime import date, datetime

import db


def parse_date(s):
    s = (s or "").strip()
    for f in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, f).date().isoformat()
        except ValueError:
            pass
    return None


def main(path):
    db.init()
    raw = open(path, encoding="utf-8-sig").read()
    rows = list(csv.DictReader(raw.splitlines(), delimiter=";" if raw.count(";") > raw.count(",") else ","))
    n = 0
    for r in rows:
        r = {k.strip().lower(): (v or "").strip() for k, v in r.items() if k}
        if not r.get("name"):
            continue
        if db.one("SELECT id FROM dancers WHERE name=? AND COALESCE(phone,'')=?", (r["name"], r.get("phone", ""))):
            continue
        db.execute("INSERT INTO dancers(name,group_name,style,phone,email,birthday,monthly_fee,joined_on,invite_code)"
                   " VALUES(?,?,?,?,?,?,?,?,?)",
                   (r["name"], r.get("group"), r.get("style"), r.get("phone"), r.get("email"), parse_date(r.get("birthday")),
                    float(r.get("monthly_fee") or 0), date.today().isoformat(), db.new_invite_code()))
        n += 1
    print(f"Импортировано: {n}. Ссылки-приглашения: команда /invites в боте или вкладка «Танцоры» в пульте.")


if __name__ == "__main__":
    main(sys.argv[1])
