"""
Языки Backstage для клиентов: английский, немецкий, украинский.

Всё, что видит клиент, — тексты ошибок, приветствие Майи, стартовый дашборд,
названия ремёсел и имена агентов — берётся отсюда по client.lang. Внутренние
промпты агентов остаются как есть: модель получает правило «отвечай на языке
клиента» в каждом контексте (lang_rule).
"""

LANGS = ("en", "de", "ua")
DEFAULT = "en"


def norm(lang):
    """Украинский у нас — 'ua'. Код ISO 'uk' (браузеры) и старые клиенты с 'ru' сводятся к нему."""
    lang = str(lang or "").lower()[:2]
    if lang in ("ru", "uk"):
        return "ua"
    return lang if lang in LANGS else DEFAULT


MSG = {
    "too_many": {"en": "Too many attempts — please wait 10 minutes.",
                 "de": "Zu viele Versuche — bitte warte 10 Minuten.",
                 "ua": "Забагато спроб — зачекай 10 хвилин."},
    "too_many_slug": {"en": "Too many attempts for this name — please wait 15 minutes.",
                      "de": "Zu viele Versuche für diesen Namen — bitte warte 15 Minuten.",
                      "ua": "Забагато спроб для цього імені — зачекай 15 хвилин."},
    "bad_login": {"en": "Wrong login name or PIN", "de": "Login-Name oder PIN falsch",
                  "ua": "Неправильне ім'я або PIN-код"},
    "need_login": {"en": "Please log in", "de": "Bitte melde dich an", "ua": "Потрібно увійти"},
    "signup_closed": {"en": "Sign-up is closed right now. Write to the agency and we'll send you an invitation.",
                      "de": "Die Registrierung ist gerade geschlossen. Schreib der Agentur — du bekommst eine Einladung.",
                      "ua": "Реєстрацію зараз закрито. Напиши агенції — надішлемо запрошення."},
    "try_again": {"en": "That didn't work, please try again.", "de": "Das hat nicht geklappt, versuch es noch einmal.",
                  "ua": "Не вийшло, спробуй ще раз."},
    "form_stale": {"en": "The form is out of date or was filled in too fast — please reload the page.",
                   "de": "Das Formular ist veraltet oder wurde zu schnell ausgefüllt — bitte lade die Seite neu.",
                   "ua": "Форма застаріла або заповнена надто швидко — онови сторінку."},
    "device_limit": {"en": "Someone has already signed up from this device today. Please try again tomorrow.",
                     "de": "Von diesem Gerät gab es heute schon eine Registrierung. Versuch es morgen wieder.",
                     "ua": "З цього пристрою сьогодні вже реєструвалися. Спробуй завтра."},
    "daily_full": {"en": "All places for new members are taken for today — come back tomorrow.",
                   "de": "Für heute sind alle Plätze vergeben — schau morgen wieder vorbei.",
                   "ua": "На сьогодні місця для нових учасників закінчилися — зазирни завтра."},
    "name_short": {"en": "What's your name? At least two characters.",
                   "de": "Wie heißt du? Mindestens zwei Zeichen.",
                   "ua": "Як тебе звати? Хоча б два символи."},
    "slug_bad": {"en": "Login name: 3–25 Latin letters, digits or hyphens.",
                 "de": "Login-Name: 3–25 lateinische Buchstaben, Ziffern oder Bindestriche.",
                 "ua": "Ім'я для входу: 3–25 латинських літер, цифр або дефісів."},
    "pin_bad": {"en": "PIN: 4–8 digits, and nothing as simple as 1234 or 1111.",
                "de": "PIN: 4–8 Ziffern und nicht so einfach wie 1234 oder 1111.",
                "ua": "PIN-код: 4–8 цифр, і не такий простий, як 1234 чи 1111."},
    "need_agree": {"en": "Please agree to data storage.", "de": "Bitte stimme der Datenspeicherung zu.",
                   "ua": "Потрібна згода на зберігання даних."},
    "slug_taken": {"en": "This name is taken — try another one.", "de": "Dieser Name ist vergeben — probier einen anderen.",
                   "ua": "Це ім'я вже зайняте — спробуй інше."},
    "job_missing": {"en": "Task not found", "de": "Aufgabe nicht gefunden", "ua": "Завдання не знайдено"},
    "empty_msg": {"en": "Empty message", "de": "Leere Nachricht", "ua": "Порожнє повідомлення"},
    "busy": {"en": "The team is still answering your previous message",
             "de": "Das Team beantwortet noch deine letzte Nachricht",
             "ua": "Команда ще відповідає на попереднє повідомлення"},
    "bad_tg": {"en": "This doesn't look like a bot token from @BotFather",
               "de": "Das sieht nicht nach einem Bot-Token von @BotFather aus",
               "ua": "Це не схоже на токен бота від @BotFather"},
    "too_big": {"en": "Request too large (30 MB limit)", "de": "Anfrage zu groß (Limit 30 MB)",
                "ua": "Завеликий запит (ліміт 30 МБ)"},
    "team_error": {"en": "Team error: {e}", "de": "Fehler im Team: {e}", "ua": "Помилка команди: {e}"},
    "value": {"en": "Value", "de": "Wert", "ua": "Значення"},
    "team_error_generic": {"en": "Something went wrong on our side. Please try again in a minute.",
                           "de": "Bei uns ist etwas schiefgelaufen. Versuch es in einer Minute noch einmal.",
                           "ua": "У нас щось пішло не так. Спробуй ще раз за хвилину."},
    "mail_bad_server": {"en": "Please use your mail provider's public SMTP server (ports 465, 587, 25 or 2525).",
                        "de": "Bitte den öffentlichen SMTP-Server deines Mailanbieters verwenden (Port 465, 587, 25 oder 2525).",
                        "ua": "Вкажи публічний SMTP-сервер свого поштового сервісу (порти 465, 587, 25 або 2525)."},
    "quota_deep": {"en": "The free version allows {n} deep analyses a day. You can run another one tomorrow — the regular chat keeps working.",
                   "de": "In der kostenlosen Version sind {n} Tiefenanalysen pro Tag möglich. Morgen geht es weiter — der normale Chat funktioniert.",
                   "ua": "У безкоштовній версії — {n} глибоких аналізи на день. Завтра знову можна, а звичайний чат працює."},
    "quota_chat": {"en": "That's today's limit for the free version — {n} team replies. We'll continue tomorrow; everything is saved.",
                   "de": "Das Tageslimit der kostenlosen Version ist erreicht — {n} Antworten des Teams. Morgen geht's weiter, alles ist gespeichert.",
                   "ua": "На сьогодні ліміт безкоштовної версії — {n} відповідей команди. Завтра продовжимо — усе збережено."},
    "budget_out": {"en": "The monthly AI budget (${b}) is used up. The platform owner can raise the limit.",
                   "de": "Das monatliche KI-Budget (${b}) ist aufgebraucht. Der Plattform-Betreiber kann das Limit erhöhen.",
                   "ua": "Місячний бюджет ШІ (${b}) вичерпано. Власник платформи може підняти ліміт."},
    "refused": {"en": "The model declined this request. Try rephrasing the task.",
                "de": "Das Modell hat diese Anfrage abgelehnt. Formuliere die Aufgabe bitte anders.",
                "ua": "Модель відхилила це прохання. Спробуй переформулювати завдання."},
    "empty_reply": {"en": "(empty reply)", "de": "(leere Antwort)", "ua": "(порожня відповідь)"},
    "cut": {"en": "_(the reply hit the length limit — ask to continue)_",
            "de": "_(die Antwort hat das Längenlimit erreicht — bitte ums Weiterschreiben)_",
            "ua": "_(відповідь уперлася в ліміт довжини — попроси продовжити)_"},
    "team_work": {"en": "Team activity", "de": "Teamarbeit", "ua": "Робота команди"},
    "team_work_delta": {"en": "requests in 31 days · subscription", "de": "Anfragen in 31 Tagen · Abo",
                        "ua": "запитів за 31 день · підписка"},
    "budget_of": {"en": "of ${b}", "de": "von ${b}", "ua": "з ${b}"},
    "subscription": {"en": "subscription", "de": "Abo", "ua": "підписка"},
    "new_widget": {"en": "New widget", "de": "Neues Widget", "ua": "Новий віджет"},
    "file": {"en": "file", "de": "Datei", "ua": "файл"},
    "about": {"en": "About me", "de": "Über mich", "ua": "Про мене"},
    "goal": {"en": "Goal for the next 12 months", "de": "Ziel für die nächsten 12 Monate", "ua": "Мета на 12 місяців"},
    "links": {"en": "Links", "de": "Links", "ua": "Посилання"},
    "first_review": {"en": "Maya, please look at my questionnaire and do a first review",
                     "de": "Maya, schau dir bitte meinen Fragebogen an und mach eine erste Analyse",
                     "ua": "Майє, подивись мою анкету і зроби перший розбір"},
    "trial_over": {"en": "Your free trial has ended. Everything you've built is saved — choose a plan in ⚙ Settings to keep working with the team.",
                   "de": "Dein kostenloser Testzeitraum ist vorbei. Alles bleibt gespeichert — wähl in ⚙ Einstellungen einen Tarif, um mit dem Team weiterzuarbeiten.",
                   "ua": "Безкоштовний пробний період закінчився. Усе збережено — обери тариф у ⚙ Налаштуваннях, щоб працювати з командою далі."},
    "radar_title": {"en": "Opportunities radar", "de": "Chancen-Radar", "ua": "Радар можливостей"},
    "radar_intro": {"en": "This week's radar: Ruben found {n} new opportunities that fit you.",
                    "de": "Radar der Woche: Ruben hat {n} neue Chancen gefunden, die zu dir passen.",
                    "ua": "Радар тижня: Рубен знайшов нових можливостей для тебе: {n}."},
    "radar_outro": {"en": "I've added them to the “Opportunities radar” on your dashboard. Tell me which one to go for — Hanna will prepare the application.",
                    "de": "Ich habe sie ins „Chancen-Radar“ auf deinem Dashboard gelegt. Sag mir, worauf wir gehen — Hanna bereitet die Bewerbung vor.",
                    "ua": "Я додала їх у «Радар можливостей» на дашборді. Скажи, на що йдемо, — Ганна підготує заявку."},
    "deadline_on": {"en": "deadline {d}", "de": "Frist {d}", "ua": "дедлайн {d}"},
    "in_days": {"en": "in {n} days ({d})", "de": "in {n} Tagen ({d})", "ua": "через {n} дн. ({d})"},
    "remind_intro": {"en": "Deadline check — these are coming up:", "de": "Fristen-Check — das steht bald an:",
                     "ua": "Перевірка дедлайнів — ось що наближається:"},
    "remind_outro": {"en": "Need help with any of them? Just write — the team will take it on.",
                     "de": "Brauchst du bei etwas Hilfe? Schreib einfach — das Team übernimmt.",
                     "ua": "Потрібна допомога з чимось? Просто напиши — команда візьметься."},
    "doc_request": {"en": "Please prepare: {kind}. {brief}", "de": "Bitte vorbereiten: {kind}. {brief}",
                    "ua": "Підготуй, будь ласка: {kind}. {brief}"},
    "doc_ready": {"en": "📄 The document “{title}” is ready — open it in the Workspace → Documents (DOCX and PDF).",
                  "de": "📄 Das Dokument „{title}“ ist fertig — du findest es in der Arbeitsmappe → Dokumente (DOCX und PDF).",
                  "ua": "📄 Документ «{title}» готовий — він у Робочій теці → Документи (DOCX і PDF)."},
    "too_big_file": {"en": "The file is larger than 20 MB.", "de": "Die Datei ist größer als 20 MB.", "ua": "Файл більший за 20 МБ."},
    "vault_full": {"en": "Your materials folder is full ({n} MB). Delete something first.",
                   "de": "Dein Materialordner ist voll ({n} MB). Lösch zuerst etwas.",
                   "ua": "Тека матеріалів заповнена ({n} МБ). Спершу видали щось."},
    "mail_incomplete": {"en": "Fill in server, login, password and sender address.", "de": "Bitte Server, Login, Passwort und Absenderadresse ausfüllen.",
                        "ua": "Заповни сервер, логін, пароль і адресу відправника."},
    "mail_login_failed": {"en": "Couldn't log in to your mailbox: {e}", "de": "Anmeldung am Postfach fehlgeschlagen: {e}",
                          "ua": "Не вдалося увійти в поштову скриньку: {e}"},
    "mail_bad_to": {"en": "Check the recipient address (up to 3, separated by commas).", "de": "Prüf die Empfängeradresse (bis zu 3, mit Komma getrennt).",
                    "ua": "Перевір адресу отримувача (до 3, через кому)."},
    "mail_limit": {"en": "Up to {n} emails a day — protection against spam. Try again tomorrow.",
                   "de": "Bis zu {n} E-Mails pro Tag — Schutz vor Spam. Morgen geht es weiter.",
                   "ua": "До {n} листів на день — захист від спаму. Спробуй завтра."},
    "mail_send_failed": {"en": "The email wasn't sent: {e}", "de": "Die E-Mail wurde nicht gesendet: {e}", "ua": "Лист не надіслано: {e}"},
    "quota_tokens": {"en": "That's today's work volume for your plan. We'll continue tomorrow — everything is saved.",
                     "de": "Das Arbeitsvolumen deines Tarifs für heute ist erreicht. Morgen geht's weiter — alles ist gespeichert.",
                     "ua": "На сьогодні обсяг роботи за твоїм тарифом вичерпано. Завтра продовжимо — усе збережено."},
    "platform_pause": {"en": "The team is taking a short break today because of very high demand. Please try again tomorrow — everything is saved.",
                       "de": "Wegen sehr hoher Nachfrage macht das Team heute eine Pause. Bitte versuch es morgen wieder — alles ist gespeichert.",
                       "ua": "Через дуже високе навантаження команда сьогодні на паузі. Спробуй завтра — усе збережено."},
    "request_cap": {"en": "_(this answer reached its size limit — ask me to continue if you need more)_",
                    "de": "_(diese Antwort hat ihr Umfangslimit erreicht — bitte ums Weitermachen, wenn du mehr brauchst)_",
                    "ua": "_(ця відповідь досягла ліміту обсягу — попроси продовжити, якщо потрібно більше)_"},
    "restart_limit": {"en": "You can start from scratch up to {n} times a day. Please try again tomorrow.",
                      "de": "Von vorn beginnen geht bis zu {n}-mal am Tag. Versuch es morgen wieder.",
                      "ua": "Почати з нуля можна до {n} разів на день. Спробуй завтра."},
    "potential": {"en": "Potential check", "de": "Potenzial-Check", "ua": "Перевірка потенціалу"},
}


