"""SHIFT Summit 2026 (22.10.2026, Goldbach Kirchner, Geiselbach): announcement page "heute" – live calligraphy
and the charity auction. After the summit the same page (same URLs, the QR code points to the DE one) becomes the report."""

DATE_ISO = '2026-10-22'
AUCTION_ISO = '2026-10-22T17:30:00+02:00'
SHIFT_URL = 'https://shiftsummit.de/'
RELATIONING_URL = 'https://www.relationing.de/'
# photos: media_seo.json keys (uploaded from media-new/ by shift_publish.py); missing keys are simply left out
PHOTOS = ['shift-leinwand-detail', 'shift-zeichen']

UI = {
 'de': dict(
    kicker='Heute · SHIFT Summit 2026',
    h1='Farbaholix beim SHIFT Summit: Live-Kalligrafie und Benefiz-Auktion',
    lead='Heute, am 22. Oktober 2026, ist Farbaholix beim SHIFT Summit bei Goldbach Kirchner in Geiselbach. '
         'Um 17:30 Uhr wird eine Leinwand versteigert, die eigens für diesen Tag entstanden ist – die Hälfte des Erlöses geht an Smek, zur Unterstützung in Kyjiw.',
    facts=[('Datum', 'Donnerstag, 22. Oktober 2026'), ('Ort', 'Goldbach Kirchner raumconcepte, Geiselbach – zwischen Aschaffenburg und Hanau'),
           ('Auktion', '17:30 Uhr'), ('Auktionator', 'Dr. Stefan Söhngen'), ('Leinwand', '1 × 2 Meter, Unikat für den SHIFT Summit'),
           ('Erlös', 'die Hälfte an Smek – Unterstützung in Kyjiw')],
    auction_t='Die Benefiz-Auktion um 17:30 Uhr',
    auction=['Die Leinwand im Format 1 × 2 Meter ist speziell für den SHIFT Summit entstanden. Slavik hat sie gemeinsam mit seinem Freund Wolodymyr Wlastin geschaffen – Wissenschaftler und Schreiber. '
             'Auf ihr treffen Kalligrafie und Zeichen aufeinander, darunter das Monogramm von Farbaholix, das Logo von Relationing und das Zeichen von Smek.',
             'Die Auktion leitet Dr. Stefan Söhngen. Die Hälfte des Erlöses geht an Smek – als Unterstützung für Kyjiw.'],
    calli_t='Live-Kalligrafie: Ihr Wort, blind gezogen',
    calli_lead='Während des Summits schreibt Slavik live Kalligrafie – mit Wörtern, die die Gäste selbst mitbringen.',
    steps=[('Zettel ausfüllen', 'Schreiben Sie einen Namen, Ihren Firmennamen, ein Wort oder eine kurze Wortgruppe auf einen Zettel.'),
           ('In die Glasschale', 'Legen Sie den Zettel in die große gläserne Schale in Form einer Halbkugel.'),
           ('Blind gezogen', 'Slavik zieht blind einen Zettel nach dem anderen und schreibt daraus eine kalligrafische Komposition.'),
           ('Zwölf Geschenke', 'Die zwölf Kalligrafien kommen direkt in Rahmen – und Slavik schenkt sie zwölf Glücklichen, noch vor der Auktion.')],
    thanks_t='Danke, Dr. Stefan Söhngen',
    thanks=['Dr. Stefan Söhngen, Geschäftsführer der Relationing GmbH in Frankfurt, hat Farbaholix zum SHIFT Summit eingeladen – und er leitet heute die Auktion.',
            'Er unterstützt uns seit Jahren, aus reinem Respekt vor unserer Arbeit. Dafür: Respekt zurück und von Herzen Danke.'],
    thanks_link='relationing.de',
    about_t='Über den SHIFT Summit',
    about='Der SHIFT Summit ist ein exklusives Offsite-Event zur Bestandsentwicklung: Keynotes, Masterclasses und Matchmaking für Projektentwickler, Bestandshalter, Investoren, Architekten und Planer. '
          'Er läuft von 10 bis 18 Uhr; teilnehmen kann man nur über einen offiziellen Partner des Summits.',
    about_link='shiftsummit.de',
    photos_t='Die Leinwand',
    caps={'shift-leinwand-detail': 'Ausschnitt der Leinwand für die Benefiz-Auktion', 'shift-zeichen': 'Zeichen auf der Leinwand: Monogramm Farbaholix, Logo Relationing, Zeichen von Smek'},
    report='Nach dem Summit erscheint hier der Bericht – mit Fotos, den zwölf Kalligrafien und dem Ergebnis der Auktion.',
    crumb='SHIFT Summit 2026',
    meta=('SHIFT Summit 2026: Live-Kalligrafie & Benefiz-Auktion | Farbaholix',
          'Farbaholix beim SHIFT Summit 2026 in Geiselbach: Live-Kalligrafie und um 17:30 Uhr die Benefiz-Auktion einer Leinwand – die Hälfte des Erlöses geht an Smek, Kyjiw.',
          'SHIFT Summit'),
 ),
 'en': dict(
    kicker='Today · SHIFT Summit 2026',
    h1='Farbaholix at SHIFT Summit: live calligraphy and a charity auction',
    lead='Today, 22 October 2026, Farbaholix is at SHIFT Summit at Goldbach Kirchner in Geiselbach. '
         'At 5:30 pm a canvas created especially for this day goes under the hammer – half of the proceeds go to Smek, to support people in Kyiv.',
    facts=[('Date', 'Thursday, 22 October 2026'), ('Venue', 'Goldbach Kirchner raumconcepte, Geiselbach – between Aschaffenburg and Hanau'),
           ('Auction', '5:30 pm'), ('Auctioneer', 'Dr. Stefan Söhngen'), ('Canvas', '1 × 2 metres, one of a kind, made for SHIFT Summit'),
           ('Proceeds', 'half to Smek – support in Kyiv')],
    auction_t='The charity auction at 5:30 pm',
    auction=['The 1 × 2 metre canvas was made especially for SHIFT Summit. Slavik created it together with his friend Volodymyr Vlastin, a scholar and scribe. '
             'Calligraphy and signs meet on it, among them the Farbaholix monogram, the Relationing logo and the sign of Smek.',
             'The auction is led by Dr. Stefan Söhngen. Half of the proceeds go to Smek, as support for Kyiv.'],
    calli_t='Live calligraphy: your word, drawn blind',
    calli_lead='During the summit Slavik writes calligraphy live – with words the guests bring themselves.',
    steps=[('Fill in a slip', 'Write a name, your company name, a word or a short phrase on a slip of paper.'),
           ('Into the glass bowl', 'Drop it into the large glass bowl shaped like a hemisphere.'),
           ('Drawn blind', 'Slavik draws the slips blind, one by one, and turns each into a calligraphic composition.'),
           ('Twelve gifts', 'The twelve calligraphy pieces go straight into frames – and Slavik gives them to twelve lucky guests before the auction.')],
    thanks_t='Thank you, Dr. Stefan Söhngen',
    thanks=['Dr. Stefan Söhngen, managing director of Relationing GmbH in Frankfurt, invited Farbaholix to SHIFT Summit – and he leads today’s auction.',
            'He has supported us for years, purely out of respect for our work. Respect right back – and heartfelt thanks.'],
    thanks_link='relationing.de',
    about_t='About SHIFT Summit',
    about='SHIFT Summit is an exclusive offsite event on developing existing real estate: keynotes, masterclasses and matchmaking for developers, owners, investors, architects and planners. '
          'It runs from 10 am to 6 pm; attendance is only possible through an official summit partner.',
    about_link='shiftsummit.de',
    photos_t='The canvas',
    caps={'shift-leinwand-detail': 'Detail of the canvas for the charity auction', 'shift-zeichen': 'Signs on the canvas: Farbaholix monogram, Relationing logo, sign of Smek'},
    report='After the summit this page becomes the report – with photos, the twelve calligraphy pieces and the result of the auction.',
    crumb='SHIFT Summit 2026',
    meta=('SHIFT Summit 2026: live calligraphy & charity auction | Farbaholix',
          'Farbaholix at SHIFT Summit 2026 in Geiselbach: live calligraphy and, at 5:30 pm, the charity auction of a canvas – half of the proceeds go to Smek, Kyiv.',
          'SHIFT Summit'),
 ),
 'uk': dict(
    kicker="Сьогодні · SHIFT Summit 2026",
    h1="Farbaholix на SHIFT Summit: каліграфія наживо і благодійний аукціон",
    lead="Сьогодні, 22 жовтня 2026 року, Farbaholix на SHIFT Summit у Goldbach Kirchner в Ґайзельбаху. "
         "О 17:30 на аукціон виставлять полотно, створене спеціально для цього дня, – половина виручки піде Smek на підтримку в Києві.",
    facts=[("Дата", "четвер, 22 жовтня 2026"), ("Місце", "Goldbach Kirchner raumconcepte, Ґайзельбах – між Ашаффенбургом і Ганау"),
           ("Аукціон", "17:30"), ("Аукціоніст", "д-р Штефан Зьонген (Dr. Stefan Söhngen)"), ("Полотно", "1 × 2 метри, унікат для SHIFT Summit"),
           ("Виручка", "половина – Smek, підтримка в Києві")],
    auction_t="Благодійний аукціон о 17:30",
    auction=["Полотно 1 × 2 метри створене спеціально для SHIFT Summit. Славік зробив його разом зі своїм другом Володимиром Властіним – науковцем і писарем. "
             "На ньому зустрічаються каліграфія і знаки, серед них монограма Farbaholix, логотип Relationing і знак Smek.",
             "Аукціон веде д-р Штефан Зьонген. Половина виручки піде Smek – на підтримку Києва."],
    calli_t="Каліграфія наживо: твоє слово, витягнуте наосліп",
    calli_lead="Під час саміту Славік пише каліграфію наживо – словами, які приносять самі гості.",
    steps=[("Заповни папірець", "Напиши ім'я, назву своєї компанії, слово або коротку фразу."),
           ("У скляну чашу", "Поклади папірець у велику скляну чашу у формі півсфери."),
           ("Наосліп", "Славік наосліп витягує папірці один за одним і пише з кожного каліграфічну композицію."),
           ("Дванадцять подарунків", "Дванадцять каліграфій одразу йдуть у рамки – і Славік дарує їх дванадцятьом щасливчикам ще до аукціону.")],
    thanks_t="Дякуємо, д-ре Штефане Зьонген",
    thanks=["Д-р Штефан Зьонген, керівник Relationing GmbH у Франкфурті, запросив Farbaholix на SHIFT Summit – і сьогодні веде аукціон.",
            "Він роками підтримує нас – виключно з поваги до нашої роботи. За це – повага у відповідь і щире дякую."],
    thanks_link="relationing.de",
    about_t="Про SHIFT Summit",
    about="SHIFT Summit – закрита офсайт-подія про розвиток наявної нерухомості: доповіді, майстер-класи й нетворкінг для девелоперів, власників, інвесторів, архітекторів і проєктувальників. "
          "Триває з 10:00 до 18:00; потрапити можна лише через офіційного партнера саміту.",
    about_link="shiftsummit.de",
    photos_t="Полотно",
    caps={'shift-leinwand-detail': "Фрагмент полотна для благодійного аукціону", 'shift-zeichen': "Знаки на полотні: монограма Farbaholix, логотип Relationing, знак Smek"},
    report="Після саміту тут з'явиться звіт – із фото, дванадцятьма каліграфіями і результатом аукціону.",
    crumb="SHIFT Summit 2026",
    meta=("SHIFT Summit 2026: каліграфія наживо і благодійний аукціон | Farbaholix",
          "Farbaholix на SHIFT Summit 2026 у Ґайзельбаху: каліграфія наживо і о 17:30 благодійний аукціон полотна – половина виручки піде Smek, Київ.",
          "SHIFT Summit"),
 ),
}
