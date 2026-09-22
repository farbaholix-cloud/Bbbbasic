# Счета (Rechnung) — создание по вводным

Как бот выставляет немецкий счёт художника-фрилансера и что в нём обязано быть.
Технически PDF собирает `invoice.py::generate_invoice`, вызывается из
`bot.py` (action `invoice` и текстовая команда «выставь счёт …»).

## Что нужно от пользователя (минимум)

- **Получатель** (`recipient`): название и адрес, каждая часть с новой строки.
  Пример: `Cosmopop GmbH\nVithursan Thanabalasingam\nUnteres Rheinufer 39\n\n67061 Ludwigshafen`.
- **Позиции** (`items`): список `{desc, price, qty}`. `desc` — описание работы
  **на немецком**, профессионально, с умляутами (напр. «Künstlerische Gestaltung
  der Fassade», «LFP26 Graffiti, Bühne 2 – Vorauszahlung»). `qty` по умолчанию 1.
- Опционально: обращение (`salutation`, напр. «Herr Thanabalasingam»),
  номер клиента (`customer_no`), вводная фраза (`intro`), дата (`when`).

Если не хватает получателя или суммы — спросить одним вопросом, не выдумывать.

## Структура счёта (шаблон)

Соответствует образцу пользователя:
1. Шапка: имя + «Graffiti Künstler», справа серый блок — адрес, телефон, email,
   Pers. Identifikationsnummer, Steuernummer.
2. Блок получателя.
3. «Ort, DD. Monat YYYY» (город + немецкая дата).
4. **Rechnung** + `Rechnungsnummer.: …` (+ Kundennummer, если задан).
5. Вводная фраза, затем таблица: Pos | Anzahl | Bezeichnung | Einzelpreis (€) | Betrag (€).
6. Строка по НДС (см. ниже).
7. Банковские реквизиты: Empfänger, Bank, IBAN, BIC.
8. «Vielen Dank für Ihren Auftrag!» + подпись.

Немецкий формат сумм: `2.000,00` (точка — тысячи, запятая — дробь).

## Реквизиты отправителя и секреты

`generate_invoice` берёт реквизиты из таблицы `settings` (ключи `inv_*`).
**Секретные поля никогда не в коде/git**: `inv_iban`, `inv_bic`,
`inv_steuernummer`, `inv_ident_nr`. Если они не заданы — в PDF попадёт
плейсхолдер (`[IBAN]` и т.п.), а не реальное значение.
Задать их владельцу: секретарю команда `/setinvoicedata <поле> <значение>`
(секретное сообщение бот сразу удаляет из чата). Неконфиденциальные брендовые
поля (`name`, `title`, `street`, `phone`, `email`, `city`, `bank`) имеют дефолты
и тоже переопределяются этой командой.

## Ключевое решение: §19 UStG vs 19 % USt

Это единственное «юридическое» место счёта — какую строку по НДС ставить.

- **Kleinunternehmer (§19 UStG)** — счёт **без НДС**, обязательная оговорка:
  «Als Kleinunternehmer im Sinne von § 19 Abs. 1 UStG wird die Umsatzsteuer
  nicht berechnet.» Для владельца — только счета до 31.12.2025.
- **Regelbesteuerung** — если статус Kleinunternehmer утрачен, счёт **с НДС**:
  Netto + 19 % USt + Brutto (`generate_invoice(..., vat_rate=19)`). **Для владельца — с 01.01.2026.**
  В счёте также обязателен USt-IdNr. или Steuernummer.

**РЕШЕНИЕ (с 16.09.2026): все счета — с 19 % USt.** Finanzamt Frankfurt am Main
письмом от 16.09.2026 подтвердил: с 01.01.2026 Regelbesteuerung обязательна
(подробно — `references/kleinunternehmer.md`). Бот сам подставляет `vat_rate=19`,
если ставка не задана; оговорка §19 больше не ставится. Другая ставка (7 %) —
только если владелец прямо её назовёт. Счета 2026 года, выставленные ещё по §19,
исправляются по §31 Abs. 5 UStDV — дело `[ust]`.

## Номер счёта

`next_invoice_number()` в `bot.py`: база `DDMMYY`, при повторе за день — суффикс
`-N`. Пользователь может задать свой номер (напр. `20260629-1`).