def t(lang, key, **kw):
    m = MSG[key]
    s = m.get(norm(lang)) or m[DEFAULT]
    return s.format(**kw) if kw else s


AGENTS = {
    "en": {"maya": ("Maya", "Producer"), "ruben": ("Ruben", "Scout"), "hanna": ("Hanna", "Grant writer"),
           "konrad": ("Konrad", "Legal"), "noa": ("Noa", "Online marketing"), "tarik": ("Tarik", "PR & offline"),
           "iris": ("Iris", "Content & video"), "ben": ("Ben", "Finance"), "chuck": ("Chuck", "Security")},
    "de": {"maya": ("Maya", "Produzentin"), "ruben": ("Ruben", "Scout"), "hanna": ("Hanna", "Antragsautorin"),
           "konrad": ("Konrad", "Recht"), "noa": ("Noa", "Online-Marketing"), "tarik": ("Tarik", "PR & offline"),
           "iris": ("Iris", "Content & Video"), "ben": ("Ben", "Finanzen"), "chuck": ("Chuck", "Sicherheit")},
    "ua": {"maya": ("Майя", "Продюсерка"), "ruben": ("Рубен", "Скаут"), "hanna": ("Ганна", "Грантрайтерка"),
           "konrad": ("Конрад", "Юридичний відділ"), "noa": ("Ноа", "Онлайн-маркетинг"), "tarik": ("Тарік", "PR і офлайн"),
           "iris": ("Ірис", "Контент і відео"), "ben": ("Бен", "Фінанси"), "chuck": ("Чак", "Захисник")},
}


