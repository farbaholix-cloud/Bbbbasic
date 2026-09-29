# Project reports (case studies). Body HTML is trusted, written here. Facts: hessenschau.de 27.11.2024, sankt-georgen.de 14.04.2026 / 13.04.2026.
HR = 'https://www.hessenschau.de/sport/fussball/regionalliga/fsv-frankfurt-kuenstler-verschoenert-stadion-am-bornheimer-hang-v1,fsv-grafitti-100.html'
SG_NEWS = 'https://www.sankt-georgen.de/button-menue/mediathek/nachrichten-aus-sankt-georgen/detail/kunstprojekt-an-der-mauer-1100/'
SG_SEM = 'https://www.sankt-georgen.de/button-menue/mediathek/nachrichten-aus-sankt-georgen/detail/eroeffnung-des-sommersemesters-2026-1099/'

CAP = {  # image key -> captions de / en / uk
 'fsv-stadion-arena': ("Fassade am Bornheimer Hang mit „FSV Frankfurt 1899“ und Wappen", "Facade at Bornheimer Hang with “FSV Frankfurt 1899” and the crest", "Фасад на Борнгаймер Ганг із написом «FSV Frankfurt 1899» і гербом"),
 'fsv-panorama': ("Panorama: Schriftzug, Wappen und Fanshop-Anhänger", "Panorama: lettering, crest and fan-shop trailers", "Панорама: напис, герб і причепи фан-шопу"),
 'fsv-wappen-flammen': ("Vereinswappen in blauen Flammen im Innenbereich", "Club crest in blue flames indoors", "Герб клубу в синьому полум’ї всередині"),
 'fsv-respekt': ("Gang mit „Respekt · Mut · Leidenschaft“", "Corridor with “Respekt · Mut · Leidenschaft”", "Коридор із написом «Respekt · Mut · Leidenschaft»"),
 'fsv-immer-weiter': ("„Immer weiter“ – Wandschrift mit Kickertisch", "“Immer weiter” lettering with a table-football table", "Напис «Immer weiter» і настільний футбол"),
 'fsv-gang': ("Gang mit #WIRsindFSV", "Corridor with #WIRsindFSV", "Коридор із #WIRsindFSV"),
 'fsv-vereinsheim': ("Innenraum mit Wappen, 1899 und Porträts", "Interior with crest, 1899 and portraits", "Інтер’єр із гербом, 1899 і портретами"),
 'fsv-rampe-fussball': ("Rampe als Rasen mit Fußball – Signatur Farbaholix & Caparol", "Ramp painted as a pitch with a football – signed Farbaholix & Caparol", "Пандус як газон із м’ячем – підпис Farbaholix і Caparol"),
 'fsv-arena-ecke': ("Stadionecke mit #WIRsindFSV – damals noch PSD Bank Arena, seit 2026 BBBank Arena", "Stadium corner with #WIRsindFSV – then still PSD Bank Arena, BBBank Arena since 2026", "Кут стадіону з #WIRsindFSV – тоді ще PSD Bank Arena, з 2026 року BBBank Arena"),
 'fsv-caparol': ("Caparol-Logo mit der Sprühdose", "Caparol logo with the spray can", "Логотип Caparol балончиком"),
 'sg-strelitzien': ("Strelitzien an der Campusmauer", "Birds of paradise on the campus wall", "Стрелітції на стіні кампусу"),
 'sg-mauer-fahnen': ("Mauer mit Jubiläumsfahnen „heute weiter denken“", "Wall with anniversary flags “heute weiter denken”", "Стіна з ювілейними прапорами «heute weiter denken»"),
 'sg-strelitzie-nah': ("Strelitzie im Detail", "Bird of paradise in detail", "Стрелітція крупним планом"),
 'sg-blueten': ("Weiße Blüten mit Hummel", "White blossoms with a bumblebee", "Білі квіти з джмелем"),
 'sg-monstera': ("Monstera-Blätter", "Monstera leaves", "Листя монстери"),
 'sg-monstera-mauer': ("Monstera über die ganze Mauerhöhe", "Monstera across the full height of the wall", "Монстера на всю висоту стіни"),
 'sg-lotus': ("Lotusblüte", "Lotus flower", "Квітка лотоса"),
 'sg-pink': ("Pinke Blätter", "Pink leaves", "Рожеве листя"),
 'sg-bananenblatt': ("Bananenblätter mit violetter Blüte", "Banana leaves with a violet flower", "Бананове листя з фіолетовою квіткою"),
 'sg-palme': ("Palmblätter", "Palm fronds", "Пальмове листя"),
 'sg-einblatt': ("Einblatt mit Signatur am Mauerende", "Peace lily with signature at the end of the wall", "Спатифілум із підписом у кінці стіни"),
 'sg-mensa': ("„Mensa im Park“ – das Schild wurde ins Mural integriert", "“Mensa im Park” – the sign is part of the mural", "«Mensa im Park» – табличку вписано в мурал"),
 'sg-100-jahre': ("„100 Jahre Sankt Georgen – heute weiter denken“", "“100 Jahre Sankt Georgen – heute weiter denken”", "«100 Jahre Sankt Georgen – heute weiter denken»"),
 'georgen-strassenbahn': ("Die Straßenbahn fährt am Mural vorbei", "The tram passes the mural", "Трамвай проїжджає повз мурал"),
 'sg-abend': ("Die Mauer im Abendlicht", "The wall in the evening light", "Стіна у вечірньому світлі"),
 'sg-strasse': ("Straßenansicht", "Street view", "Вигляд із вулиці"),
 'sg-grundierung': ("Grundierung mit dem Farbspritzgerät", "Priming with a paint sprayer", "Ґрунтування фарборозпилювачем"),
 'sg-slavik-monstera': ("Slavik sprüht ein Monstera-Blatt", "Slavik spraying a monstera leaf", "Славік малює лист монстери"),
 'sg-slavik-bluete': ("Slavik an einer weißen Blüte", "Slavik working on a white blossom", "Славік працює над білою квіткою"),
 'georgen-kuenstler': ("Slavik bei der Arbeit", "Slavik at work", "Славік за роботою"),
 'sg-farben': ("Montana-Sprühdosen und Skizzen", "Montana spray cans and sketches", "Балончики Montana й ескізи"),
 'sg-partner': ("Partner: Montana Colors und Caparol", "Partners: Montana Colors and Caparol", "Партнери: Montana Colors і Caparol"),
 'sg-caparol-malen': ("Der Caparol-Elefant entsteht", "The Caparol elephant taking shape", "Створення слона Caparol"),
 'georgen-presse': ("Frankfurter Presse: „Aus seiner Sprühdose kommen Blumen“", "Frankfurt press: “Aus seiner Sprühdose kommen Blumen”", "Франкфуртська преса: «Aus seiner Sprühdose kommen Blumen»"),
}

FSV_GAL = ['fsv-stadion-arena', 'fsv-panorama', 'fsv-wappen-flammen', 'fsv-respekt', 'fsv-immer-weiter', 'fsv-gang', 'fsv-vereinsheim', 'fsv-rampe-fussball', 'fsv-arena-ecke', 'fsv-caparol']
SG_GAL = ['sg-strelitzien', 'sg-mauer-fahnen', 'sg-strelitzie-nah', 'sg-blueten', 'sg-monstera', 'sg-monstera-mauer', 'sg-lotus', 'sg-pink', 'sg-bananenblatt', 'sg-palme', 'sg-einblatt',
          'sg-mensa', 'sg-100-jahre', 'georgen-strassenbahn', 'sg-abend', 'sg-strasse', 'sg-grundierung', 'sg-slavik-monstera', 'sg-slavik-bluete', 'georgen-kuenstler', 'sg-farben', 'sg-partner', 'sg-caparol-malen', 'georgen-presse']

