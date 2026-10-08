"""Демо-наполнение: 110 танцоров и ~2,5 года жизни коллектива.

    python seed_demo.py            # создать inspire.db с демо-данными
    python seed_demo.py --force    # пересоздать

Для боевого запуска НЕ нужен: начните с пустой базы и импортируйте свой список танцоров
(python import_dancers.py dancers.csv).
"""
import os
import random
import sys
from datetime import date, timedelta

import db
from config import DB_PATH

R = random.Random(2026)
TODAY = date.today()
START = date(TODAY.year - 2, 4, 1)

FIRST_F = ["Анна", "Мария", "Софья", "Алина", "Виктория", "Дарья", "Полина", "Ева", "Лея", "Мила", "Ксения",
           "Лаура", "Эмили", "Ханна", "Лина", "Мия", "Юлия", "Вероника", "Елена", "Ника", "Амели", "Карина",
           "Диана", "Яна", "Олеся", "Сара", "Николь", "Злата", "Арина", "Лиза"]
FIRST_M = ["Максим", "Артём", "Лукас", "Давид", "Марк", "Леон", "Тимур", "Никита", "Даниэль", "Феликс",
           "Илья", "Кирилл", "Йонас", "Эмиль", "Роман", "Пауль", "Адам", "Ной"]
LAST = ["Мюллер", "Шмидт", "Ковальчук", "Беккер", "Вагнер", "Иванова", "Петренко", "Фишер", "Хоффманн",
        "Кох", "Морозова", "Шульц", "Бондаренко", "Кляйн", "Вольф", "Новак", "Зайцева", "Ричтер", "Лебедева",
        "Кравец", "Бергер", "Майер", "Соколова", "Ткаченко", "Келлер", "Хан", "Орлова", "Фогель", "Демир", "Роса"]
GROUPS = [("Kids", 26, 45, (7, 12)), ("Teens", 28, 55, (13, 17)), ("Adults", 30, 65, (18, 45)),
          ("Pro", 16, 0, (18, 32)), ("Show", 10, 0, (19, 30))]
STYLES = ["hip-hop", "contemporary", "jazz-funk", "house", "waacking", "dancehall", "breaking", "locking"]

CLIENT_KINDS = ["корпоратив", "свадьба", "агентство", "фестиваль", "ТВ", "бренд", "частный", "город"]
COMPANIES = ["Deutsche Messe", "Lufthansa Events", "Skyline Agency", "Main Festival", "Hessischer Rundfunk",
             "Adidas Store FFM", "Commerzbank Arena", "Stadt Frankfurt — Kulturamt", "Palmengarten",
             "Alte Oper", "Bembel Media", "Event Fabrik", "Nordwest Zentrum", "Kinder-Festival Hessen",
             "Zalando Showroom", "Tanzhaus West", "Gala Concept", "Mainova", "Messe Wedding Show",
             "Museumsufer e.V.", "Hip-Hop Jam Offenbach", "Fitness First", "Sparkasse", "Hotel Villa Kennedy",
             "Bridal Moments", "Luminale", "Clipmaker Studio", "Rhein-Main Awards", "Opernplatzfest", "IKEA Wallau"]
SOURCES = ["Instagram", "рекомендация", "сайт", "TikTok", "повторный", "агентство", "выступление"]
PKINDS = {"корпоратив": ["Шоу-программа", "Флешмоб для команды", "Открытие конференции"],
          "свадьба": ["Свадебный номер", "Постановка первого танца", "Шоу на свадьбе"],
          "агентство": ["Шоу-номер", "Промо-выступление"],
          "фестиваль": ["Выступление на фестивале", "Баттл и шоукейс"],
          "ТВ": ["Съёмка ТВ-шоу", "Танцевальная заставка"],
          "бренд": ["Съёмка рекламы", "Открытие магазина", "Клип для бренда"],
          "частный": ["День рождения: шоу", "Мастер-класс на празднике"],
          "город": ["Городской праздник", "Уличный перформанс"]}
VENUES = ["Alte Oper", "Messe Frankfurt", "Palmengarten", "Römerberg", "Gibson Club", "Batschkapp",
          "Jahrhunderthalle", "Zoom Club", "Museumsufer", "Kap Europa", "Villa Kennedy", "Studio Inspire"]


def d(x):
    return x.isoformat()