def agents(lang, base):
    """Состав команды для панели: имена и роли на языке клиента, остальное из agents.json."""
    names = AGENTS[norm(lang)]
    return {k: {**v, "name": names.get(k, (v["name"],))[0], "role": names.get(k, (None, v["role"]))[1]}
            for k, v in base.items()}


CRAFTS = {
    "en": {"animation": "animation", "illustration": "illustration", "painting": "painting and graphic art",
           "mural": "murals and graffiti", "music": "music and DJing", "dance": "dance and choreography",
           "theatre": "theatre and performance", "film": "film and video", "photo": "photography", "design": "design",
           "fashion": "fashion and costume", "writing": "writing and screenwriting", "other": "creative practice"},
    "de": {"animation": "Animation", "illustration": "Illustration", "painting": "Malerei und Grafik",
           "mural": "Murals und Graffiti", "music": "Musik und DJing", "dance": "Tanz und Choreografie",
           "theatre": "Theater und Performance", "film": "Film und Video", "photo": "Fotografie", "design": "Design",
           "fashion": "Mode und Kostüm", "writing": "Literatur und Drehbuch", "other": "kreative Praxis"},
    "ua": {"animation": "анімація", "illustration": "ілюстрація", "painting": "живопис і графіка",
           "mural": "мурали та графіті", "music": "музика і DJ", "dance": "танці та хореографія",
           "theatre": "театр і перформанс", "film": "кіно і відео", "photo": "фотографія", "design": "дизайн",
           "fashion": "мода і костюм", "writing": "література і сценарії", "other": "творча практика"},
}

