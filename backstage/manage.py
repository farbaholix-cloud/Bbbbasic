"""
Управление Backstage из консоли сервера (когда админка ещё не открыта или нужен скрипт).

  python manage.py add <код> "<Название>" [бюджет$]   — новый клиент, печатает ссылку
  python manage.py list                               — клиенты и расход
  python manage.py key <код>                          — новый ключ клиента
  python manage.py budget <код> <$>                   — месячный лимит
"""
import os
import sys

from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(HERE, ".env"))

import store  # noqa: E402

BASE = os.environ.get("BACKSTAGE_PUBLIC_URL", f"http://<IP-сервера>:{os.environ.get('BACKSTAGE_PORT', '8800')}")


def by_slug(slug):
    with store.db() as conn:
        row = conn.execute("SELECT id FROM clients WHERE slug=?", (slug,)).fetchone()
    if not row:
        sys.exit(f"нет клиента с кодом {slug}")
    return row["id"]


def main(argv):
    store.init()
    if len(argv) >= 3 and argv[0] == "add":
        budget = float(argv[3]) if len(argv) > 3 else 20.0
        _, key = store.create_client(argv[1].lower(), argv[2], budget=budget)
        print(f"Клиент создан. Персональная ссылка (показывается один раз):\n  {BASE}/c/{argv[1].lower()}?k={key}")
    elif argv[:1] == ["list"]:
        for c in store.list_clients():
            print(f"{c['id']:>3}  {c['slug']:<20} {c['name']:<24} ${c['spent_month']:.2f} / ${c['monthly_budget']:.0f} "
                  f"(всего ${c['spent_total']:.2f}){'' if c['active'] else '  [отключён]'}")
    elif len(argv) == 2 and argv[0] == "key":
        key = store.reset_key(by_slug(argv[1]))
        print(f"Новая ссылка:\n  {BASE}/c/{argv[1]}?k={key}")
    elif len(argv) == 3 and argv[0] == "budget":
        store.update_client(by_slug(argv[1]), monthly_budget=float(argv[2]))
        print("ок")
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