def season(m):
    # мультипликатор спроса по месяцам: декабрь — корпоративы, лето — свадьбы/фестивали
    return {1: .45, 2: .55, 3: .8, 4: .9, 5: 1.15, 6: 1.35, 7: 1.3, 8: 1.1, 9: 1.15, 10: 1.0, 11: 1.15, 12: 1.7}[m]


def growth(day):
    # коллектив растёт: +~45% за два с половиной года
    return 0.75 + 0.45 * ((day - START).days / max(1, (TODAY - START).days))


def main(force=False):
    if os.path.exists(DB_PATH):
        if not force:
            print("База уже есть:", DB_PATH, "— запустите с --force, чтобы пересоздать")
            return
        os.remove(DB_PATH)
    db.init()
    with db.db() as c:
        # ── Танцоры ───────────────────────────────────────────────────────────
        dancers = []
        for gname, count, fee, (amin, amax) in GROUPS:
            for _ in range(count):
                fem = R.random() < .72
                name = f"{R.choice(FIRST_F if fem else FIRST_M)} {R.choice(LAST)}"
                age = R.randint(amin, amax)
                bday = date(TODAY.year - age, R.randint(1, 12), R.randint(1, 28))
                joined = (START - timedelta(days=R.randint(10, 900)) if R.random() < .68
                          else START + timedelta(days=R.randint(0, (TODAY - START).days - 20)))
                status = "active" if R.random() > .06 else R.choice(["pause", "left"])
                tg = R.random() < .87  # 87% уже подключились к боту
                cur = c.execute(
                    "INSERT INTO dancers(name,group_name,style,level,phone,email,birthday,joined_on,status,"
                    "monthly_fee,tg_id,tg_username,invite_code) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (name, gname, R.choice(STYLES),
                     {"Kids": "начальный", "Teens": R.choice(["начальный", "средний"]),
                      "Adults": R.choice(["начальный", "средний", "продвинутый"])}.get(gname, "продвинутый"),
                     f"+49 1{R.randint(50, 79)} {R.randint(1000000, 9999999)}",
                     f"dancer{len(dancers) + 1}@mail.de", d(bday), d(joined), status, fee,
                     (900000000 + len(dancers)) if tg else None,
                     f"inspire_{len(dancers) + 1}" if tg else None, db.new_invite_code()))
                dancers.append((cur.lastrowid, gname, fee, joined, status))
        # гарантируем пару дней рождения «сегодня/на неделе» — для сводки
        for i, shift in enumerate([0, 2, 5]):
            b = TODAY + timedelta(days=shift)
            c.execute("UPDATE dancers SET birthday=? WHERE id=?",
                      (d(date(TODAY.year - 20 - i * 3, b.month, b.day)), dancers[10 + i * 30][0]))
        pros = [x[0] for x in dancers if x[1] in ("Pro", "Show") and x[4] == "active"]
        adults = [x[0] for x in dancers if x[1] == "Adults" and x[4] == "active"]

        # ── Заказчики ─────────────────────────────────────────────────────────
        clients = []
        for i, comp in enumerate(COMPANIES):
            kind = ("свадьба" if "Wedding" in comp or "Bridal" in comp else
                    "фестиваль" if "Festival" in comp or "fest" in comp.lower() or "Jam" in comp else
                    "ТВ" if "Rundfunk" in comp or "Media" in comp else
                    "агентство" if "Agency" in comp or "Concept" in comp or "Fabrik" in comp else
                    "город" if "Stadt" in comp or "e.V." in comp or "Luminale" in comp else
                    R.choice(["корпоратив", "бренд", "корпоратив"]))
            created = START + timedelta(days=R.randint(-60, (TODAY - START).days - 30))
            cur = c.execute("INSERT INTO clients(name,company,kind,phone,email,source,created_on) VALUES(?,?,?,?,?,?,?)",
                            (f"{R.choice(FIRST_F + FIRST_M)} {R.choice(LAST)}", comp, kind,
                             f"+49 69 {R.randint(100000, 999999)}", f"events@{comp.split()[0].lower()}.de",
                             R.choice(SOURCES), d(created)))
            clients.append((cur.lastrowid, kind, created))
        # частные клиенты-свадьбы
        for i in range(14):
            created = START + timedelta(days=R.randint(0, (TODAY - START).days))
            cur = c.execute("INSERT INTO clients(name,company,kind,phone,source,created_on) VALUES(?,?,?,?,?,?)",
                            (f"{R.choice(FIRST_F)} и {R.choice(FIRST_M)} {R.choice(LAST)}", None, "свадьба",
                             f"+49 17{R.randint(0, 9)} {R.randint(1000000, 9999999)}", R.choice(SOURCES), d(created)))
            clients.append((cur.lastrowid, "свадьба", created))

        # ── Проекты + оплаты + выплаты танцорам + коммуникации ────────────────
        day = START
        end = TODAY + timedelta(days=75)
        while day <= end:
            n = R.random() * 2 * season(day.month) * growth(min(day, TODAY)) * .42
            for _ in range(int(n) + (1 if R.random() < n % 1 else 0)):
                cid, ckind, cdate = R.choice(clients)
                if cdate > day:
                    continue
                title = R.choice(PKINDS[ckind])
                base = {"корпоратив": 3200, "свадьба": 1400, "агентство": 2600, "фестиваль": 2200, "ТВ": 4200,
                        "бренд": 3800, "частный": 900, "город": 2400}[ckind]
                budget = round(base * R.uniform(.6, 1.7) / 50) * 50
                need = R.randint(4, 16)
                if day < TODAY - timedelta(days=3):
                    status = "отменён" if R.random() < .06 else "выполнен"
                elif day < TODAY + timedelta(days=21):
                    status = R.choice(["подтверждён", "подтверждён", "подтверждён", "переговоры"])
                else:
                    status = R.choice(["подтверждён", "переговоры", "лид", "лид"])
                created = day - timedelta(days=R.randint(14, 70))
                cur = c.execute(
                    "INSERT INTO projects(title,client_id,kind,date,venue,status,budget,dancers_needed,created_on) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (title, cid, ckind, d(day), R.choice(VENUES), status, budget, need, d(created)))
                pid = cur.lastrowid
                # переписка с заказчиком по проекту
                ch = ["звонок", "email", "WhatsApp", "встреча", "Telegram"]
                steps = [("in", "Запрос: дата, формат, кол-во танцоров", "Отправить КП"),
                         ("out", f"Отправили КП на {budget:.0f} {chr(8364)}, 2 варианта номера", "Созвон по деталям"),
                         ("in", "Согласовали музыку и тайминг", "Договор и предоплата"),
                         ("out", "Договор отправлен, предоплата 50%", "Техрайдер площадки")]
                k = 4 if status in ("выполнен", "подтверждён") else 2 if status == "переговоры" else 1
                for j in range(k):
                    cd = created + timedelta(days=j * R.randint(2, 9))
                    if cd > TODAY:
                        break
                    dirn, summ, nxt = steps[j]
                    nd = cd + timedelta(days=R.randint(2, 6))
                    c.execute("INSERT INTO communications(client_id,project_id,date,channel,direction,summary,next_step,next_date)"
                              " VALUES(?,?,?,?,?,?,?,?)",
                              (cid, pid, d(cd), R.choice(ch), dirn, summ, nxt if j == k - 1 and status != "выполнен" else None,
                               d(nd) if j == k - 1 and status != "выполнен" else None))
                if status in ("выполнен", "подтверждён"):
                    # предоплата 50% + остаток после события (часть заказчиков задерживает оплату)
                    pre = created + timedelta(days=R.randint(5, 12))
                    if pre <= TODAY:
                        c.execute("INSERT INTO transactions(date,amount,direction,category,project_id,client_id,method,note)"
                                  " VALUES(?,?,?,?,?,?,?,?)",
                                  (d(min(pre, day)), budget / 2, "in", "Гонорары", pid, cid, "банк", "Предоплата 50%"))
                    if status == "выполнен":
                        late = R.random() < .1 and day > TODAY - timedelta(days=60)
                        post = day + timedelta(days=R.randint(1, 14))
                        if not late and post <= TODAY:
                            c.execute("INSERT INTO transactions(date,amount,direction,category,project_id,client_id,method,note)"
                                      " VALUES(?,?,?,?,?,?,?,?)",
                                      (d(post), budget / 2, "in", "Гонорары", pid, cid, "банк", "Остаток после события"))
                    # состав и гонорары танцоров
                    team = R.sample(pros + adults[:20], min(need, len(pros) + 20))
                    fee = round(budget * .42 / max(1, len(team)) / 5) * 5
                    for did in team:
                        c.execute("INSERT OR IGNORE INTO assignments(project_id,dancer_id,status,fee) VALUES(?,?,?,?)",
                                  (pid, did, "confirmed" if status == "выполнен" else R.choice(["confirmed", "yes", "maybe", "invited"]), fee))
                    if status == "выполнен" and day + timedelta(days=10) <= TODAY:
                        c.execute("INSERT INTO transactions(date,amount,direction,category,project_id,method,note)"
                                  " VALUES(?,?,?,?,?,?,?)",
                                  (d(day + timedelta(days=10)), fee * len(team), "out", "Выплаты танцорам", pid, "банк",
                                   f"{len(team)} танцоров × {fee} {chr(8364)}"))
                        if R.random() < .35:
                            c.execute("INSERT INTO transactions(date,amount,direction,category,project_id,method,note)"
                                      " VALUES(?,?,?,?,?,?,?)",
                                      (d(day), R.randint(60, 380), "out", "Транспорт", pid, "карта", "Трансфер / такси"))
            day += timedelta(days=1)

        # ── Ежемесячные потоки: абонементы, аренда, мастер-классы, гранты, расходы ──
        m = date(START.year, START.month, 1)
        while m <= TODAY:
            last = (m.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
            fees = sum(f for (_i, _g, f, j, s) in dancers if f and j <= last and s == "active")
            paid = fees * R.uniform(.86, .97) * (.88 if m.month in (7, 8) else 1)
            pay_day = m + timedelta(days=R.randint(2, 6))
            if pay_day <= TODAY:
                c.execute("INSERT INTO transactions(date,amount,direction,category,method,note) VALUES(?,?,?,?,?,?)",
                          (d(pay_day), round(paid), "in", "Абонементы", "банк", "Абонементы за месяц"))
                c.execute("INSERT INTO transactions(date,amount,direction,category,method,note) VALUES(?,?,?,?,?,?)",
                          (d(m + timedelta(days=1)), 2100 if m.year < TODAY.year else 2350, "out", "Аренда зала", "банк",
                           "Студия Hanauer Landstraße"))
            for _ in range(R.randint(1, 3)):
                wd = m + timedelta(days=R.randint(5, 26))
                if wd <= TODAY:
                    c.execute("INSERT INTO transactions(date,amount,direction,category,method,note) VALUES(?,?,?,?,?,?)",
                              (d(wd), R.randint(18, 40) * 25, "in", "Мастер-классы", "карта",
                               f"Мастер-класс {R.choice(STYLES)}"))
            for cat, lo, hi, p in [("Костюмы", 150, 1400, .55), ("Реклама", 80, 450, .7), ("Музыка и лицензии", 20, 120, .5),
                                   ("Хореографы", 300, 900, .45), ("Оборудование", 90, 700, .2)]:
                if R.random() < p * (1.6 if m.month in (11, 12, 5, 6) and cat == "Костюмы" else 1):
                    ed = m + timedelta(days=R.randint(3, 27))
                    if ed <= TODAY:
                        c.execute("INSERT INTO transactions(date,amount,direction,category,method,note) VALUES(?,?,?,?,?,?)",
                                  (d(ed), R.randint(lo, hi), "out", cat, R.choice(["карта", "банк"]), cat))
            if m.month in (3, 9):
                gd = m + timedelta(days=R.randint(8, 20))
                if gd <= TODAY:
                    c.execute("INSERT INTO transactions(date,amount,direction,category,method,note) VALUES(?,?,?,?,?,?)",
                              (d(gd), R.choice([2500, 4000, 6000]), "in", "Гранты", "банк", "Kulturamt Frankfurt"))
            m = last + timedelta(days=1)

        # ── Репетиции и посещаемость ──────────────────────────────────────────
        sched = {"Kids": [(1, "16:30"), (3, "16:30")], "Teens": [(1, "18:00"), (4, "18:00")],
                 "Adults": [(0, "19:30"), (2, "19:30")], "Pro": [(1, "20:00"), (3, "20:00"), (5, "12:00")],
                 "Show": [(2, "18:00"), (5, "14:00")]}
        by_group = {}
        for did, g, _f, j, s in dancers:
            by_group.setdefault(g, []).append((did, j, s, R.uniform(.62, .97)))
        day = TODAY - timedelta(days=365)
        while day <= TODAY + timedelta(days=14):
            for g, slots in sched.items():
                for wd, tm in slots:
                    if day.weekday() != wd:
                        continue
                    cur = c.execute("INSERT INTO rehearsals(date,time,group_name,title,place) VALUES(?,?,?,?,?)",
                                    (d(day), tm, g, f"Репетиция {g}", "Studio Inspire, зал A" if g != "Kids" else "зал B"))
                    if day > TODAY:
                        continue
                    rid = cur.lastrowid
                    summer = .85 if day.month in (7, 8) else 1
                    for did, j, s, rate in by_group[g]:
                        if j > day:
                            continue
                        if s == "left" and day > TODAY - timedelta(days=90):
                            continue
                        c.execute("INSERT INTO attendance(rehearsal_id,dancer_id,present) VALUES(?,?,?)",
                                  (rid, did, 1 if R.random() < rate * summer else 0))
            day += timedelta(days=1)

        # ── Переписка с танцорами через бота ──────────────────────────────────
        ins = ["Можно сегодня прийти на 15 минут позже? Пробка на A66", "Скинула видео отработки связки 🎥",
               "Не смогу в субботу, заболела 🤒", "Когда будет известен состав на шоу в Alte Oper?",
               "Можно оплатить абонемент наличными?", "Где взять музыку к новой постановке?",
               "Привела подругу, можно на пробное?", "Костюм мне мал, нужен размер S",
               "Спасибо за вчерашнюю репетицию, это было мощно 🔥", "Я в деле на съёмку клипа!"]
        outs = ["Ок, ждём!", "Супер, посмотрю вечером и дам фидбек", "Выздоравливай, держим место в номере",
                "Состав опубликую в пятницу", "Да, можно. Отметь в боте /pay", "Отправил ссылку в общий чат"]
        tg_dancers = [x[0] for x in dancers if x[4] == "active"]
        for i in range(340):
            dd = TODAY - timedelta(days=int(R.expovariate(1 / 40)))
            did = R.choice(tg_dancers)
            c.execute("INSERT INTO messages(dancer_id,date,direction,text,is_read) VALUES(?,?,?,?,?)",
                      (did, d(dd) + f" {R.randint(8, 22):02d}:{R.randint(0, 59):02d}", "in", R.choice(ins),
                       0 if dd >= TODAY - timedelta(days=1) and R.random() < .7 else 1))
            if R.random() < .75:
                c.execute("INSERT INTO messages(dancer_id,date,direction,text,is_read) VALUES(?,?,?,?,1)",
                          (did, d(dd) + f" {R.randint(8, 23):02d}:{R.randint(0, 59):02d}", "out", R.choice(outs)))
        for i in range(24):
            dd = TODAY - timedelta(days=i * 9 + R.randint(0, 4))
            c.execute("INSERT INTO messages(dancer_id,date,direction,text,kind,is_read) VALUES(NULL,?,?,?,?,1)",
                      (d(dd) + " 10:00", "broadcast",
                       R.choice(["Напоминание: оплата абонемента до 5 числа", "Новый состав на шоу — смотрите /me",
                                 "Сбор на генеральный прогон в субботу в 12:00", "Фото с выступления в общем альбоме 📸"]),
                       "broadcast"))
        # файлы проектов
        for pid, in c.execute("SELECT id FROM projects WHERE status='выполнен' ORDER BY RANDOM() LIMIT 120").fetchall():
            for _ in range(R.randint(1, 4)):
                kind = R.choice(["photo", "photo", "video", "document", "audio"])
                ext = {"photo": "jpg", "video": "mp4", "document": "pdf", "audio": "mp3"}[kind]
                c.execute("INSERT INTO files(project_id,date,uploaded_by,kind,filename,size,caption) VALUES(?,?,?,?,?,?,?)",
                          (pid, d(TODAY - timedelta(days=R.randint(0, 800))), R.choice(["руководитель", "танцор"]), kind,
                           f"{kind}_{pid}_{R.randint(100, 999)}.{ext}", R.randint(200_000, 90_000_000),
                           {"photo": "Фото с события", "video": "Видео номера", "document": "Договор / техрайдер",
                            "audio": "Фонограмма"}[kind]))
    print("Готово:", DB_PATH)
    for t in ["dancers", "clients", "projects", "transactions", "communications", "attendance", "messages", "files"]:
        print(f"  {t:15} {db.one(f'SELECT COUNT(*) n FROM {t}')['n']}")


if __name__ == "__main__":
    main(force="--force" in sys.argv)