BOARDS = {
    "en": {"animation": ["Ideas", "Storyboard", "Animation", "Delivered"],
           "dance": ["Ideas", "Choreography", "Rehearsals", "Performances"],
           "theatre": ["Ideas", "Rehearsals", "Premiere", "Touring"],
           "film": ["Ideas", "Script", "Shooting", "Editing"],
           "painting": ["Ideas", "On the easel", "Finished", "Sold"],
           "design": ["Inbox", "Concept", "Revisions", "Delivered"],
           "fashion": ["Ideas", "Sketches", "Production", "Show / sale"],
           "writing": ["Ideas", "Draft", "Editing", "Published"],
           "illustration": ["Ideas", "Sketches", "In progress", "Delivered"],
           "music": ["Demos", "In progress", "Release", "Gigs"],
           "mural": ["Inbox", "Sketch", "On the wall", "Done"],
           "photo": ["Ideas", "Shoot", "Editing", "Delivered"],
           "_": ["Inbox", "In progress", "Waiting", "Done"]},
    "de": {"animation": ["Ideen", "Storyboard", "Animation", "Abgegeben"],
           "dance": ["Ideen", "Choreografie", "Proben", "Auftritte"],
           "theatre": ["Ideen", "Proben", "Premiere", "Tournee"],
           "film": ["Ideen", "Drehbuch", "Dreh", "Schnitt"],
           "painting": ["Ideen", "Auf der Staffelei", "Fertig", "Verkauft"],
           "design": ["Eingang", "Konzept", "Korrekturen", "Abgegeben"],
           "fashion": ["Ideen", "Entwürfe", "Fertigung", "Show / Verkauf"],
           "writing": ["Ideen", "Entwurf", "Lektorat", "Veröffentlicht"],
           "illustration": ["Ideen", "Skizzen", "In Arbeit", "Abgegeben"],
           "music": ["Demos", "In Arbeit", "Release", "Gigs"],
           "mural": ["Eingang", "Entwurf", "An der Wand", "Fertig"],
           "photo": ["Ideen", "Shooting", "Bearbeitung", "Abgegeben"],
           "_": ["Eingang", "In Arbeit", "Warten auf Antwort", "Fertig"]},
    "ua": {"animation": ["Ідеї", "Розкадровка", "Анімація", "Здано"],
           "dance": ["Ідеї", "Постановка", "Репетиції", "Виступи"],
           "theatre": ["Ідеї", "Репетиції", "Прем'єра", "Гастролі"],
           "film": ["Ідеї", "Сценарій", "Зйомка", "Монтаж"],
           "painting": ["Ідеї", "Полотна в роботі", "Готово", "Продано"],
           "design": ["Вхідні", "Концепт", "Правки", "Здано"],
           "fashion": ["Ідеї", "Ескізи", "Пошиття", "Показ / продаж"],
           "writing": ["Ідеї", "Чернетка", "Редагування", "Видано"],
           "illustration": ["Ідеї", "Ескізи", "В роботі", "Здано"],
           "music": ["Демо", "В роботі", "Реліз", "Виступи"],
           "mural": ["Вхідні", "Ескіз", "На стіні", "Готово"],
           "photo": ["Ідеї", "Зйомка", "Обробка", "Здано"],
           "_": ["Вхідні", "В роботі", "Чекаємо відповіді", "Готово"]},
}