CASE_PAGES = {
'fsv': dict(case='fsv', hero='fsv-stadion-arena', wide='fsv-panorama', gallery=FSV_GAL, date='2024-11-27', related='georgen', t={
 'de': dict(
  meta=("FSV Frankfurt Stadion: Graffiti am Bornheimer Hang | Farbaholix",
        "FSV Frankfurt Stadion am Bornheimer Hang: Graffiti-Künstler Slavik (Farbaholix) gestaltete Wappen (6 × 4 m), Fassade, Fanshop und Innenräume. Projektbericht mit Fotos und Presse."),
  focus="FSV Frankfurt Stadion", kicker="Projektbericht", h1="FSV Frankfurt: Wie das Stadion am Bornheimer Hang seine Farben bekam",
  lead="Anderthalb Jahre lang hat der Graffiti-Künstler Viacheslav „Slavik“ Balabaiev (Farbaholix) das FSV Frankfurt Stadion am Bornheimer Hang gestaltet: die Fassade mit Vereinsschriftzug und einem rund sechs mal vier Meter großen Wappen, den Fanshop, Gänge und Innenräume – passend zum 125-jährigen Jubiläum des Vereins. Der Hessische Rundfunk berichtete im November 2024.",
  facts=[("Ort", "Stadion am Bornheimer Hang – seit 2026 BBBank Arena (zuvor PSD Bank Arena), Frankfurt-Bornheim"), ("Auftraggeber", "FSV Frankfurt 1899"), ("Anlass", "125 Jahre FSV Frankfurt"), ("Dauer", "ca. 1,5 Jahre"),
         ("Umfang", "Fassade, Wappen ca. 6 × 4 m, Fanshop, Gänge, Innenräume, Außenrampe"), ("Material", "Fassadenfarben von Caparol, Sprühlack")],
  sections=[
   ("Die Ausgangslage", ["<p>Das Stadion am Bornheimer Hang ist seit 1931 die Heimat des FSV Frankfurt und mit gut 12.500 Plätzen die zweitgrößte Arena der Stadt. Während der Arbeiten hieß es PSD Bank Arena, seit 2026 trägt es den Namen BBBank Arena. Die dunkle Lamellenfassade war funktional – aber sie erzählte nichts vom Verein. Zum 125-jährigen Jubiläum wollte die Geschäftsführung um Robert Lempka das ändern.</p>"]),
   ("Was am FSV Frankfurt Stadion gestaltet wurde", ["<ul><li><strong>Fassade:</strong> der Schriftzug „FSV Frankfurt 1899“ in Blau-Weiß und das Vereinswappen, rund sechs mal vier Meter groß – gesprüht auf die senkrechten Lamellen, sodass Schrift und Wappen aus der Entfernung plastisch wirken.</li>"
                             "<li><strong>Fanshop:</strong> die mobilen Verkaufsanhänger in Vereinsdesign mit „125 Jahre Fußballsportverein“.</li>"
                             "<li><strong>Innenräume und Gänge:</strong> das Wappen in blauen Flammen, die Leitsätze „Respekt · Mut · Leidenschaft“ und „Immer weiter“, #WIRsindFSV und Porträts der Vereinsgeschichte.</li>"
                             "<li><strong>Außenrampe:</strong> als Rasen mit Fußball gemalt – signiert von Farbaholix und Caparol.</li></ul>"]),
   ("Wie gearbeitet wurde", ["<p>Große Flächen entstanden mit Fassadenfarbe, Details, Schatten und Glanzlichter mit der Sprühdose. Die Arbeit verteilte sich über anderthalb Jahre in mehreren Etappen. Materialpartner war Caparol – sein Logo steht neben der Farbaholix-Signatur an der Außenrampe.</p>"]),
   ("Die Reaktionen", ["<p>„Ich finde es richtig geil“, sagte FSV-Spieler Elias Breir dem Hessischen Rundfunk – im Team kam gleich der Wunsch nach weiteren Motiven in der Mixed Zone auf. Und: „Wenn man weiß, wie es vorher ausgesehen hat, und jetzt das hier sieht, ist das eine gelungene Arbeit.“ Slavik selbst beschreibt seine Arbeit als „die älteste Kunstform in der modernsten Ausprägung“. Die hessenschau zeigte das Wappen im Fernsehbeitrag „Große Kunst am Bornheimer Hang“, und die Stadt Frankfurt nannte die Gestaltung der Südtribüne des FSV-Stadions 2025 als eine der Arbeiten, mit denen Slavik zu einem wichtigen Teil der urbanen Kunstszene wurde.</p>"]),
  ],
  quote=("Ich lebe jetzt hier und möchte diesen Ort schöner machen.", "Slavik im Gespräch mit dem Hessischen Rundfunk, November 2024"),
  review=("Slavik, Gründer von Farbaholix, hat in dem Zeitraum von anderthalb Jahren, die künstlerische Gestaltung unseres Fußballstadions durchgeführt. Kreativität, Ausführung, Flexibilität und Zuverlässigkeit waren auf allerhöchstem Niveau. Ich kann Slavik uneingeschränkt und mit Nachdruck weiterempfehlen.", "Robert Lempka, Geschäftsführer FSV Frankfurt"),
  gallery_t="Fotos aus dem Stadion",
  sources=[("hessenschau.de: „Ukrainischer Künstler verschönert Stadion des FSV Frankfurt“ (27.11.2024)", HR), ("hessenschau (Video, 1:28): „Große Kunst am Bornheimer Hang“ (27.11.2024)", "https://www.hessenschau.de/panorama/riesiges-fsv-wappen-grosse-kunst-am-bornheimer-hang,video-204422.html"), ("sportschau.de (hr): „FSV Frankfurt: Künstler verschönert Stadion am Bornheimer Hang“ (27.11.2024)", "https://www.sportschau.de/regional/hr/hr-fsv-frankfurt-kuenstler-verschoenert-stadion-am-bornheimer-hang-100.html"), ("Stadt Frankfurt am Main: „Graffiti für Frieden und Freiheit“ – u. a. zur Südtribüne des FSV-Stadions (02.10.2025)", "https://www.frankfurt-live.com/graffiti-fuer-frieden-und-freiheit")],
  faq=[("Wie groß ist das FSV-Wappen an der Fassade?", "Rund sechs mal vier Meter. Es wurde direkt auf die Lamellenfassade gesprüht."),
       ("Wie lange hat die Stadiongestaltung gedauert?", "Etwa anderthalb Jahre, in mehreren Etappen."),
       ("Gestaltet Farbaholix auch andere Sportstätten?", "Ja: Stadien, Sporthallen, Fitnessstudios und Vereinsheime – von der Fassade bis zur Kabine. Einen ersten Richtwert gibt der Preisrechner.")],
 ),
 'en': dict(
  meta=("FSV Frankfurt Stadium Graffiti at Bornheimer Hang | Farbaholix",
        "FSV Frankfurt stadium at Bornheimer Hang: graffiti artist Slavik (Farbaholix) designed the 6 × 4 m crest, facade, fan shop and interiors. Case study with photos and press."),
  focus="FSV Frankfurt stadium", kicker="Case study", h1="FSV Frankfurt: how the stadium at Bornheimer Hang got its colours",
  lead="For a year and a half, graffiti artist Viacheslav “Slavik” Balabaiev (Farbaholix) designed the FSV Frankfurt stadium at Bornheimer Hang: the facade with the club lettering and a crest of about six by four metres, the fan shop, corridors and interiors – in time for the club’s 125th anniversary. Hessischer Rundfunk reported on it in November 2024.",
  facts=[("Location", "Stadion am Bornheimer Hang – BBBank Arena since 2026 (formerly PSD Bank Arena), Frankfurt-Bornheim"), ("Client", "FSV Frankfurt 1899"), ("Occasion", "125 years of FSV Frankfurt"), ("Duration", "approx. 1.5 years"),
         ("Scope", "Facade, crest approx. 6 × 4 m, fan shop, corridors, interiors, outdoor ramp"), ("Materials", "Caparol facade paints, spray paint")],
  sections=[
   ("The starting point", ["<p>The stadium at Bornheimer Hang has been FSV Frankfurt’s home since 1931 and, with about 12,500 seats, is the second-largest arena in the city. During the project it was called PSD Bank Arena; since 2026 it has been the BBBank Arena. Its dark slatted facade was functional – but it said nothing about the club. For the 125th anniversary, managing director Robert Lempka wanted to change that.</p>"]),
   ("What was designed at the FSV Frankfurt stadium", ["<ul><li><strong>Facade:</strong> the lettering “FSV Frankfurt 1899” in blue and white and the club crest, about six by four metres – sprayed onto the vertical slats so that lettering and crest look three-dimensional from a distance.</li>"
                          "<li><strong>Fan shop:</strong> the mobile sales trailers in club design with “125 Jahre Fußballsportverein”.</li>"
                          "<li><strong>Interiors and corridors:</strong> the crest in blue flames, the mottos “Respekt · Mut · Leidenschaft” and “Immer weiter”, #WIRsindFSV and portraits from the club’s history.</li>"
                          "<li><strong>Outdoor ramp:</strong> painted as a pitch with a football – signed by Farbaholix and Caparol.</li></ul>"]),
   ("How it was done", ["<p>Large areas were painted with facade paint; details, shadows and highlights with spray cans. The work was spread over a year and a half in several stages. Caparol was the materials partner – its logo sits next to the Farbaholix signature on the outdoor ramp.</p>"]),
   ("The reactions", ["<p>“Ich finde es richtig geil” (“I think it’s really awesome”), FSV player Elias Breir told Hessischer Rundfunk – and the team immediately asked for more motifs in the mixed zone. He added: if you know what it looked like before and see this now, “it’s a successful piece of work”. Slavik describes his work as “the oldest art form in its most modern expression”. hessenschau featured the crest in its TV report “Große Kunst am Bornheimer Hang”, and in 2025 the City of Frankfurt named the design of the FSV stadium’s south stand among the works that made Slavik an important part of the urban art scene.</p>"]),
  ],
  quote=("I live here now and want to make this place more beautiful.", "Slavik to Hessischer Rundfunk, November 2024"),
  review=("Slavik, founder of Farbaholix, carried out the artistic design of our football stadium over a period of one and a half years. Creativity, execution, flexibility and reliability were at the very highest level. I recommend Slavik without reservation and emphatically.", "Robert Lempka, managing director of FSV Frankfurt (translated)"),
  gallery_t="Photos from the stadium",
  sources=[("hessenschau.de: “Ukrainian artist beautifies FSV Frankfurt’s stadium” (27 Nov 2024, in German)", HR), ("hessenschau (video, 1:28): “Große Kunst am Bornheimer Hang” (27 Nov 2024)", "https://www.hessenschau.de/panorama/riesiges-fsv-wappen-grosse-kunst-am-bornheimer-hang,video-204422.html"), ("sportschau.de (hr): “FSV Frankfurt: artist beautifies the stadium at Bornheimer Hang” (27 Nov 2024, in German)", "https://www.sportschau.de/regional/hr/hr-fsv-frankfurt-kuenstler-verschoenert-stadion-am-bornheimer-hang-100.html"), ("City of Frankfurt: “Graffiti für Frieden und Freiheit” – incl. the FSV stadium’s south stand (2 Oct 2025, in German)", "https://www.frankfurt-live.com/graffiti-fuer-frieden-und-freiheit")],
  faq=[("How big is the FSV crest on the facade?", "About six by four metres. It was sprayed directly onto the slatted facade."),
       ("How long did the stadium design take?", "About a year and a half, in several stages."),
       ("Does Farbaholix design other sports venues?", "Yes: stadiums, sports halls, gyms and clubhouses – from the facade to the changing room. The price calculator gives you a first estimate.")],
 ),
 'uk': dict(
  meta=("Стадіон FSV Frankfurt: графіті на Борнгаймер Ганг | Farbaholix",
        "Кейс: як графіті-художник Славік (Farbaholix) оформив стадіон FSV Frankfurt – герб 6 × 4 м, фасад, фан-шоп, інтер’єри. З фото й публікаціями в пресі."),
  focus="FSV Frankfurt", kicker="Кейс", h1="FSV Frankfurt: як стадіон на Борнгаймер Ганг отримав свої кольори",
  lead="Півтора року графіті-художник В’ячеслав «Славік» Балабаєв (Farbaholix) оформлював стадіон FSV Frankfurt 1899: фасад із клубним написом і гербом приблизно шість на чотири метри, фан-шоп, коридори й інтер’єри – до 125-річчя клубу. Гессенське радіо (hr) розповіло про це в листопаді 2024 року.",
  facts=[("Місце", "Stadion am Bornheimer Hang – з 2026 року BBBank Arena (раніше PSD Bank Arena), Франкфурт-Борнгайм"), ("Замовник", "FSV Frankfurt 1899"), ("Привід", "125 років FSV Frankfurt"), ("Тривалість", "близько 1,5 року"),
         ("Обсяг", "Фасад, герб ≈ 6 × 4 м, фан-шоп, коридори, інтер’єри, пандус"), ("Матеріали", "Фасадні фарби Caparol, аерозольні фарби")],
  sections=[
   ("Вихідна точка", ["<p>Стадіон на Борнгаймер Ганг – дім FSV Frankfurt із 1931 року й, маючи близько 12 500 місць, друга за величиною арена міста. Під час робіт він називався PSD Bank Arena, з 2026 року – BBBank Arena. Темний ламельний фасад був функціональним, але нічого не розповідав про клуб. До 125-річчя керівництво на чолі з Робертом Лемпкою вирішило це змінити.</p>"]),
   ("Що оформили на стадіоні FSV Frankfurt", ["<ul><li><strong>Фасад:</strong> напис «FSV Frankfurt 1899» у синьо-білих кольорах і клубний герб приблизно шість на чотири метри – намальовані на вертикальних ламелях, тож здалеку напис і герб виглядають об’ємними.</li>"
                    "<li><strong>Фан-шоп:</strong> мобільні торгові причепи в клубному дизайні з написом «125 Jahre Fußballsportverein».</li>"
                    "<li><strong>Інтер’єри й коридори:</strong> герб у синьому полум’ї, гасла «Respekt · Mut · Leidenschaft» і «Immer weiter», #WIRsindFSV та портрети з історії клубу.</li>"
                    "<li><strong>Зовнішній пандус:</strong> намальований як газон із м’ячем – із підписами Farbaholix і Caparol.</li></ul>"]),
   ("Як працювали", ["<p>Великі площі фарбували фасадною фарбою, деталі, тіні й відблиски – балончиком. Робота тривала півтора року в кілька етапів. Партнер із матеріалів – Caparol: його логотип стоїть поруч із підписом Farbaholix на зовнішньому пандусі.</p>"]),
   ("Реакція", ["<p>«Ich finde es richtig geil» («Мені дуже подобається»), – сказав гравець FSV Еліас Брайр в ефірі hr, і команда одразу попросила нових мотивів у мікст-зоні. І додав: якщо знаєш, як тут було раніше, і бачиш це тепер, – «це вдала робота». Сам Славік називає свою роботу «найдавнішим видом мистецтва в найсучаснішому втіленні». hessenschau показала герб у телесюжеті «Große Kunst am Bornheimer Hang», а у 2025 році місто Франкфурт назвало оформлення південної трибуни стадіону FSV серед робіт, що зробили Славіка важливою частиною міської арт-сцени.</p>"]),
  ],
  quote=("Тепер я живу тут і хочу зробити це місце гарнішим.", "Славік в інтерв’ю Гессенському радіо, листопад 2024"),
  review=("Славік, засновник Farbaholix, упродовж півтора року виконував художнє оформлення нашого футбольного стадіону. Креативність, виконання, гнучкість і надійність були на найвищому рівні. Я беззастережно й наполегливо рекомендую Славіка.", "Роберт Лемпка, генеральний директор FSV Frankfurt (переклад)"),
  gallery_t="Фото зі стадіону",
  sources=[("hessenschau.de: «Український художник прикрашає стадіон FSV Frankfurt» (27.11.2024, німецькою)", HR), ("hessenschau (відео, 1:28): «Große Kunst am Bornheimer Hang» (27.11.2024)", "https://www.hessenschau.de/panorama/riesiges-fsv-wappen-grosse-kunst-am-bornheimer-hang,video-204422.html"), ("sportschau.de (hr): «FSV Frankfurt: художник прикрашає стадіон на Борнгаймер Ганг» (27.11.2024, німецькою)", "https://www.sportschau.de/regional/hr/hr-fsv-frankfurt-kuenstler-verschoenert-stadion-am-bornheimer-hang-100.html"), ("Місто Франкфурт: «Graffiti für Frieden und Freiheit» – зокрема про південну трибуну стадіону FSV (02.10.2025, німецькою)", "https://www.frankfurt-live.com/graffiti-fuer-frieden-und-freiheit")],
  faq=[("Якого розміру герб FSV на фасаді?", "Приблизно шість на чотири метри. Його намалювали безпосередньо на ламельному фасаді."),
       ("Скільки тривало оформлення стадіону?", "Близько півтора року, у кілька етапів."),
       ("Чи оформлює Farbaholix інші спортивні об’єкти?", "Так: стадіони, спортзали, фітнес-клуби й клубні приміщення – від фасаду до роздягальні. Перший орієнтир дасть калькулятор ціни.")],
 ),
}),
'georgen': dict(case='georgen', hero='sg-strelitzien', wide=None, gallery=SG_GAL, date='2026-04-14', related='fsv', t={
 'de': dict(
  meta=("Sankt Georgen Mural: 100 Jahre, eine Mauer voller Blumen | Farbaholix",
        "Das Sankt Georgen Mural in Frankfurt: botanisches Graffiti an der Campusmauer zum 100-jährigen Jubiläum der Hochschule – Motive, Bedeutung, Entstehung. Mit über 20 Fotos."),
  focus="Sankt Georgen Mural", kicker="Projektbericht", h1="100 Jahre Sankt Georgen: eine Mauer voller Blumen",
  lead="Das Sankt Georgen Mural ist fertig: Ab Oktober 2025 verwandelte der Graffiti-Künstler Viacheslav „Slavik“ Balabaiev (Farbaholix) die Campusmauer der Philosophisch-Theologischen Hochschule Sankt Georgen in Frankfurt-Sachsenhausen in eine botanische Galerie – zum 100-jährigen Jubiläum der Hochschule 2026 unter dem Motto „heute weiter denken“.",
  facts=[("Ort", "Campusmauer der Hochschule Sankt Georgen, Frankfurt-Sachsenhausen"), ("Auftraggeber", "Philosophisch-Theologische Hochschule Sankt Georgen"), ("Anlass", "100 Jahre Sankt Georgen (gegründet 1926)"),
         ("Zeitraum", "Oktober 2025 – 2026, abgeschlossen"), ("Motive", "Strelitzien, Monstera, Lotus, Palm- und Bananenblätter, Blüten mit Hummel"), ("Material", "Montana Colors, Caparol")],
  sections=[
   ("Vorher: eine graue Mauer an der Straße", ["<p>Die lange Mauer um den Campus-Park war grau, fleckig und stellenweise beschmiert – eine Grenze, an der täglich Autos, Radfahrer und die Straßenbahn vorbeifahren. Zum Jubiläum sollte sie zeigen, wofür die Hochschule steht: Offenheit und Entwicklung.</p>"]),
   ("Was auf der Mauer blüht", ["<p>Strelitzien in Orange und Violett, meterhohe Monstera-Blätter, Lotus, pinke Blätter, Palm- und Bananenblätter, weiße Blüten mit einer Hummel – botanisch genau und über die gesamte Länge der Mauer. Vorhandene Schilder wie „Mensa im Park“ und der Jubiläumsschriftzug „100 Jahre Sankt Georgen – heute weiter denken“ wurden in die Komposition eingebunden.</p>"]),
   ("Was die Pflanzen bedeuten", ["<p>Die Hochschule schreibt: „Die dargestellten pflanzlichen Motive verweisen auf Prozesse des Wachsens, der Differenzierung und der fortlaufenden Veränderung.“ Das Mural zeige Sankt Georgen als offenen, dynamischen Ort, an dem Wissen ständig weiterentwickelt wird – und schaffe einen neuen Blickpunkt auf dem Campus.</p>"]),
   ("Wie das Sankt Georgen Mural entsteht", ["<ol><li><strong>Vorbereiten:</strong> Die Mauer wird gereinigt und mit dem Farbspritzgerät hell grundiert (Caparol).</li>"
                              "<li><strong>Entwerfen:</strong> Die Motive werden skizziert – auch mit Hilfe von KI-Werkzeugen – und abschnittsweise übertragen.</li>"
                              "<li><strong>Sprühen:</strong> Blätter und Blüten entstehen mit Sprühdosen von Montana Colors, Abschnitt für Abschnitt.</li></ol>"]),
   ("Ein Werk, das gewachsen ist", ["<p>Bei der Eröffnung des Sommersemesters am 13. April 2026 sprach Slavik mit P. Niccolo Steiner SJ, moderiert von Rektor Prof. Wolfgang Beck. Damals beschrieb er seine Arbeit – ähnlich den dargestellten floralen Motiven – als fortwährenden Wachstumsprozess, in den neue künstlerische Möglichkeiten wie KI-Technologien einflossen. Inzwischen ist das Mural vollendet: eine durchgehende Blumenwand, an der Passanten stehen bleiben, fotografieren und ins Gespräch kommen.</p>"]),
  ],
  quote=("Die dargestellten pflanzlichen Motive verweisen auf Prozesse des Wachsens, der Differenzierung und der fortlaufenden Veränderung.", "Hochschule Sankt Georgen, April 2026"),
  review=None,
  gallery_t="Fotos von der Mauer",
  sources=[("Hochschule Sankt Georgen: „Kunstprojekt an der Mauer“ (14.04.2026)", SG_NEWS), ("Hochschule Sankt Georgen: „Eröffnung des Sommersemesters 2026“", SG_SEM),
           ("Frankfurter Presse: „Aus seiner Sprühdose kommen Blumen“", None)],
  faq=[("Wo ist das Blumen-Mural von Sankt Georgen?", "An der Mauer des Campus der Hochschule Sankt Georgen in Frankfurt-Sachsenhausen, gut sichtbar von der Straße und aus der Straßenbahn."),
       ("Warum Pflanzen?", "Sie stehen laut Hochschule für Wachstum, Differenzierung und fortlaufende Veränderung – passend zum Jubiläumsmotto „heute weiter denken“."),
       ("Kann ich so eine Wand auch für mein Unternehmen bekommen?", "Ja. Florale Murals funktionieren an Mauern, Fassaden und in Innenräumen. Einen ersten Richtwert gibt der Preisrechner.")],
 ),
 'en': dict(
  meta=("Sankt Georgen Mural: 100 Years, a Wall Full of Flowers | Farbaholix",
        "The Sankt Georgen mural in Frankfurt: botanical graffiti on the campus wall for the school’s 100th anniversary – motifs, meaning, process. With 20+ photos."),
  focus="Sankt Georgen mural", kicker="Case study", h1="100 years of Sankt Georgen: a wall full of flowers",
  lead="The Sankt Georgen mural is finished: from October 2025, graffiti artist Viacheslav “Slavik” Balabaiev (Farbaholix) turned the campus wall of the Sankt Georgen Graduate School of Philosophy and Theology in Frankfurt-Sachsenhausen into a botanical gallery – for the school’s 100th anniversary in 2026 under the motto “heute weiter denken” (“thinking further today”).",
  facts=[("Location", "Campus wall of Sankt Georgen, Frankfurt-Sachsenhausen"), ("Client", "Sankt Georgen Graduate School of Philosophy and Theology"), ("Occasion", "100 years of Sankt Georgen (founded 1926)"),
         ("Period", "October 2025 – 2026, completed"), ("Motifs", "Birds of paradise, monstera, lotus, palm and banana leaves, blossoms with a bumblebee"), ("Materials", "Montana Colors, Caparol")],
  sections=[
   ("Before: a grey wall by the road", ["<p>The long wall around the campus park was grey, stained and partly tagged – a boundary passed every day by cars, cyclists and the tram. For the anniversary it was to show what the school stands for: openness and development.</p>"]),
   ("What blooms on the wall", ["<p>Birds of paradise in orange and violet, monstera leaves metres high, lotus, pink leaves, palm and banana fronds, white blossoms with a bumblebee – botanically accurate and along the entire length of the wall. Existing signs such as “Mensa im Park” and the anniversary lettering “100 Jahre Sankt Georgen – heute weiter denken” became part of the composition.</p>"]),
   ("What the plants mean", ["<p>According to the school, “the plant motifs refer to processes of growth, differentiation and continuous change.” The mural presents Sankt Georgen as an open, dynamic place where knowledge keeps developing – and creates a new point of attention on campus.</p>"]),
   ("How the Sankt Georgen mural is made", ["<ol><li><strong>Preparation:</strong> the wall is cleaned and primed white with a paint sprayer (Caparol).</li>"
                             "<li><strong>Design:</strong> the motifs are sketched – also with the help of AI tools – and transferred section by section.</li>"
                             "<li><strong>Spraying:</strong> leaves and blossoms are painted with Montana Colors spray cans, section by section.</li></ol>"]),
   ("A work that has grown", ["<p>At the opening of the summer semester on 13 April 2026, Slavik talked with Fr Niccolo Steiner SJ, moderated by rector Prof. Wolfgang Beck. At the time he described his work, like the floral motifs it shows, as a continuous process of growth that took in new artistic possibilities such as AI technologies. The mural has since been completed: a continuous wall of flowers where passers-by stop, take photos and start conversations.</p>"]),
  ],
  quote=("The plant motifs refer to processes of growth, differentiation and continuous change.", "Sankt Georgen Graduate School, April 2026 (translated)"),
  review=None,
  gallery_t="Photos of the wall",
  sources=[("Sankt Georgen: “Kunstprojekt an der Mauer” (14 Apr 2026, in German)", SG_NEWS), ("Sankt Georgen: “Eröffnung des Sommersemesters 2026” (in German)", SG_SEM),
           ("Frankfurt press: “Aus seiner Sprühdose kommen Blumen”", None)],
  faq=[("Where is the Sankt Georgen flower mural?", "On the campus wall of Sankt Georgen in Frankfurt-Sachsenhausen, clearly visible from the road and the tram."),
       ("Why plants?", "According to the school, they stand for growth, differentiation and continuous change – fitting the anniversary motto “thinking further today”."),
       ("Can I get a wall like this for my company?", "Yes. Floral murals work on walls, facades and indoors. The price calculator gives you a first estimate.")],
 ),
 'uk': dict(
  meta=("Мурал Sankt Georgen: 100 років, стіна, повна квітів | Farbaholix",
        "Кейс: ботанічний графіті-мурал на стіні кампусу Вищої школи Sankt Georgen у Франкфурті – мотиви, сенс, процес. Понад 20 фото."),
  focus="Sankt Georgen", kicker="Кейс", h1="100 років Sankt Georgen: стіна, повна квітів",
  lead="Мурал Sankt Georgen завершено: з жовтня 2025 року графіті-художник В’ячеслав «Славік» Балабаєв (Farbaholix) перетворював стіну кампусу Філософсько-теологічної вищої школи Sankt Georgen у Франкфурті-Заксенгаузені на ботанічну галерею – до 100-річчя школи у 2026 році під гаслом «heute weiter denken» («думати далі вже сьогодні»).",
  facts=[("Місце", "Стіна кампусу Sankt Georgen, Франкфурт-Заксенгаузен"), ("Замовник", "Філософсько-теологічна вища школа Sankt Georgen"), ("Привід", "100 років Sankt Georgen (засн. 1926)"),
         ("Період", "Жовтень 2025 – 2026, завершено"), ("Мотиви", "Стрелітції, монстера, лотос, пальмове й бананове листя, квіти з джмелем"), ("Матеріали", "Montana Colors, Caparol")],
  sections=[
   ("До: сіра стіна біля дороги", ["<p>Довга стіна навколо парку кампусу була сірою, у плямах і подекуди розмальованою тегами – межа, повз яку щодня їдуть авто, велосипедисти й трамвай. До ювілею вона мала показати, що цінує школа: відкритість і розвиток.</p>"]),
   ("Що квітне на стіні", ["<p>Стрелітції в оранжевих і фіолетових тонах, багатометрове листя монстери, лотос, рожеве листя, пальмове й бананове листя, білі квіти з джмелем – ботанічно точно й уздовж усієї стіни. Наявні таблички, як-от «Mensa im Park», і ювілейний напис «100 Jahre Sankt Georgen – heute weiter denken» стали частиною композиції.</p>"]),
   ("Що означають рослини", ["<p>Як пише школа, «рослинні мотиви вказують на процеси зростання, диференціації й безперервних змін». Мурал показує Sankt Georgen як відкрите, динамічне місце, де знання постійно розвиваються, – і створює нову точку тяжіння в кампусі.</p>"]),
   ("Як створюється мурал Sankt Georgen", ["<ol><li><strong>Підготовка:</strong> стіну очищають і світло ґрунтують фарборозпилювачем (Caparol).</li>"
                             "<li><strong>Ескіз:</strong> мотиви малюють – зокрема за допомогою інструментів ШІ – і переносять ділянками.</li>"
                             "<li><strong>Розпис:</strong> листя й квіти малюють балончиками Montana Colors, ділянка за ділянкою.</li></ol>"]),
   ("Робота, що виросла", ["<p>На відкритті літнього семестру 13 квітня 2026 року Славік говорив із о. Нікколо Штайнером SJ, модерував ректор проф. Вольфганг Бек. Тоді він описував свою роботу – як і квіткові мотиви на стіні – як безперервне зростання, що вбирало нові художні можливості, зокрема технології ШІ. Відтоді мурал завершено: суцільна квіткова стіна, біля якої перехожі зупиняються, фотографують і заводять розмови.</p>"]),
  ],
  quote=("Рослинні мотиви вказують на процеси зростання, диференціації й безперервних змін.", "Вища школа Sankt Georgen, квітень 2026 (переклад)"),
  review=None,
  gallery_t="Фото стіни",
  sources=[("Sankt Georgen: «Kunstprojekt an der Mauer» (14.04.2026, німецькою)", SG_NEWS), ("Sankt Georgen: «Eröffnung des Sommersemesters 2026» (німецькою)", SG_SEM),
           ("Франкфуртська преса: «Aus seiner Sprühdose kommen Blumen»", None)],
  faq=[("Де знаходиться квітковий мурал Sankt Georgen?", "На стіні кампусу Sankt Georgen у Франкфурті-Заксенгаузені, його добре видно з дороги й трамвая."),
       ("Чому саме рослини?", "За словами школи, вони символізують зростання, диференціацію й безперервні зміни – у дусі ювілейного гасла «думати далі вже сьогодні»."),
       ("Чи можна замовити таку стіну для компанії?", "Так. Квіткові мурали працюють на огорожах, фасадах і в інтер’єрах. Перший орієнтир дасть калькулятор ціни.")],
 ),
}),
}
UI = {
 'de': dict(facts_t="Projekt auf einen Blick", review_t="Stimme des Auftraggebers", sources_t="Presse und Quellen", faq_t="Häufige Fragen", more="Projektbericht lesen", related="Weiteres Projekt",
            cta_t="Ihre Wand als nächstes Projekt?", cta_calc="Preis berechnen", cta_contact="Projekt anfragen", all_works="Alle Arbeiten ansehen", back="Alle Projekte", gallery_hint="Zum Vergrößern antippen"),
 'en': dict(facts_t="Project at a glance", review_t="Client’s voice", sources_t="Press and sources", faq_t="Frequently asked questions", more="Read the case study", related="Another project",
            cta_t="Your wall as the next project?", cta_calc="Calculate a price", cta_contact="Request a project", all_works="See all works", back="All projects", gallery_hint="Tap to enlarge"),
 'uk': dict(facts_t="Проєкт коротко", review_t="Відгук замовника", sources_t="Преса та джерела", faq_t="Часті запитання", more="Читати кейс", related="Інший проєкт",
            cta_t="Ваша стіна – наступний проєкт?", cta_calc="Розрахувати ціну", cta_contact="Замовити проєкт", all_works="Дивитися всі роботи", back="Усі проєкти", gallery_hint="Торкніться, щоб збільшити"),
}