LISTS = {
    "en": {"animation": "Festivals, pitches and deadlines", "music": "Contests, festivals and releases",
           "mural": "Contests, tenders and deadlines", "dance": "Contests, festivals and castings",
           "theatre": "Festivals, grants and touring", "film": "Festivals, pitches and grants",
           "_": "Deadlines and applications"},
    "de": {"animation": "Festivals, Pitches und Fristen", "music": "Wettbewerbe, Festivals und Releases",
           "mural": "Wettbewerbe, Ausschreibungen und Fristen", "dance": "Wettbewerbe, Festivals und Castings",
           "theatre": "Festivals, Förderungen und Tourneen", "film": "Festivals, Pitches und Förderungen",
           "_": "Fristen und Bewerbungen"},
    "ua": {"animation": "Фестивалі, пітчинги та дедлайни", "music": "Конкурси, фестивалі та релізи",
           "mural": "Конкурси, тендери та дедлайни", "dance": "Конкурси, фестивалі та кастинги",
           "theatre": "Фестивалі, гранти та гастролі", "film": "Фестивалі, пітчинги та гранти",
           "_": "Дедлайни та заявки"},
}

SEED = {
    "en": {"income": "Income this month", "apps": "Applications in progress", "budget": "AI budget this month",
           "projects": "Projects", "card": "Tell Maya about your practice", "chart": "Income by month",
           "series": "Income", "profile": "Practice profile",
           "profile_text": "Who I am, what I do, what I want to achieve in 12 months. The team reads this note before every reply."},
    "de": {"income": "Einnahmen diesen Monat", "apps": "Laufende Bewerbungen", "budget": "KI-Budget diesen Monat",
           "projects": "Projekte", "card": "Maya von deiner Arbeit erzählen", "chart": "Einnahmen pro Monat",
           "series": "Einnahmen", "profile": "Praxisprofil",
           "profile_text": "Wer ich bin, was ich mache, was ich in 12 Monaten erreichen will. Das Team liest diese Notiz vor jeder Antwort."},
    "ua": {"income": "Дохід за місяць", "apps": "Заявки в роботі", "budget": "Бюджет ШІ на місяць",
           "projects": "Проєкти", "card": "Розповісти Майї про свою практику", "chart": "Дохід за місяцями",
           "series": "Дохід", "profile": "Профіль практики",
           "profile_text": "Хто я, що роблю, чого хочу досягти за 12 місяців. Команда читає цю нотатку перед кожною відповіддю."},
}

SEC = {
    "sev": {"critical": ("critical", "kritisch", "критично"), "important": ("important", "wichtig", "важливо"),
            "later": ("can wait", "kann warten", "можна пізніше")},
    "cert_expired": ("The website's security certificate has expired — visitors see a warning.",
                     "Das Sicherheitszertifikat der Website ist abgelaufen — Besucher sehen eine Warnung.",
                     "Сертифікат безпеки сайту прострочений — відвідувачі бачать попередження."),
    "cert_soon": ("The certificate expires in {d} days — check that it renews automatically.",
                  "Das Zertifikat läuft in {d} Tagen ab — prüf, ob es sich automatisch erneuert.",
                  "Сертифікат спливає через {d} дн. — перевір, чи він оновлюється автоматично."),
    "cert_invalid": ("The certificate isn't valid for this domain — browsers show a warning.",
                     "Das Zertifikat ist für diese Domain ungültig — Browser zeigen eine Warnung.",
                     "Сертифікат не дійсний для цього домену — браузери показують попередження."),
    "no_https": ("The website doesn't open via HTTPS at all.", "Die Website ist gar nicht per HTTPS erreichbar.",
                 "Сайт узагалі не відкривається через HTTPS."),
    "no_redirect": ("http:// doesn't redirect to https:// — some visits stay unencrypted.",
                    "http:// leitet nicht auf https:// um — manche Besuche bleiben unverschlüsselt.",
                    "http:// не перенаправляє на https:// — частина відвідувань лишається без шифрування."),
    "no_hsts": ("No HSTS header: browsers aren't told to always use HTTPS.",
                "Kein HSTS-Header: Browser werden nicht angewiesen, immer HTTPS zu nutzen.",
                "Немає заголовка HSTS: браузерам не сказано завжди використовувати HTTPS."),
    "no_frame": ("The site can be embedded in other pages (no clickjacking protection).",
                 "Die Seite lässt sich in fremde Seiten einbetten (kein Clickjacking-Schutz).",
                 "Сайт можна вбудувати в чужі сторінки (немає захисту від clickjacking)."),
    "no_nosniff": ("Missing X-Content-Type-Options header.", "Header X-Content-Type-Options fehlt.",
                   "Бракує заголовка X-Content-Type-Options."),
    "version_header": ("The server reveals its software version ({d}).", "Der Server verrät seine Softwareversion ({d}).",
                       "Сервер показує версію свого ПЗ ({d})."),
    "cms_version": ("The site shows its CMS version ({d}) — attackers look for outdated versions. Hide it and keep the CMS updated.",
                    "Die Seite zeigt ihre CMS-Version ({d}) — Angreifer suchen gezielt nach veralteten Versionen. Verstecken und das CMS aktuell halten.",
                    "Сайт показує версію CMS ({d}) — зловмисники шукають застарілі версії. Сховай її й оновлюй CMS."),
    "no_spf": ("Your domain has no SPF record — anyone can send emails pretending to be you.",
               "Deine Domain hat keinen SPF-Eintrag — jede:r kann E-Mails in deinem Namen verschicken.",
               "Твій домен не має запису SPF — будь-хто може надсилати листи від твого імені."),
    "no_dmarc": ("No DMARC record — fake emails from your domain aren't blocked.",
                 "Kein DMARC-Eintrag — gefälschte E-Mails von deiner Domain werden nicht blockiert.",
                 "Немає запису DMARC — підроблені листи з твого домену не блокуються."),
    "intro": ("🛡️ Chuck here — weekly security check of {site}:", "🛡️ Hier ist Chuck — wöchentlicher Sicherheits-Check von {site}:",
              "🛡️ Це Чак — щотижнева перевірка безпеки {site}:"),
    "more": ("+ {n} smaller points.", "+ {n} kleinere Punkte.", "+ ще {n} дрібніших пунктів."),
    "outro": ("Write to me (Chuck) for step-by-step instructions — most fixes take 5–15 minutes.",
              "Schreib mir (Chuck) für eine Schritt-für-Schritt-Anleitung — das meiste ist in 5–15 Minuten erledigt.",
              "Напиши мені (Чаку) — дам покрокову інструкцію; більшість виправлень займає 5–15 хвилин."),
}


def sec_line(lang, f):
    i = LANGS.index(norm(lang))
    return f"{SEC['sev'][f['sev']][i]}: " + SEC[f["code"]][i].replace("{d}", str(f.get("detail") or ""))


def sec_text(lang, key, **kw):
    s = SEC[key][LANGS.index(norm(lang))]
    return s.format(**kw) if kw else s


DOC_KINDS = {
    "en": {"application": "Application", "letter": "Cover letter", "statement": "Artist statement", "bio": "Short bio",
           "offer": "Commercial offer", "estimate": "Cost estimate", "email": "Email to a client"},
    "de": {"application": "Bewerbung", "letter": "Anschreiben", "statement": "Künstlerisches Statement", "bio": "Kurzbiografie",
           "offer": "Angebot", "estimate": "Kostenvoranschlag", "email": "E-Mail an Kundschaft"},
    "ua": {"application": "Заявка", "letter": "Супровідний лист", "statement": "Artist statement", "bio": "Коротка біографія",
           "offer": "Комерційна пропозиція", "estimate": "Кошторис", "email": "Лист клієнту"},
}