# ---- Braubachstraße: window paintings for German Unity Day 2025 (sources: Stadt Frankfurt / frankfurt-live 02.10.2025, visitfrankfurt)
BB_CITY = 'https://frankfurt.de/aktuelle-meldung/meldungen/graffiti-fuer-frieden-und-freiheit/'
BB_LIVE = 'https://www.frankfurt-live.com/graffiti-fuer-frieden-und-freiheit'
BB_WELT = 'https://weltexpresso.de/index.php/heimspiel/35600-graffiti-fuer-frieden-und-freiheit'
BB_RMV = 'https://www.rheinmainverlag.de/2025/10/02/graffiti-fuer-frieden-und-freiheit-in-frankfurt/'
BB_JAZZ = 'https://www.visitfrankfurt.travel/presse/pressemeldungen/details/jazz-zum-dritten-35-jahre-deutsche-einheit'
CAP.update({
 'bb-philokalist': ("„Frau, Leben, Freiheit“ – Philokalist Concept Store", "“Frau, Leben, Freiheit” (Woman, Life, Freedom) – Philokalist Concept Store", "«Frau, Leben, Freiheit» («Жінка, життя, свобода») – Philokalist Concept Store"),
 'bb-salon': ("„Demokratie lebt vom Mitmachen“ – Frankfurter Salon", "“Demokratie lebt vom Mitmachen” (Democracy thrives on taking part) – Frankfurter Salon", "«Demokratie lebt vom Mitmachen» («Демократія живе участю») – Frankfurter Salon"),
 'bb-iimori': ("„Berlin wird leben und die Mauer wird fallen“ (Willy Brandt) – Iimori Pâtisserie", "“Berlin wird leben und die Mauer wird fallen” (Willy Brandt) – Iimori Pâtisserie", "«Berlin wird leben und die Mauer wird fallen» (Віллі Брандт) – Iimori Pâtisserie"),
})
CASE_PAGES['braubach'] = dict(case='braubach', hero='bb-philokalist', wide=None, gallery=['bb-philokalist', 'bb-salon', 'bb-iimori'], date='2025-10-02', related='georgen', t={
 'de': dict(
  meta=("Schaufenster Graffiti in der Braubachstraße: Frieden & Freiheit | Farbaholix",
        "Schaufenster Graffiti zum Tag der Deutschen Einheit 2025: Slavik (Farbaholix) bemalte sechs Schaufenster in der Braubachstraße – Willy Brandt, „Frau, Leben, Freiheit“ und mehr."),
  focus="Schaufenster Graffiti", kicker="Projektbericht", h1="Graffiti für Frieden und Freiheit: Schaufenster in der Braubachstraße",
  lead="Zum Tag der Deutschen Einheit 2025 – dem 35. Jahrestag – verwandelte der Graffiti-Künstler Viacheslav „Slavik“ Balabaiev (Farbaholix) Schaufenster in der Frankfurter Braubachstraße in Botschaften für Demokratie: Schaufenster Graffiti und Kalligrafie mit Sätzen von Willy Brandt bis zur iranischen Protestbewegung, unter dem Motto „Wir schützen unsere Demokratie – gemeinsam für Freiheit, Vielfalt und Zusammenhalt“.",
  facts=[("Ort", "Braubachstraße, neue Frankfurter Altstadt"), ("Anlass", "Tag der Deutschen Einheit 2025 – 35 Jahre Einheit"), ("Rahmen", "„Jazz zum Dritten“ (Tourismus+Congress GmbH und Stadtmarketing Frankfurt)"),
         ("Initiative", "Café „Das Herz von Frankfurt“"), ("Umfang", "Schaufenster von sechs Geschäften"), ("Zeitraum", "Anfang Oktober 2025, zu sehen bis 5. Oktober")],
  sections=[
   ("Die Idee", ["<p>Römerberg, neue Altstadt und Braubachstraße waren 2025 das Zentrum der Frankfurter Feiern zum Tag der Deutschen Einheit. Das Café „Das Herz von Frankfurt“ um Mengi und Taff Zeleke hatte die Idee, die Schaufenster der Straße sprechen zu lassen – und holte Slavik dazu. Das Projekt lief im Rahmen des traditionellen Bürgerfests „Jazz zum Dritten“, das die Tourismus+Congress GmbH zusammen mit dem Stadtmarketing ausrichtet und das zum 35. Jubiläum auf ein ganzes Wochenende (3.–5. Oktober) wuchs.</p>"]),
   ("Welche Schaufenster gestaltet wurden", ["<p>Mitgemacht haben sechs Adressen in der Braubachstraße:</p><ul><li>Café „Das Herz von Frankfurt“ (Initiative)</li><li>Iimori Pâtisserie</li><li>Frankfurter Salon</li><li>Magus Antiquitäten</li><li>Maison Slilou</li><li>Philokalist Concept Store</li></ul>"]),
   ("Die Botschaften im Schaufenster Graffiti", ["<ul><li><strong>„Berlin wird leben und die Mauer wird fallen!“</strong> – Willy Brandt; der erste Spruch der Reihe, in weißer Kalligrafie mit grünen Farbstrahlen im Fenster der Iimori Pâtisserie.</li>"
                                                "<li><strong>„Frau, Leben, Freiheit“</strong> – der Slogan der iranischen Protestbewegung, im Fenster von Philokalist.</li>"
                                                "<li><strong>„Demokratie lebt vom Mitmachen“</strong> – im Fenster mit der Signatur „Albert Einstein“ versehen, umrahmt von orange-weißen Sprühstrahlen am Frankfurter Salon.</li></ul>"
                                                "<p>Historische Zitate treffen auf aktuelle Fragen – die Verbindung von Wiedervereinigung und dem weltweiten Kampf für Freiheit war der rote Faden.</p>"]),
   ("Besuch der Bürgermeisterin", ["<p>Das Fenster mit „Frau, Leben, Freiheit“ entstand am Mittwoch, 1. Oktober 2025, in Anwesenheit von Bürgermeisterin und Diversitätsdezernentin Nargess Eskandari-Grünberg. Mit dabei waren auch Loucienne Nahih Girmazion vom Philokalist Concept Store und das Team des Cafés „Das Herz von Frankfurt“.</p>"]),
   ("Technik: Kalligrafie trifft Sprühdose", ["<p>Die Schriftzüge sind weiße Kalligrafie direkt auf dem Glas. Dazu kommen Farbstrahlen und weiche Verläufe aus der Sprühdose, die das Licht der Schaufenster aufnehmen – tagsüber wie abends. Die Bilder waren für die Festtage gedacht und bis zum 5. Oktober zu sehen.</p>"]),
  ],
  quote=("Die Demokratie ist kein Geschenk, sondern muss immer wieder gelebt und verteidigt werden.", "Bürgermeisterin Nargess Eskandari-Grünberg zum Projekt, 1. Oktober 2025 (sinngemäß laut Stadt Frankfurt)"),
  review=None,
  gallery_t="Fotos der Schaufenster",
  sources=[("Stadt Frankfurt am Main: „Graffiti für Frieden und Freiheit“ (02.10.2025)", BB_CITY), ("frankfurt-live.com: „Graffiti für Frieden und Freiheit“ (02.10.2025)", BB_LIVE),
           ("Weltexpresso: „Graffiti für Frieden und Freiheit“", BB_WELT), ("Rhein Main Verlag: „Graffiti für Frieden und Freiheit in Frankfurt“ (02.10.2025)", BB_RMV),
           ("visitfrankfurt: „Jazz zum Dritten – 35 Jahre Deutsche Einheit“", BB_JAZZ)],
  faq=[("Was ist Schaufenster Graffiti?", "Malerei und Kalligrafie direkt auf der Schaufensterscheibe – mit Pinsel und Sprühdose. Sie wirkt von der Straße wie ein Plakat aus Licht und lässt sich später rückstandsfrei entfernen."),
       ("Welche Sprüche standen in der Braubachstraße?", "Unter anderem „Berlin wird leben und die Mauer wird fallen!“ (Willy Brandt), „Frau, Leben, Freiheit“ und „Demokratie lebt vom Mitmachen“."),
       ("Kann ich mein Schaufenster gestalten lassen?", "Ja – für Eröffnungen, Feiertage oder Aktionen. Einen ersten Richtwert gibt der Preisrechner, das Eröffnungspaket kombiniert Fenster, Wand und Event.")],
 ),
 'en': dict(
  meta=("Window Graffiti on Braubachstraße: Peace & Freedom | Farbaholix",
        "Window graffiti for German Unity Day 2025: Slavik (Farbaholix) painted six shop windows on Frankfurt’s Braubachstraße – Willy Brandt, “Woman, Life, Freedom” and more."),
  focus="window graffiti", kicker="Case study", h1="Graffiti for peace and freedom: shop windows on Braubachstraße",
  lead="For German Unity Day 2025 – the 35th anniversary – graffiti artist Viacheslav “Slavik” Balabaiev (Farbaholix) turned shop windows on Frankfurt’s Braubachstraße into messages for democracy: window graffiti and calligraphy with lines from Willy Brandt to the Iranian protest movement, under the motto “We protect our democracy – together for freedom, diversity and solidarity”.",
  facts=[("Location", "Braubachstraße, Frankfurt’s new old town"), ("Occasion", "German Unity Day 2025 – 35 years of unity"), ("Framework", "“Jazz zum Dritten” (Tourismus+Congress GmbH and Frankfurt city marketing)"),
         ("Initiative", "Café “Das Herz von Frankfurt”"), ("Scope", "Windows of six shops"), ("Period", "Early October 2025, on view until 5 October")],
  sections=[
   ("The idea", ["<p>In 2025, Römerberg, the new old town and Braubachstraße were the centre of Frankfurt’s German Unity Day celebrations. Café “Das Herz von Frankfurt”, run by Mengi and Taff Zeleke, came up with the idea of letting the street’s shop windows speak – and brought in Slavik. The project was part of the traditional civic festival “Jazz zum Dritten”, organised by Tourismus+Congress GmbH with the city marketing office, which grew to a full weekend (3–5 October) for the 35th anniversary.</p>"]),
   ("Which windows were painted", ["<p>Six addresses on Braubachstraße took part:</p><ul><li>Café “Das Herz von Frankfurt” (initiative)</li><li>Iimori Pâtisserie</li><li>Frankfurter Salon</li><li>Magus Antiquitäten</li><li>Maison Slilou</li><li>Philokalist Concept Store</li></ul>"]),
   ("The messages in the window graffiti", ["<ul><li><strong>“Berlin wird leben und die Mauer wird fallen!”</strong> (“Berlin will live and the wall will fall!”) – Willy Brandt; the first line of the series, in white calligraphy with green rays of paint at Iimori Pâtisserie.</li>"
                                           "<li><strong>“Frau, Leben, Freiheit”</strong> (“Woman, Life, Freedom”) – the slogan of the Iranian protest movement, at Philokalist.</li>"
                                           "<li><strong>“Demokratie lebt vom Mitmachen”</strong> (“Democracy thrives on taking part”) – signed “Albert Einstein” in the window, framed by orange and white spray rays at Frankfurter Salon.</li></ul>"
                                           "<p>Historic quotes meet current issues – the link between reunification and the worldwide struggle for freedom was the common thread.</p>"]),
   ("The mayor’s visit", ["<p>The “Woman, Life, Freedom” window was painted on Wednesday, 1 October 2025, in the presence of Mayor and Diversity Commissioner Nargess Eskandari-Grünberg, together with Loucienne Nahih Girmazion of Philokalist Concept Store and the team of Café “Das Herz von Frankfurt”.</p>"]),
   ("Technique: calligraphy meets spray can", ["<p>The lettering is white calligraphy directly on the glass, combined with rays and soft gradients from the spray can that catch the light of the shop windows – by day and by night. The pieces were made for the festival days and were on view until 5 October.</p>"]),
  ],
  quote=("Democracy is not a gift; it has to be lived and defended again and again.", "Mayor Nargess Eskandari-Grünberg on the project, 1 October 2025 (paraphrased by the City of Frankfurt, translated)"),
  review=None,
  gallery_t="Photos of the windows",
  sources=[("City of Frankfurt: “Graffiti für Frieden und Freiheit” (2 Oct 2025, in German)", BB_CITY), ("frankfurt-live.com: “Graffiti für Frieden und Freiheit” (2 Oct 2025, in German)", BB_LIVE),
           ("Weltexpresso: “Graffiti für Frieden und Freiheit” (in German)", BB_WELT), ("Rhein Main Verlag: “Graffiti für Frieden und Freiheit in Frankfurt” (2 Oct 2025, in German)", BB_RMV),
           ("visitfrankfurt: “Jazz zum Dritten – 35 Jahre Deutsche Einheit” (in German)", BB_JAZZ)],
  faq=[("What is window graffiti?", "Painting and calligraphy directly on the shop window – with brush and spray can. From the street it reads like a poster made of light, and it can be removed without residue later."),
       ("Which lines were painted on Braubachstraße?", "Among others “Berlin wird leben und die Mauer wird fallen!” (Willy Brandt), “Frau, Leben, Freiheit” and “Demokratie lebt vom Mitmachen”."),
       ("Can I have my shop window painted?", "Yes – for openings, holidays or campaigns. The price calculator gives a first estimate; the opening package combines window, wall and event.")],
 ),
 'uk': dict(
  meta=("Графіті на вітринах Braubachstrasse: мир і свобода | Farbaholix",
        "Графіті на вітринах до Дня німецької єдності 2025: Славік (Farbaholix) розписав шість вітрин на Braubachstrasse у Франкфурті – Віллі Брандт, «Жінка, життя, свобода» та інше."),
  focus="Braubachstrasse", kicker="Кейс", h1="Графіті за мир і свободу: вітрини на Braubachstrasse",
  lead="До Дня німецької єдності 2025 року – 35-ї річниці – графіті-художник В’ячеслав «Славік» Балабаєв (Farbaholix) перетворив вітрини на Braubachstrasse у Франкфурті на послання на захист демократії: графіті й каліграфія з цитатами від Віллі Брандта до гасла іранського протестного руху, під девізом «Ми захищаємо нашу демократію – разом за свободу, різноманіття й згуртованість».",
  facts=[("Місце", "Braubachstrasse, нове Старе місто Франкфурта"), ("Привід", "День німецької єдності 2025 – 35 років єдності"), ("Рамки", "«Jazz zum Dritten» (Tourismus+Congress GmbH і міський маркетинг Франкфурта)"),
         ("Ініціатива", "Кафе «Das Herz von Frankfurt»"), ("Обсяг", "Вітрини шести закладів"), ("Період", "Початок жовтня 2025, до 5 жовтня")],
  sections=[
   ("Ідея", ["<p>У 2025 році Рьомерберг, нове Старе місто й Braubachstrasse стали центром святкування Дня німецької єдності у Франкфурті. Кафе «Das Herz von Frankfurt» (Менгі й Тафф Зелеке) придумало дати слово вітринам вулиці – і запросило Славіка. Проєкт став частиною традиційного міського свята «Jazz zum Dritten», яке Tourismus+Congress GmbH проводить разом із міським маркетингом; до 35-річчя воно розтягнулося на цілі вихідні (3–5 жовтня).</p>"]),
   ("Які вітрини розписали", ["<p>Долучилися шість адрес на Braubachstrasse:</p><ul><li>Кафе «Das Herz von Frankfurt» (ініціатор)</li><li>Iimori Pâtisserie</li><li>Frankfurter Salon</li><li>Magus Antiquitäten</li><li>Maison Slilou</li><li>Philokalist Concept Store</li></ul>"]),
   ("Послання на вітринах Braubachstrasse", ["<ul><li><strong>«Berlin wird leben und die Mauer wird fallen!»</strong> («Берлін житиме, а стіна впаде!») – Віллі Брандт; перша цитата серії, біла каліграфія з зеленими променями на вітрині Iimori Pâtisserie.</li>"
                                           "<li><strong>«Frau, Leben, Freiheit»</strong> («Жінка, життя, свобода») – гасло іранського протестного руху, на вітрині Philokalist.</li>"
                                           "<li><strong>«Demokratie lebt vom Mitmachen»</strong> («Демократія живе участю») – на вітрині з підписом «Albert Einstein», в обрамленні оранжево-білих променів біля Frankfurter Salon.</li></ul>"
                                           "<p>Історичні цитати зустрічаються з актуальними питаннями – зв’язок між возз’єднанням Німеччини й світовою боротьбою за свободу став наскрізною ниткою.</p>"]),
   ("Візит бургомістерки", ["<p>Вітрина «Frau, Leben, Freiheit» з’явилася в середу, 1 жовтня 2025 року, у присутності бургомістерки й очільниці відділу з питань різноманіття Наргес Ескандарі-Грюнберг, разом із Лусьєнн Нахіх Гірмазіон із Philokalist Concept Store і командою кафе «Das Herz von Frankfurt».</p>"]),
   ("Техніка: каліграфія й балончик", ["<p>Написи – це біла каліграфія прямо на склі. До неї додаються промені й м’які переходи з балончика, що ловлять світло вітрин – і вдень, і ввечері. Роботи задумувалися на святкові дні й були на вітринах до 5 жовтня.</p>"]),
  ],
  quote=("Демократія – не подарунок, її треба знову й знову проживати й захищати.", "Бургомістерка Наргес Ескандарі-Грюнберг про проєкт, 1 жовтня 2025 (за переказом міста Франкфурт, переклад)"),
  review=None,
  gallery_t="Фото вітрин",
  sources=[("Місто Франкфурт: «Graffiti für Frieden und Freiheit» (02.10.2025, німецькою)", BB_CITY), ("frankfurt-live.com: «Graffiti für Frieden und Freiheit» (02.10.2025, німецькою)", BB_LIVE),
           ("Weltexpresso: «Graffiti für Frieden und Freiheit» (німецькою)", BB_WELT), ("Rhein Main Verlag: «Graffiti für Frieden und Freiheit in Frankfurt» (02.10.2025, німецькою)", BB_RMV),
           ("visitfrankfurt: «Jazz zum Dritten – 35 Jahre Deutsche Einheit» (німецькою)", BB_JAZZ)],
  faq=[("Що таке графіті на вітринах?", "Розпис і каліграфія прямо на склі вітрини – пензлем і балончиком. З вулиці це виглядає як світловий плакат, а згодом його можна прибрати без слідів."),
       ("Які цитати були на Braubachstrasse?", "Зокрема «Berlin wird leben und die Mauer wird fallen!» (Віллі Брандт), «Frau, Leben, Freiheit» і «Demokratie lebt vom Mitmachen»."),
       ("Чи можна замовити розпис своєї вітрини?", "Так – до відкриття, свят чи акцій. Перший орієнтир дасть калькулятор ціни, а пакет «Відкриття» поєднує вітрину, стіну й подію.")],
 ),
})