LANG_NAME = {"en": "English", "de": "German (informal “du”)", "ua": "Ukrainian"}


def lang_rule(lang):
    """Правило для агентов: промпты у нас русские, а отвечать нужно на языке клиента."""
    L = norm(lang)
    names = ", ".join(n for n, _ in AGENTS[L].values())
    extra = " Never answer in Russian." if L == "ua" else ""
    return (f"LANGUAGE: the client works in {LANG_NAME[L]}. Write every reply in {LANG_NAME[L]}, whatever language "
            f"these instructions, the profile or earlier messages are in — unless the client clearly switches language "
            f"themselves. Everything you put on the dashboard (titles, cards, list items, notes, KPI captions) and into "
            f"the knowledge base is in {LANG_NAME[L]} too. Team names in this language: {names}.{extra}")


HINTS = {
    "en": {"animation": "“find animation festivals and pitches with deadlines in the next six months” or “help me price a minute of animation”",
           "illustration": "“where can I find children's book commissions?” or “how much should I charge for a cover?”",
           "music": "“plan my release for the coming month” or “find open calls for musicians”",
           "dance": "“find contests and castings for the coming months” or “help me price choreographing a piece”",
           "theatre": "“find festivals and grants for independent theatre”",
           "film": "“find short film festivals with deadlines” or “help me budget a shoot”",
           "painting": "“where could I exhibit this year?” or “how should I price my paintings?”",
           "design": "“help me with my price list” or “where do I find clients?”",
           "fashion": "“find shows and markets for young designers”",
           "writing": "“find contests and publishers for my manuscript”",
           "mural": "“find mural contests near me” or “calculate the price for a 40 m² wall”",
           "photo": "“where can I sell my photos?” or “help me price a shoot”",
           "_": "“find grants and contests for me” or “help me put together a price list”"},
    "de": {"animation": "„finde Animationsfestivals und Pitches mit Fristen im nächsten halben Jahr“ oder „hilf mir, den Preis für eine Minute Animation zu kalkulieren“",
           "illustration": "„wo finde ich Aufträge für Kinderbücher?“ oder „was verlange ich für ein Cover?“",
           "music": "„plane meinen Release für den nächsten Monat“ oder „finde Open Calls für Musiker:innen“",
           "dance": "„finde Wettbewerbe und Castings für die nächsten Monate“ oder „hilf mir beim Preis für eine Choreografie“",
           "theatre": "„finde Festivals und Förderungen für freies Theater“",
           "film": "„finde Kurzfilmfestivals mit Fristen“ oder „hilf mir beim Drehbudget“",
           "painting": "„wo kann ich dieses Jahr ausstellen?“ oder „wie bepreise ich meine Bilder?“",
           "design": "„hilf mir mit meiner Preisliste“ oder „wo finde ich Kund:innen?“",
           "fashion": "„finde Shows und Märkte für junge Designer:innen“",
           "writing": "„finde Wettbewerbe und Verlage für mein Manuskript“",
           "mural": "„finde Mural-Wettbewerbe in meiner Nähe“ oder „berechne den Preis für eine 40-m²-Wand“",
           "photo": "„wo kann ich meine Fotos verkaufen?“ oder „hilf mir mit dem Preis für ein Shooting“",
           "_": "„finde Förderungen und Wettbewerbe für mich“ oder „hilf mir, eine Preisliste zu erstellen“"},
    "ua": {"animation": "«знайди фестивалі анімації та пітчинги з дедлайнами на найближчі пів року» або «допоможи порахувати ціну за хвилину анімації»",
           "illustration": "«де шукати замовлення на дитячі книжки» або «скільки брати за обкладинку»",
           "music": "«склади план релізу на місяць» або «знайди open calls для музикантів»",
           "dance": "«знайди конкурси та кастинги на найближчі місяці» або «допоможи з ціною за постановку номера»",
           "theatre": "«знайди фестивалі та гранти для незалежного театру»",
           "film": "«знайди фестивалі короткого метру з дедлайнами» або «допоможи з бюджетом зйомки»",
           "painting": "«де виставитися цього року» або «як оцінити мої картини»",
           "design": "«допоможи з прайсом» або «де шукати клієнтів»",
           "fashion": "«знайди покази та маркети для молодих дизайнерів»",
           "writing": "«знайди конкурси та видавництва для мого рукопису»",
           "mural": "«знайди конкурси на мурали поруч зі мною» або «порахуй ціну стіни 40 м²»",
           "photo": "«де продавати фото» або «допоможи з прайсом на зйомку»",
           "_": "«знайди гранти та конкурси для мене» або «допоможи скласти прайс»"},
}


def welcome(lang, name, craft, goal):
    L = norm(lang)
    first = name.split()[0]
    hint = HINTS[L].get(craft) or HINTS[L]["_"]
    g = goal[:160]
    if L == "de":
        goal_line = f"\n\nDein Ziel habe ich notiert: „{g}“. Wir gehen es Schritt für Schritt an." if goal else ""
        return (f"Hallo {first}! Ich bin Maya, die Produzentin deines Teams. Ich bin dafür da, dass dir Zeit "
                "für die Kunst und fürs Leben bleibt — nicht für Routine.\n\n"
                "Mit mir arbeiten Ruben (findet Chancen), Hanna (schreibt Anträge), Konrad (prüft Verträge), "
                "Noa und Tarik (Promotion), Iris (Content), Ben (Finanzen) und Chuck (Sicherheit). Du musst nicht jedem einzeln schreiben: "
                "schreib mir, ich verteile die Aufgaben und bringe die Antworten zusammen."
                f"{goal_line}\n\nIch habe das Team schon zur ersten Analyse deines Fragebogens geholt: Wir suchen "
                "im Netz nach Chancen für dich und skizzieren die ersten Schritte. Das dauert ein paar Minuten.\n\n"
                "Alles, was wir finden und beschließen, landet von selbst als Kennzahlen im Tab „Dashboard“ — "
                f"dort kannst du einfach reinschauen. Gearbeitet wird hier, im Gespräch. Zum Beispiel: {hint}.")
    if L == "ua":
        goal_line = f"\n\nТвою мету я записала: «{g}». Рухатимемося до неї крок за кроком." if goal else ""
        return (f"Вітаю, {first}! Я Майя, продюсерка твоєї команди. Я тут для того, щоб у тебе лишався час "
                "на творчість і на життя, а не на рутину.\n\n"
                "Зі мною Рубен (шукає можливості), Ганна (пише заявки), Конрад (читає договори), Ноа і Тарік "
                "(просування), Ірис (контент), Бен (гроші) і Чак (безпека). Не треба писати кожному: пиши мені, я роздам завдання "
                "і зберу відповідь."
                f"{goal_line}\n\nЯ вже покликала їх на перший розбір твоєї анкети: пошукаємо для тебе можливості "
                "в інтернеті й намітимо перші кроки. Це займе кілька хвилин.\n\n"
                "Усе, що ми знаходимо й вирішуємо, саме складається в показники на вкладці «Дашборд» — "
                f"туди можна просто зазирати. А робота йде тут, у розмові. Наприклад: {hint}.")
    goal_line = f"\n\nI've noted your goal: “{g}”. We'll work towards it step by step." if goal else ""
    return (f"Hi {first}! I'm Maya, your team's producer. I'm here so that you have time for your art "
            "and for living — not for routine.\n\n"
            "With me are Ruben (finds opportunities), Hanna (writes applications), Konrad (reads contracts), "
            "Noa and Tarik (promotion), Iris (content), Ben (money) and Chuck (security). You don't need to write to each of them: "
            "write to me, I'll hand out the tasks and bring the answers together."
            f"{goal_line}\n\nI've already called the team for a first review of your questionnaire: we'll look "
            "for opportunities online and outline your first steps. It takes a few minutes.\n\n"
            "Everything we find and decide turns into figures on the “Dashboard” tab by itself — "
            f"you can just take a look there now and then. The actual work happens here, in the conversation. "
            f"For example: {hint}.")


def relabel(old, new, w):
    """Смена языка в настройках: стандартные подписи стартового дашборда переводятся,
    всё, что клиент или команда уже переписали, остаётся как есть. None — менять нечего."""
    import copy
    old, new = norm(old), norm(new)
    if old == new:
        return None
    O, N = SEED[old], SEED[new]
    title, cfg, data = w["title"], copy.deepcopy(w["config"]), copy.deepcopy(w["data"])
    for k in ("income", "apps", "budget", "projects", "chart", "profile"):
        if title == O[k]:
            title = N[k]
    for k, v in LISTS[old].items():
        if title == v:
            title = LISTS[new][k]
    if cfg.get("radar") and title == MSG["radar_title"][old]:
        title = MSG["radar_title"][new]
    for k, cols in BOARDS[old].items():
        if cfg.get("columns") == cols:
            cfg["columns"] = BOARDS[new][k]
    for card in data.get("cards") or []:
        if card.get("text") == O["card"]:
            card["text"] = N["card"]
    if data.get("text") == O["profile_text"]:
        data["text"] = N["profile_text"]
    for s in data.get("series") or []:
        if s.get("name") == O["series"]:
            s["name"] = N["series"]
    if (title, cfg, data) == (w["title"], w["config"], w["data"]):
        return None
    return title, cfg, data
