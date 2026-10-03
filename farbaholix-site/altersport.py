"""Hidden page "altersport": media reports about the Mykolaiv youth NGO "Alter-Sport" (founded 2004, head Roland Bairozian),
where Slavik (BVB) was a member. Same format as smi_bvb.py: not linked, noindex; full texts on a password page.
Raw copies in archive/altersport/ (gitignored)."""
import json, os

ARCHIVED = '03.10.2026'
_EXF = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'archive', 'altersport', 'extract.json')
EX = json.load(open(_EXF)) if os.path.exists(_EXF) else None

UI = {
    'de': dict(title='„Alter-Sport“ Mykolajiw in den Medien', kicker='Medienarchiv · Jugendorganisation, 2004–2019',
               lead='Alle auffindbaren Berichte über die Mykolajiwer Jugendorganisation „Alter-Sport“ – Extremsport, Skateparks, Fahrradbewegung und Stadtentwicklung. Slavik (BVB) war Mitglied und Aktivist der Organisation. Jeder Eintrag nennt Quelle, Datum und Originallink; Texte und Fotos wurden am %s gesichert.' % ARCHIVED,
               bio_t='Die Organisation in Kürze', tl_t='Chronik der Berichte', orig='Originalartikel', arch='Archivkopie (Passwort)', wb='Kopie im Internet Archive',
               status={'ok': 'Text und Foto lokal gesichert', 'txt': 'Text lokal gesichert'}, credit='Fotos: jeweilige Redaktionen, siehe Quelle.', orig_lang={'ru': 'Original auf Russisch', 'uk': 'Original auf Ukrainisch'},
               note='Interne Seite – nicht verlinkt und nicht in Suchmaschinen.', bvb='mit BVB'),
    'en': dict(title='“Alter-Sport” Mykolaiv in the media', kicker='Media archive · youth organisation, 2004–2019',
               lead='Every report we could find about the Mykolaiv youth organisation “Alter-Sport” – extreme sports, skate parks, the cycling movement and urban development. Slavik (BVB) was a member and activist. Each entry gives source, date and the original link; texts and photos were saved on %s.' % ARCHIVED,
               bio_t='The organisation in brief', tl_t='Timeline of reports', orig='Original article', arch='Archive copy (password)', wb='Copy in the Internet Archive',
               status={'ok': 'Text and photo saved locally', 'txt': 'Text saved locally'}, credit='Photos: the respective newsrooms, see source.', orig_lang={'ru': 'Original in Russian', 'uk': 'Original in Ukrainian'},
               note='Internal page – not linked and not indexed by search engines.', bvb='with BVB'),
    'uk': dict(title='«Альтер-Спорт» Миколаїв у медіа', kicker='Медіаархів · молодіжна організація, 2004–2019',
               lead='Усі знайдені публікації про миколаївську молодіжну організацію «Альтер-Спорт» – екстремальний спорт, скейт-парки, веломух і розвиток міста. Славік (BVB) був її членом і активістом. Для кожного запису – джерело, дата й посилання на оригінал; тексти й фото збережено %s.' % ARCHIVED,
               bio_t='Організація коротко', tl_t='Хроніка публікацій', orig='Оригінал статті', arch='Архівна копія (пароль)', wb='Копія в Internet Archive',
               status={'ok': 'Текст і фото збережено локально', 'txt': 'Текст збережено локально'}, credit='Фото: відповідні редакції, див. джерело.', orig_lang={'ru': 'Оригінал російською', 'uk': 'Оригінал українською'},
               note='Внутрішня сторінка – без посилань і без індексації пошуковиками.', bvb='з BVB'),
}

BIO = {
    'de': [('2001–2004', 'aus der BMX-, Skate- und Inliner-Szene Mykolajiws entsteht die Idee einer Organisation, die sich für einen Skatepark einsetzt; im Mai 2004 wird „Alter-Sport“ registriert, Vorsitzender: Roland Bajrosjan.'),
           ('Profil', 'rund 17–18 Disziplinen – Skateboarding, BMX und Flatland, Trial, Inline, Workout, Rollhockey; 2013 etwa 120 Mitglieder, davon 20 aktiv, im Alter von 14 bis 36 Jahren.'),
           ('seit 2010', '„Welodenj“ (Fahrradtag) – von 15–20 Leuten zu über 1.200 Teilnehmenden; dazu das Cross-Country-Rennen „Gonka Pobedy“ im Park Peremohy.'),
           ('2012', 'erster Skatepark Mykolajiws im Park Peremohy – finanziert über den Wettbewerb „Territorija RUSALa“ und den Gestaltungswettbewerb „Herz der Stadt“; kostenlose Sektionen für BMX, Inline, Skateboard, Trial und Flatland.'),
           ('2012–2016', 'mit dem Filmklub RealityShiftCinema jährlich das Manhattan-Kurzfilmfestival und die „Offene Nacht“ in Mykolajiw.'),
           ('2013', 'zweiter RUSAL-Zuschuss (300.000 Hrywnja) – daraus entsteht der Sportpark „Korabelnyj“ mit Skatepark und Workout-Fläche; BVB legt als Vertreter von „Alter-Sport“ die Zeitkapsel, Eröffnung am 4. November.'),
           ('2014–2015', 'Extremsport-Shows und Wettbewerbe im Skatepark Korabelnyj, Auftritte bei Stadtfesten, Radsport-Meisterschaft und Gesundheitsaktionen; 2015 Projekt „Sommersaison im Skatepark“.'),
           ('2016–2017', 'mit der Agentur für Entwicklung Mykolajiws: „Mykolaiv Urban Days“, Fahrradparade zum Stadttag (rund 1.000 Teilnehmende), Fahrradkonzept der Stadt; Mitveranstalter des internationalen „Welo-Forums 2017“ mit über 100 Teilnehmenden aus 8 Ländern.'),
           ('2019', 'Graffiti „Wir sind hier, um zu kreieren“ von BVB am neuen Skatepark-Gelände bei der Sportschule „Nadeschda“, organisiert von Roland Bajrosjan.')],
    'en': [('2001–2004', 'from Mykolaiv’s BMX, skate and inline scene comes the idea of an organisation lobbying for a skate park; “Alter-Sport” is registered in May 2004, chaired by Roland Bairozian.'),
           ('Profile', 'some 17–18 disciplines – skateboarding, BMX and flatland, trial, inline, workout, roller hockey; in 2013 about 120 members, 20 of them active, aged 14 to 36.'),
           ('since 2010', 'the “Velo Day” – from 15–20 riders to more than 1,200; plus the cross-country race “Gonka Pobedy” in Peremohy Park.'),
           ('2012', 'Mykolaiv’s first skate park in Peremohy Park – funded through the “Territory of RUSAL” competition and the design contest “Heart of the City”; free classes in BMX, inline, skateboarding, trial and flatland.'),
           ('2012–2016', 'with the film club RealityShiftCinema, the annual Manhattan Short Film Festival and the “Open Night” in Mykolaiv.'),
           ('2013', 'a second RUSAL grant (300,000 hryvnias) becomes the Korabelnyi sports park with skate park and workout area; BVB lays the time capsule for Alter-Sport, opening on 4 November.'),
           ('2014–2015', 'extreme-sport shows and contests at the Korabelnyi skate park, performances at city festivals, a national cycling championship and health events; in 2015 the project “Summer season at the skate park”.'),
           ('2016–2017', 'with the Mykolaiv Development Agency: “Mykolaiv Urban Days”, a bike parade on City Day (about 1,000 riders), the city’s cycling concept; co-organiser of the international “Velo Forum 2017” with 100+ participants from 8 countries.'),
           ('2019', 'BVB’s graffiti “We are here to create” at the new skate-park site next to the Nadezhda sports school, organised by Roland Bairozian.')],
    'uk': [('2001–2004', 'з миколаївської BMX-, скейт- і ролер-тусовки виникає ідея організації, яка лобіюватиме скейт-парк; у травні 2004 року «Альтер-Спорт» зареєстровано, голова – Роланд Байрозян.'),
           ('Профіль', 'близько 17–18 дисциплін – скейтбординг, BMX і флетленд, велотріал, ролики, воркаут, хокей на роликах; у 2013 році близько 120 членів, з них 20 активних, віком від 14 до 36 років.'),
           ('з 2010', '«Велодень» – від 15–20 людей до понад 1200 учасників; а також крос-кантрі «Гонка Перемоги» в парку Перемоги.'),
           ('2012', 'перший скейт-парк Миколаєва в парку Перемоги – за конкурсом «Територія РУСАЛу» та конкурсом дизайн-проєктів «Серце міста»; безкоштовні секції BMX, роликів, скейтбордингу, тріалу й флетленду.'),
           ('2012–2016', 'разом із кіноклубом RealityShiftCinema – щорічний Манхеттенський фестиваль короткометражок і «Відкрита ніч» у Миколаєві.'),
           ('2013', 'другий грант РУСАЛу (300 тис. грн) – з нього постає Парк спорту «Корабельний» зі скейт-парком і воркаутом; BVB від «Альтер-Спорту» закладає капсулу, відкриття 4 листопада.'),
           ('2014–2015', 'екстрим-шоу та змагання у скейт-парку «Корабельний», виступи на міських святах, чемпіонаті з велоспорту й акціях здоров’я; у 2015 році проєкт «Літній сезон у скейт-парку».'),
           ('2016–2017', 'разом з Агенцією розвитку Миколаєва: Mykolaiv Urban Days, велопарад до Дня міста (близько 1000 учасників), велоконцепція міста; співорганізатор міжнародного «Велофоруму-2017» – понад 100 учасників із 8 країн.'),
           ('2019', 'графіті BVB «Ми тут, щоб творити» на місці нового скейт-парку біля спортшколи «Надія», організатор – Роланд Байрозян.')],
}

IMGS = ["active-2017", "chempionat-2015", "den-molodi-2017", "gonka-2016", "olymp-2013", "retro-2026", "skate-vn-2019", "urban-days-2016", "veloden-2017", "veloden-2019"]

def _t(de, en, uk): return {'de': de, 'en': en, 'uk': uk}

# (key in extract.json, date, outlet, original language, involves BVB, summary, quotes)
KOR = 'Корабелов.info (korabelov.info)'; NP = 'Миколаївська правда (nikpravda.com.ua)'
ROWS = [
 ('skatepark-2012', '20.09.2012', KOR, 'uk', False, _t(
   'Einladung zur Eröffnung des ersten Skateparks Mykolajiws im Park Peremohy am 22.09.2012 – möglich durch „Alter-Sport“ im Wettbewerb „Territorija RUSALa“ und den Wettbewerb „Herz der Stadt“; geplant sind kostenlose Sektionen für BMX, Inline, Skateboard, Trial und Flatland.',
   'Invitation to the opening of Mykolaiv’s first skate park in Peremohy Park on 22.09.2012 – made possible by Alter-Sport in the “Territory of RUSAL” competition and the “Heart of the City” contest; free classes in BMX, inline, skateboarding, trial and flatland are planned.',
   'Запрошення на відкриття першого скейт-парку Миколаєва в парку Перемоги 22.09.2012 – завдяки участі «Альтер-Спорту» в конкурсі «Територія РУСАЛу» та конкурсі «Серце міста»; заплановано безкоштовні секції BMX, роликів, скейтбордингу, тріалу й флетленду.'), []),
 ('gurt-2013', '13.03.2013', 'Ресурсний центр ГУРТ (gurt.org.ua)', 'uk', False, _t(
   'Ausführliches Interview mit dem Vorsitzenden Roland Bajrosjan: Gründung im Mai 2004 aus der BMX-Szene, 17–18 Disziplinen, 120 Mitglieder, der erste Skatepark der Stadt als größter Erfolg, Finanzierung zu 80–90 % über Projekte mit der Gebietsverwaltung.',
   'In-depth interview with chairman Roland Bairozian: founded in May 2004 out of the BMX scene, 17–18 disciplines, 120 members, the city’s first skate park as the biggest achievement, 80–90% of funding from projects with the regional administration.',
   'Велике інтерв’ю з головою Роландом Байрозяном: заснування у травні 2004 року з BMX-тусовки, 17–18 дисциплін, 120 членів, перший скейт-парк міста як головне досягнення, 80–90 % фінансування – проєкти з облдержадміністрацією.'),
   [('А загалом найбільша нестача відчувається завжди у справжніх лідерах та коштах.', _t('Am meisten fehlt es immer an echten Führungspersönlichkeiten und an Geld.', 'What we always lack most is real leaders and money.', None))]),
 ('velodorozhky-2013', '26.03.2013', KOR, 'ru', False, _t(
   'Ankündigung einer offenen Diskussion „Neues Mykolajiw“ über Radwege; Roland Bajrosjan spricht über „Alter-Sport und Fahrradkultur“.',
   'Announcement of an open discussion “New Mykolaiv” on cycle lanes; Roland Bairozian speaks on “Alter-Sport and cycling culture”.',
   'Анонс відкритого обговорення «Новий Миколаїв» про велодоріжки; Роланд Байрозян – доповідь «Альтер-Спорт і велокультура».'), []),
 ('shkola29-2013', '16.05.2013', KOR, 'uk', False, _t(
   'Die Schule Nr. 29 bekommt als erste Schule der Stadt einen Fahrradständer; Roland Bajrosjan und Anton Horodezkyj von „Alter-Sport“ erzählen den Schülern von Fahrradinfrastruktur und europäischen Erfahrungen.',
   'School No. 29 becomes the first in the city with a bike rack; Roland Bairozian and Anton Horodetskyi of Alter-Sport tell pupils about cycling infrastructure and European experience.',
   'ЗОШ №29 – перша школа міста з власною велостоянкою; Роланд Байрозян і Антон Городецький з «Альтер-Спорту» розповідають учням про велоінфраструктуру та європейський досвід.'), []),
 ('olymp-2013', '05.2013', 'Губернський тиждень (gweek.com.ua)', 'ru', False, _t(
   'Fahrradkorso zum Internationalen Olympischen Tag auf der Admiralska-Straße; „die jungen Aktivisten von Alter-Sport um Roland Bajrosjan“ organisieren die Fahrt seit Jahren.',
   'Bike ride on Admiralska Street for International Olympic Day; “the young activists of Roland Bairozian’s Alter-Sport” have been organising it for years.',
   'Велопробіг до Міжнародного олімпійського дня на Адміральській; «молоді громадські активісти «Альтер-Спорту» Роланда Байрозяна» організовують його вже не перший рік.'), []),
 ('vodoley-2013', '26.06.2013', KOR, 'ru', False, _t(
   'Mit dem zweiten Zuschuss aus „Territorija RUSALa“ (300.000 Hrywnja) soll neben dem Schwimmbad „Wodolej“ im Bezirk Korabelnyj ein neuer Sportpark entstehen; Behörden, RUSAL und „Alter-Sport“ besichtigen das Gelände.',
   'With a second “Territory of RUSAL” grant (300,000 hryvnias) a new sports park is to be built next to the Vodoliy pool in Korabelnyi district; officials, RUSAL and Alter-Sport inspect the site.',
   'За другий грант «Території РУСАЛу» (300 тис. грн) біля басейну «Водолій» у Корабельному районі має з’явитися новий спортивний майданчик; влада, РУСАЛ і «Альтер-Спорт» оглядають ділянку.'), []),
 ('dobro-2013', '29.08.2013', KOR, 'ru', False, _t(
   'Wohltätigkeitsaktion „Lasst uns Gutes tun“ für Kinder aus dem Internat Nr. 2 – mit Auftritten der Sportler von „Alter-Sport“.',
   'Charity event “Let’s do good” for children from boarding school No. 2 – with performances by Alter-Sport athletes.',
   'Благодійна акція «Давайте робити добро» для дітей з інтернату №2 – за участі спортсменів «Альтер-Спорту».'), []),
 ('kapsula-2013', '06.09.2013', KOR, 'ru', True, _t(
   'Grundsteinlegung des Sportparks „Korabelnyj“: Viacheslav Balabaiev (BVB) legt als Vertreter von „Alter-Sport“ die Zeitkapsel „An das Mykolajiw der Zukunft“.',
   'Ground-breaking of the Korabelnyi sports park: Viacheslav Balabaiev (BVB) lays the time capsule “To the Mykolaiv of the future” on behalf of Alter-Sport.',
   'Закладка Парку спорту «Корабельний»: В’ячеслав Балабаєв (BVB) від «Альтер-Спорту» закладає капсулу «Миколаєву майбутнього».'), []),
 ('rukavytsi-2013', '09.09.2013', KOR, 'ru', True, _t(
   'Ironische Nachlese: Die Gebietsspitze zieht die Arbeitshandschuhe falsch an – „Alter-Sport“-Aktivist Viacheslav Balabaiev zeigt, wie es richtig geht.',
   'Ironic follow-up: the regional leadership wears its work gloves wrong – Alter-Sport activist Viacheslav Balabaiev shows how it is done.',
   'Іронічний матеріал: керівництво області вдягло рукавиці навиворіт – активіст «Альтер-Спорту» В’ячеслав Балабаєв показав, як правильно.'), []),
 ('montazh-2013', '11.09.2013', KOR, 'ru', False, _t(
   'Die Skatepark-Elemente für den Sportpark „Korabelnyj“ treffen ein – die Kinder fahren schon, bevor alles montiert ist.',
   'The skate-park elements for the Korabelnyi sports park arrive – children start riding before assembly is finished.',
   'Обладнання скейт-парку для Парку спорту «Корабельний» прибуло – діти катаються ще до завершення монтажу.'), []),
 ('nedelya-dobra-2013', '15.10.2013', KOR, 'ru', False, _t(
   'Programm der sechsten „Herbstwoche des Guten“: „Alter-Sport“ organisiert ein Sportfest im Kastanienpark.',
   'Programme of the sixth “Autumn Week of Kindness”: Alter-Sport organises a sports festival in Chestnut Square.',
   'Програма шостого «Осіннього тижня добра»: «Альтер-Спорт» організовує спортивне свято в Каштановому сквері.'), []),
 ('sessiya-2013', '18.10.2013', KOR, 'ru', False, _t(
   'Auswärtssitzung des Stadtrats im neuen Sportpark; der stellvertretende Bezirkschef Ihor Kopejka: „Die Idee kam von Alter-Sport, wir haben sie unterstützt.“',
   'Off-site city council session at the new sports park; deputy district head Ihor Kopeika: “The idea was Alter-Sport’s, we supported it.”',
   'Виїзне засідання міськради в новому спортмістечку; заступник голови району Ігор Копійка: «Ідея була «Альтер-Спорту», ми її підтримали».'),
   [('Идея была «Альтер-спорта», мы ее поддержали, а дальше молодежь должна внести предложения, что они хотят здесь видеть.', _t('Die Idee kam von Alter-Sport, wir haben sie unterstützt – jetzt soll die Jugend sagen, was sie hier sehen will.', 'The idea was Alter-Sport’s, we supported it – now young people should say what they want to see here.', 'Ідея була «Альтер-Спорту», ми її підтримали, а далі молодь має запропонувати, що вона хоче тут бачити.'))]),
 ('isakov-2013', '24.10.2013', KOR, 'ru', False, _t(
   'Stadtrat Serhij Isakow stellt Fragen zur Finanzierung des Sportparks „Korabelnyj“ – je 300.000 Hrywnja von RUSAL und von „Alter-Sport“.',
   'Councillor Serhii Isakov questions the funding of the Korabelnyi sports park – 300,000 hryvnias each from RUSAL and from Alter-Sport.',
   'Депутат Сергій Ісаков ставить питання щодо фінансування спортмістечка «Корабельний» – по 300 тис. грн від РУСАЛу та від «Альтер-Спорту».'), []),
 ('spartakiada-2013', '24.10.2013', KOR, 'ru', False, _t(
   'Spartakiade der Vorschulkinder im Bezirk Korabelnyj – mit „Tänzen auf Fahrrädern“ der Mitglieder von „Alter-Sport“.',
   'Pre-school sports day in Korabelnyi district – with “dances on bicycles” by Alter-Sport members.',
   'Спартакіада дошкільнят Корабельного району – з «танцями на велосипедах» від учасників «Альтер-Спорту».'), []),
 ('vidkryttia-2013', '04.11.2013', KOR, 'ru', False, _t(
   'Feierliche Eröffnung des Sportparks „Korabelnyj“. Bezirkschef Ihor Djatlow holt Roland Bajrosjan auf die Bühne – mit dem Projekt von „Alter-Sport“ hatte alles begonnen.',
   'Official opening of the Korabelnyi sports park. District head Ihor Diatlov calls Roland Bairozian on stage – it all began with Alter-Sport’s project.',
   'Урочисте відкриття Парку спорту «Корабельний». Голова району Ігор Дятлов кличе на сцену Роланда Байрозяна – саме з проєкту «Альтер-Спорту» все почалося.'),
   [('Не скромничай, люди должны знать своих героев в лицо.', _t('Sei nicht so bescheiden – die Leute sollen ihre Helden kennen. (Ihor Djatlow)', 'Don’t be modest – people should know their heroes by sight. (Ihor Diatlov)', 'Не скромничай, люди мають знати своїх героїв в обличчя. (Ігор Дятлов)'))]),
 ('zaryadka-2014', '04.04.2014', KOR, 'ru', False, _t(
   'Aktion zum Weltgesundheitstag mit Schauauftritt des Teams „Alter-Sport“.',
   'World Health Day event with a demonstration by the Alter-Sport team.',
   'Акція до Всесвітнього дня здоров’я з показовим виступом команди «Альтер-Спорт».'), []),
 ('z-ditmy-anons-2014', '27.05.2014', KOR, 'ru', False, _t(
   'Ankündigung des Kinderfests „Gemeinsam mit den Kindern“: „Alter-Sport“ zeigt eine Extremsport-Show im Skatepark, danach Wettbewerbe auf Skateboard, Inlinern und BMX.',
   'Announcement of the children’s festival “Together with the children”: Alter-Sport puts on an extreme-sport show at the skate park, followed by skateboard, inline and BMX contests.',
   'Анонс свята «Разом із дітьми»: «Альтер-Спорт» покаже екстрим-шоу в скейт-парку, далі змагання на скейтах, роликах і BMX.'), []),
 ('veloden-2014', '31.05.2014', KOR, 'ru', False, _t(
   'Rund 600 Radfahrer fahren beim Welodenj durch das Zentrum – Organisator Roland Bajrosjan betont: keine politische, sondern eine Geste des guten Willens.',
   'About 600 cyclists ride through the centre on Velo Day – organiser Roland Bairozian stresses: not political, a gesture of good will.',
   'Близько 600 велосипедистів проїхали центром на Велодень – організатор Роланд Байрозян наголошує: акція не політична, а жест доброї волі.'), []),
 ('z-ditmy-2014', '10.06.2014', KOR, 'ru', False, _t(
   'Bericht vom Kinderfest: „Alter-Sport“ veranstaltet mit Unterstützung von RUSAL Wettbewerbe für Roller, Skater und BMX-Fahrer im Skatepark.',
   'Report from the children’s festival: with RUSAL’s support, Alter-Sport holds contests for inline skaters, skateboarders and BMX riders at the skate park.',
   'Репортаж зі свята: «Альтер-Спорт» за підтримки РУСАЛу провів у скейт-парку змагання для ролерів, скейтерів і BMX-ерів.'), []),
 ('kino-2014', '25.06.2014', KOR, 'ru', False, _t(
   'Das Filmfestival „Widkryta nitsch“ („Offene Nacht“) kommt nach Mykolajiw – seit 2012 auf Initiative des Filmklubs RealityShiftCinema und von „Alter-Sport“.',
   'The film festival “Vidkryta nich” (“Open Night”) comes to Mykolaiv – since 2012 on the initiative of the RealityShiftCinema film club and Alter-Sport.',
   'Кінофестиваль «Відкрита ніч» у Миколаєві – з 2012 року з ініціативи кіноклубу RealityShiftCinema та «Альтер-Спорту».'), []),
 ('chempionat-2015', '26.03.2015', 'НікВісті (nikvesti.com)', 'ru', False, _t(
   'Start der ukrainischen Radsportmeisterschaft (Kriterium) in Mykolajiw – vorab eine Schaueinlage der „in Mykolajiw gut bekannten Jugendorganisation Alter-Sport“.',
   'Start of the Ukrainian cycling championship (criterium) in Mykolaiv – opened by a demonstration from “the youth organisation Alter-Sport, well known in Mykolaiv”.',
   'Старт чемпіонату України з велоспорту (критеріум) у Миколаєві – перед ним показовий виступ «добре відомої миколаївцям молодіжної організації «Альтер-Спорт».'), []),
 ('formula-2015', '14.05.2015', KOR, 'ru', False, _t(
   'Gewinner des RUSAL-Wettbewerbs „Formel der Zukunft 2015“: darunter „Sommersaison im Skatepark“ von „Alter-Sport“ – Wettbewerbe und Shows in Skateboard, BMX Park, Aggressive Inline und Inline-Slalom.',
   'Winners of RUSAL’s “Formula of the Future 2015”: among them Alter-Sport’s “Summer season at the skate park” – contests and shows in skateboarding, BMX park, aggressive inline and inline slalom.',
   'Переможці конкурсу РУСАЛу «Формула майбутнього-2015»: серед них «Літній сезон у скейт-парку» від «Альтер-Спорту» – змагання й шоу зі скейтбордингу, BMX park, агресивних роликів та інлайн-слалому.'), []),
 ('veloden-2015', '30.05.2015', KOR, 'ru', False, _t(
   'Welodenj 2015: Roland Bajrosjan und Mykola Dmytrijew stellen eine Initiativgruppe für das Fahrradkonzept der Stadt vor – erster Schritt: Fahrradständer.',
   'Velo Day 2015: Roland Bairozian and Mykola Dmytriiev present an initiative group for the city’s cycling concept – first step: bike racks.',
   'Велодень-2015: Роланд Байрозян і Микола Дмитрієв представляють ініціативну групу з велоконцепції міста – першим кроком стануть велопарковки.'), []),
 ('zmagannia-2015', '08.06.2015', KOR, 'ru', False, _t(
   'Wettbewerbe im Skatepark Korabelnyj; RUSAL erinnert: 2013 gewann „Alter-Sport“ den Zuschuss für den Bau, 2015 erneut einen Wettbewerb.',
   'Contests at the Korabelnyi skate park; RUSAL recalls that Alter-Sport won the construction grant in 2013 and another competition in 2015.',
   'Змагання у скейт-парку «Корабельний»; у РУСАЛі нагадують: 2013 року «Альтер-Спорт» виграв грант на будівництво, 2015-го – ще один конкурс.'),
   [('С момента открытия скейт-площадка в Корабельном пользуется большой популярностью у молодежи района.', _t('Seit der Eröffnung ist die Skate-Anlage in Korabelnyj bei den Jugendlichen des Bezirks sehr beliebt. (Roland Bajrosjan)', 'Since it opened, the Korabelnyi skate area has been very popular with the district’s young people. (Roland Bairozian)', 'Від відкриття скейт-майданчик у Корабельному дуже популярний серед молоді району. (Роланд Байрозян)'))]),
 ('gonka-2016', '28.03.2016', KOR + ' · NikLife', 'ru', False, _t(
   'Cross-Country-Rennen „Gonka Pobedy“ im Park Peremohy (seit 2010): 51 Fahrer aus Mykolajiw, Odesa, Cherson und Piwdennoukrajinsk legen zusammen 809,5 km zurück; Mitveranstalter Roland Bajrosjan.',
   'Cross-country race “Gonka Pobedy” in Peremohy Park (since 2010): 51 riders from Mykolaiv, Odesa, Kherson and Yuzhnoukrainsk cover 809.5 km in total; co-organised by Roland Bairozian.',
   'Крос-кантрі «Гонка Перемоги» в парку Перемоги (з 2010 року): 51 велосипедист із Миколаєва, Одеси, Херсона й Південноукраїнська разом проїхали 809,5 км; співорганізатор – Роланд Байрозян.'), []),
 ('veloden-2016', '27.05.2016', NP, 'ru', False, _t(
   'Ankündigung des „Allukrainischen Welodenj“ 2016 – Veranstalter: „Alter-Sport“, „Welorukh Mykolajiw“, die Entwicklungsagentur und der Bürgermeister.',
   'Announcement of the “All-Ukrainian Velo Day” 2016 – organisers: Alter-Sport, “Velorukh Mykolaiv”, the development agency and the mayor.',
   'Анонс «Всеукраїнського Велодня» 2016 – організатори: «Альтер-Спорт», «Велорух Миколаїв», Агенція розвитку та міський голова.'), []),
 ('urban-days-2016', '23.08.2016', KOR, 'uk', False, _t(
   'Der Stadthaushalt fördert 18 soziale Projekte – auf Platz eins: die Stadtentwicklungswoche „Mykolaiv Urban Days“ von „Alter-Sport“.',
   'The city budget funds 18 social projects – in first place: the urban development week “Mykolaiv Urban Days” by Alter-Sport.',
   'Міський бюджет профінансує 18 соцпроєктів – перше місце: тиждень міського розвитку Mykolaiv Urban Days від «Альтер-Спорту».'), []),
 ('veloparad-2016', '05.09.2016', NP, 'uk', False, _t(
   'Aufruf zur großen Fahrradparade zum Stadttag – Veranstalter: Entwicklungsagentur, „Alter-Sport“ und „Welorukh“; erwartet werden über 1.000 Teilnehmende.',
   'Call to join the big City Day bike parade – organisers: development agency, Alter-Sport and “Velorukh”; over 1,000 riders expected.',
   'Запрошення на масштабний велопарад до Дня міста – організатори: Агенція розвитку, «Альтер-Спорт» і «Велорух»; очікують понад тисячу учасників.'), []),
 ('kino-2016', '19.09.2016', NP, 'ru', False, _t(
   'Mykolajiw nimmt zum fünften Mal am Manhattan Short Film Festival teil – seit 2012 auf Initiative von RealityShiftCinema und „Alter-Sport“.',
   'Mykolaiv takes part in the Manhattan Short Film Festival for the fifth time – since 2012 on the initiative of RealityShiftCinema and Alter-Sport.',
   'Миколаїв уп’яте долучається до Манхеттенського фестивалю короткометражок – з 2012 року з ініціативи RealityShiftCinema та «Альтер-Спорту».'), []),
 ('pryberannia-2016', '01.10.2016', NP, 'ru', False, _t(
   'Roland Bajrosjan ruft zum Aufräumen im Skatepark des Parks Peremohy auf.',
   'Roland Bairozian calls for a clean-up of the skate park in Peremohy Park.',
   'Роланд Байрозян закликає прибрати скейт-парк у парку Перемоги.'), []),
 ('pryberannia2-2016', '12.10.2016', NP, 'ru', False, _t(
   'Ergebnis: Freiwillige räumen den Park Peremohy beim Skatepark und die Allee des olympischen Ruhms auf.',
   'Result: volunteers clean up Peremohy Park around the skate park and the Alley of Olympic Glory.',
   'Результат: волонтери прибрали парк Перемоги біля скейт-парку та алею олімпійської слави.'), []),
 ('veloforum-perem-2016', '03.11.2016', NP, 'ru', False, _t(
   'Pressekonferenz: Mykolajiw erhält das internationale „Welo-Forum 2017“. Roland Bajrosjan erklärt, warum die Stadt den Zuschlag bekam – Fahrradkonzept, Urban Days und Unterstützung der Stadtverwaltung.',
   'Press conference: Mykolaiv wins the international “Velo Forum 2017”. Roland Bairozian explains why – the cycling concept, Urban Days and support from the city administration.',
   'Пресконференція: Миколаїв отримав право провести міжнародний «Велофорум-2017». Роланд Байрозян пояснює, чому – велоконцепція, Urban Days і підтримка міської влади.'), []),
 ('urban-days-2017', '03.01.2017', NP, 'uk', False, _t(
   'Jahresbilanz der „Mykolaiv Urban Days“: Zum Stadttag organisierten die Entwicklungsagentur und „Alter-Sport“ eine der größten Fahrradparaden Mykolajiws mit rund 1.000 Teilnehmenden.',
   'Annual review of “Mykolaiv Urban Days”: on City Day the development agency and Alter-Sport organised one of Mykolaiv’s biggest bike parades with about 1,000 riders.',
   'Підсумки року Mykolaiv Urban Days: до Дня міста Агенція розвитку разом з «Альтер-Спортом» провели один із найбільших велопарадів Миколаєва – близько 1000 учасників.'), []),
 ('mykoleso-2017', '07.05.2017', NP, 'ru', False, _t(
   'Fahrradfestival „MyKoleso“ mit rund 2.000 Teilnehmenden; die Aktivisten Denys Moljaka und Roland Bajrosjan sprechen über die Zukunft der Fahrradbewegung.',
   'Bike festival “MyKoleso” with about 2,000 participants; activists Denys Moliaka and Roland Bairozian talk about the future of the cycling movement.',
   'Велофестиваль «МиКолесо» – близько 2000 учасників; активісти Денис Моляка й Роланд Байрозян розповіли про перспективи веломуху.'), []),
 ('veloden-2017', '27.05.2017', KOR + ' · NikLife', 'ru', False, _t(
   'Über 1.000 Radfahrer „fahren für ihre Rechte“; Roland Bajrosjan kündigt das Welo-Forum im Herbst an.',
   'More than 1,000 cyclists “ride for their rights”; Roland Bairozian announces the Velo Forum in autumn.',
   'Понад тисяча миколаївців «проїхалися за свої права»; Роланд Байрозян анонсує осінній Велофорум.'), []),
 ('velodorizhka-2017', '27.05.2017', 'НікВісті (nikvesti.com)', 'ru', False, _t(
   'TV-Beitrag: Die Zahl der Radfahrer wächst jedes Jahr, sagt Roland Bajrosjan; die Entwicklungsagentur hofft auf den ersten Radweg der Stadt.',
   'TV report: the number of cyclists grows every year, says Roland Bairozian; the development agency hopes for the city’s first cycle lane.',
   'Телесюжет: кількість велосипедистів щороку зростає, каже Роланд Байрозян; Агенція розвитку сподівається на першу велодоріжку міста.'), []),
 ('den-molodi-2017', '25.06.2017', 'Шипшина (shipovnik.ua)', 'ru', True, _t(
   'Tag der Jugend: Das Fest beginnt mit einer Fahrradtour von „Alter-Sport“ mit über hundert Teilnehmenden; Moderator ist BVB.',
   'Youth Day: the festival opens with an Alter-Sport bike ride of more than a hundred riders; BVB hosts.',
   'День молоді: свято починається з велопробігу «Альтер-Спорту» – понад сотня учасників; ведучий – BVB.'), []),
 ('active-2017', '26.07.2017', KOR, 'ru', False, _t(
   'Gewinner des Programms „Active Citizens“: Das Welo-Forum erhält die meisten Punkte; Roland Bajrosjan erwartet Experten aus ganz Europa.',
   'Winners of the “Active Citizens” programme: the Velo Forum gets the most points; Roland Bairozian expects experts from across Europe.',
   'Переможці проєкту Active Citizens: найбільше балів у Велофоруму; Роланд Байрозян чекає експертів з усієї Європи.'), []),
 ('veloforum-2017', '06.10.2017', 'НікВісті (nikvesti.com)', 'ru', False, _t(
   'Fotoreportage vom Start des „Welo-Forums“, der wichtigsten Fahrradveranstaltung der Ukraine, in Mykolajiw; Veranstalter Roland Bajrosjan.',
   'Photo report from the start of the “Velo Forum”, Ukraine’s main cycling event, in Mykolaiv; organiser Roland Bairozian.',
   'Фоторепортаж зі старту «Велофоруму» – головної велоподії України – у Миколаєві; організатор Роланд Байрозян.'),
   [('«Велофорум» – это прежде всего образовательно-коммуникативная площадка, которая призвана повысить квалификацию не только активистов, но и управленцев.', _t('Das Welo-Forum ist vor allem eine Bildungs- und Austauschplattform, die nicht nur Aktivisten, sondern auch Verwaltungsleute weiterbilden soll. (Roland Bajrosjan)', 'The Velo Forum is above all a platform for learning and exchange, meant to train not only activists but also administrators. (Roland Bairozian)', '«Велофорум» – це насамперед освітньо-комунікаційний майданчик, що має підвищити кваліфікацію не лише активістів, а й управлінців. (Роланд Байрозян)'))]),
 ('veloforum-boell-2017', '09.10.2017', 'Heinrich-Böll-Stiftung Ukraine (ua.boell.org)', 'uk', False, _t(
   'Bilanz des Welo-Forums: über 100 Teilnehmende aus 8 Ländern Europas; Mitveranstalter sind die Stadt Mykolajiw und „Alter-Sport“.',
   'Velo Forum review: more than 100 participants from 8 European countries; co-organisers are the city of Mykolaiv and Alter-Sport.',
   'Підсумки Велофоруму: понад 100 учасників із 8 країн Європи; співорганізатори – мерія Миколаєва та «Альтер-Спорт».'), []),
 ('film-2017', '02.11.2017', NP, 'ru', False, _t(
   'In Mykolajiw entstand ein Film über die Kraft des Fahrrads, die Stadt zu verändern; Roland Bajrosjan nennt Radfahrer „gebildete, vielseitige Menschen, die Werte vertreten“.',
   'A film is made in Mykolaiv about how the bicycle can change a city; Roland Bairozian calls cyclists “educated, well-rounded people who promote values”.',
   'У Миколаєві зняли фільм про те, як велосипед змінює місто; Роланд Байрозян називає велосипедистів «ерудованими й різнобічними людьми, які пропагують цінності».'), []),
 ('veloprobih-2019', '27.05.2019', NP, 'uk', False, _t(
   'Fahrradkorso mit rund 700 Teilnehmenden; die Stadt erinnert: Am Anfang stand „Alter-Sport“, später kam „Welorukh“ dazu.',
   'Bike ride with about 700 participants; the city recalls that it all started with Alter-Sport, later joined by “Velorukh”.',
   'Велопробіг – близько 700 учасників; у міськраді нагадують: біля витоків – «Альтер-Спорт», згодом приєднався «Велорух».'),
   [('Справа не у кількості учасників, а в тому, що кожного року серед них є якнайменше 80-100 новачків, які залюбки приєднуються.', _t('Es geht nicht um die Zahl, sondern darum, dass jedes Jahr mindestens 80–100 Neue mitfahren. (Roland Bajrosjan)', 'It is not about numbers but that every year at least 80–100 newcomers happily join. (Roland Bairozian)', None))]),
 ('veloden-2019', '29.05.2019', 'Вечірній Миколаїв (vn.mk.ua)', 'ru', False, _t(
   'Welodenj auf dem Sobornaja-Platz: seit 2010, ins Leben gerufen von „Alter-Sport“.',
   'Velo Day on Soborna Square: held since 2010, started by Alter-Sport.',
   'Велодень на Соборній площі: проводиться з 2010 року, біля витоків – «Альтер-Спорт».'),
   [('Начиналось все с 15-20 человек — междусобойчик у велосипедистов. А теперь бывают случаи, когда собирается больше 1200 участников.', _t('Angefangen hat es mit 15–20 Leuten, ein Treffen unter Radfahrern. Heute kommen manchmal über 1.200. (Roland Bajrosjan)', 'It started with 15–20 people, a get-together of cyclists. Now there are sometimes more than 1,200. (Roland Bairozian)', 'Починалося все з 15–20 людей – зустріч велосипедистів. А тепер буває, що збирається понад 1200 учасників. (Роланд Байрозян)'))]),
 ('skate-svidok-2019', '17.09.2019', 'Свідок (svidok.info)', 'ru', True, _t(
   'Graffiti „Wir sind hier, um zu kreieren“ am künftigen Skatepark bei der Sportschule „Nadeschda“; Dank an Roland Bajrosjan für die Organisation und an Viacheslav Balabaiev für das Graffiti.',
   'Graffiti “We are here to create” at the future skate park next to the Nadezhda sports school; thanks to Roland Bairozian for organising and Viacheslav Balabaiev for the graffiti.',
   'Графіті «Ми тут, щоб творити» на місці майбутнього скейт-парку біля «Надії»; подяка Роланду Байрозяну за організацію та В’ячеславу Балабаєву за графіті.'), []),
 ('skate-vn-2019', '24.09.2019', 'Вечірній Миколаїв (vn.mk.ua)', 'ru', True, _t(
   'Skatepark statt Brachfläche: Organisator Roland Bajrosjan, Künstler Viacheslav Balabaiev.',
   'Skate park instead of a wasteland: organiser Roland Bairozian, artist Viacheslav Balabaiev.',
   'Скейт-парк замість пустиря: організатор Роланд Байрозян, художник В’ячеслав Балабаєв.'), []),
 ('retro-2026', '11.09.2026', KOR, 'uk', False, _t(
   'Rückblick „Was war am 11. September in Korabelnyj“: 2013 traf die Skatepark-Ausrüstung ein, das Projekt setzte „Alter-Sport“ mit einem Zuschuss um.',
   'Look-back “What happened on 11 September in Korabelnyi”: in 2013 the skate-park equipment arrived – a project realised by Alter-Sport with a grant.',
   'Ретроспектива «Чим запам’яталося 11 вересня у Корабельному»: 2013 року привезли обладнання скейт-парку – проєкт «Альтер-Спорту», реалізований за грант.'), []),
]

SRC = {
"skatepark-2012": [
"https://korabelov.info/ru/2012/09/222541/molod-zaproshuyut-na-vidkrittya-skeyt-parku/",
"Молодь запрошують на відкриття скейт-парку, працюватимуть безкоштовні секції"
],
"gurt-2013": [
"https://gurt.org.ua/interviews/17320/",
"\"Альтер-Спорт\": найбільша нестача відчувається завжди у справжніх лідерах та коштах"
],
"velodorozhky-2013": [
"https://korabelov.info/ru/2013/03/2139/velodorozhki-v-nikolaeve/",
"Велодорожки в Николаеве?"
],
"shkola29-2013": [
"https://korabelov.info/ru/2013/05/2533/ranok-uchniv/",
"Ранок учнів ЗОШ №29 буде починатись спортивно і корисно"
],
"olymp-2013": [
"http://www.gweek.com.ua/2013/05/blog-post_25.html",
"Велопоток на Адмиральской"
],
"vodoley-2013": [
"https://korabelov.info/ru/2013/06/223355/nikolaevskie-chinovniki-postroyat-novyj-skejt-park-na-meste-byvshego-kladbishcha/",
"Новый спорткомплекс построят возле \"Водолея\", на месте бывшего кладбища"
],
"dobro-2013": [
"https://korabelov.info/ru/2013/08/3275/davajte-delat-dobro-v-subbotu-soberem-detej-iz-nikolaevskogo-internata-2-v-shkolu/",
"«Давайте делать добро»: соберем в школу детей из интерната №2"
],
"kapsula-2013": [
"https://korabelov.info/ru/2013/09/223578/poslanie-potomkam-torzhestvenno-zakopali-pod-parkom-sporta-v-korabelnom-video/",
"Послание потомкам торжественно закопали под Парком спорта в Корабельном (видео)"
],
"rukavytsi-2013": [
"https://korabelov.info/ru/2013/09/3358/rukovodstvo-oblasti-okonfuzilos-v-korabelnom/",
"Вслед за Азаровым, оконфузились первые лица области на празднике в Корабельном"
],
"montazh-2013": [
"https://korabelov.info/ru/2013/09/223594/deti-ne-v-silakh-dozhdatsya-okonchatelnoj-ustanovki-skejt-parka-v-korabelnom/",
"Дети не в силах дождаться окончательной установки скейт-парка в Корабельном"
],
"nedelya-dobra-2013": [
"https://korabelov.info/ru/2013/10/3636/v-nikolaeve-shestoj-raz-startovala-osennyaya-nedelya-dobra/",
"Купи свидание или просто сдай деньги! Осенняя неделя добра"
],
"sessiya-2013": [
"https://korabelov.info/ru/2013/10/3666/vyezdnoe-zasedanie-sessii-v-korabelnom-deputaty-uznali-kuda-delsya-million/",
"В Корабельном депутатам горсовета показали, куда делся миллион"
],
"isakov-2013": [
"https://korabelov.info/ru/2013/10/223746/tajny-gorodka-sporta-korabelnyj/",
"\"Отписка вызывает еще больше сомнений\", - Исаков о спортгородке «Корабельный»"
],
"spartakiada-2013": [
"https://korabelov.info/ru/2013/10/3718/spartakiada-doshkolyat-korabelnogo/",
"ВИДЕО: Живчики, Смайлики, Капитошки и другие дошколята Корабельного открыли Спартакиаду"
],
"vidkryttia-2013": [
"https://korabelov.info/ru/2013/11/223779/video-pod-fanfary-i-zolotoj-dozhd-torzhestvenno-otkryt-park-sporta-korabelnyj/",
"ВИДЕО: Под фанфары и \"золотой дождь\" торжественно открыт парк спорта \"Корабельный\""
],
"zaryadka-2014": [
"https://korabelov.info/ru/2014/04/4989/na-zaryadku-stanovis/",
"На зарядку становись!"
],
"z-ditmy-anons-2014": [
"https://korabelov.info/ru/2014/05/5654/vmeste-s-detmi-v-korabelnom-rajone/",
"«Вместе с детьми» в Корабельном районе"
],
"veloden-2014": [
"https://korabelov.info/ru/2014/05/5696/veloden-v-nikolaeve-okolo-600-velosipedistov-edinoj-kolonnoj-proekhalis-po-tsentru-goroda/",
"Велодень в Николаеве: около 600 велосипедистов единой колонной проехались по центру города"
],
"z-ditmy-2014": [
"https://korabelov.info/ru/2014/06/5787/prazdnik-vmeste-s-detmi-v-korabelnom-rajone-udalsya-na-slavu/",
"Праздник «Вместе с детьми» в Корабельном районе удался на славу!"
],
"kino-2014": [
"https://korabelov.info/ru/2014/06/5919/v-nikolaeve-projdet-nochnoj-pokaz-kinofestivalya-vidkrita-nich/",
"В Николаеве состоится кинофестиваль \"ВІДКРИТА НІЧ\""
],
"chempionat-2015": [
"https://nikvesti.com/news/sport/67245",
"Накануне Дня освобождения в Николаеве дали старт чемпионату Украины по велоспорту"
],
"formula-2015": [
"https://korabelov.info/ru/2015/05/225986/16-pobeditelej-konkursa-formula-budushchego-2015-poluchat-finansirovanie/",
"В Корабельном появятся велопарковки и кинотеатр под открытым небом. Выбраны победители конкурса \"Формула будущего-2015\""
],
"veloden-2015": [
"https://korabelov.info/ru/2015/05/9086/veloden-v-nikolaeve/",
"Велодень в Николаеве"
],
"zmagannia-2015": [
"https://korabelov.info/ru/2015/06/9146/sportivnye-sorevnovaniya-proshli-na-skejt-ploshchadke-v-korabelnom-rajone-g-nikolaeva/",
"Спортивные соревнования прошли на скейт-площадке в Корабельном районе г. Николаева"
],
"gonka-2016": [
"https://korabelov.info/ru/2016/03/3140/gonka-pobedy-velosipedisty-nakatali-800/",
"\"Гонка Победы\": велосипедисты накатали 800 км по николаевскому бездорожью"
],
"veloden-2016": [
"https://www.nikpravda.com.ua/zavtra-v-nikolaeve-projdet-vseukrainskij-veloden/",
"Завтра в Николаеве пройдет Всеукраинский Велодень"
],
"urban-days-2016": [
"https://korabelov.info/ru/2016/08/15637/iz-byudzheta-nikolaeva-profinansiruyut-18/",
"Из бюджета Николаева профинансируют еще 18 соцпроектов. В Корабельном проведут турнир по мини-футболу и Веселые старты"
],
"veloparad-2016": [
"https://www.nikpravda.com.ua/mikolayivtsiv-zaproshuyut-doluchitisya-do-masshtabnogo-veloparadu/",
"Миколаївців запрошують долучитися до масштабного велопараду"
],
"kino-2016": [
"https://www.nikpravda.com.ua/nikolaev-primet-uchastie-v-festivale-korotkometrazhek/",
"Николаев примет участие в фестивале короткометражек"
],
"pryberannia-2016": [
"https://www.nikpravda.com.ua/nikolaevtsev-zovut-na-uborku-skejtparka-v-park-pobedy/",
"Николаевцев зовут на уборку скейтпарка в парке “Победы”"
],
"pryberannia2-2016": [
"https://www.nikpravda.com.ua/nikolaevtsy-organizovali-uborku-v-samom-bolshom-gorodskom-parke-i-ochistili-aleyu-olimpijskoj-slavy-foto/",
"Николаевцы организовали уборку в самом большом городском парке и очистили алею олимпийской славы (ФОТО)"
],
"veloforum-perem-2016": [
"https://www.nikpravda.com.ua/senkevich-poobeshhal-razvivat-veloinfrastrukturu/",
"Сенкевич пообещал развивать велоинфраструктуру"
],
"urban-days-2017": [
"https://www.nikpravda.com.ua/mykolaiv-urban-days-pidviv-pidsumki-minulogo-roku/",
"“Mykolaiv Urban Days” підвів підсумки минулого року"
],
"mykoleso-2017": [
"https://www.nikpravda.com.ua/masshtabnyj-velofestival-mikoleso-sobral-v-nikolaeve-okolo-2-tysyach-uchastnikov/",
"Масштабный велофестиваль «МиКолесо» собрал в Николаеве около 2 тысяч участников"
],
"veloden-2017": [
"https://korabelov.info/ru/2017/05/44751/bolee-tysyachi-nikolaevcev-prokatili/",
"Более тысячи николаевцев «прокатились за свои права» на традиционном ВелоДне"
],
"velodorizhka-2017": [
"https://nikvesti.com/news/sport/109004",
"В Агентстве развития надеются, что проект первой велодорожки в Николаеве может появиться к концу года "
],
"den-molodi-2017": [
"https://shipovnik.ua/longrid/16390",
"Граффити, BMX и брейк-данс: николаевцы «отожгли» на Дне молодежи (Фоторепортаж)"
],
"active-2017": [
"https://korabelov.info/ru/2017/07/51281/31-iyulya-startuet-frendsfestival-kotoryy-proydet-v/",
"В Николаеве определят лучшую женщину-водителя, соберутся на велофорум, а в Корабельном районе пройдет FrendsFestival"
],
"veloforum-2017": [
"https://nikvesti.com/news/photoreportage/117136",
"Самое представительное мероприятие велосипедистов Украины \"Велофорум\" стартовало в Николаеве"
],
"veloforum-boell-2017": [
"https://ua.boell.org/uk/2017/10/09/veloforum-v-ukrayini-zibrav-ponad-100-uchasnikiv-i-uchasnic-z-8-krayin-ievropi",
"Велофорум в Україні зібрав понад 100 учасників і учасниць з 8 країн Європи | Heinrich Böll Stiftung | Київ – Україна"
],
"film-2017": [
"https://www.nikpravda.com.ua/velosipedizatsiya-neizbezhna-v-nikolaeve-snyali-film-o-tom-kak-velosiped-sposoben-izmenit-gorod/",
"«Велосипедизация неизбежна»: в Николаеве сняли фильм о том, как велосипед способен изменить город"
],
"veloprobih-2019": [
"https://www.nikpravda.com.ua/u-mykolayevi-vidbuvsya-veloprobig/",
"У Миколаєві відбувся велопробіг"
],
"veloden-2019": [
"https://vn.mk.ua/ru/veloden-na-sobornoj-ploshhadi/",
"Велодень на Соборной площади"
],
"skate-svidok-2019": [
"https://svidok.info/ru/news/33371",
"В Николаеве на месте скейт-парка появилось яркое граффити"
],
"skate-vn-2019": [
"https://vn.mk.ua/ru/skejt-park-vmesto-pustyrya/",
"Скейт-парк вместо пустыря"
],
"retro-2026": [
"https://korabelov.info/2026/09/614005/sukhyj-dok-okeanu-skejt-park-i-zahyblyj-vypusknyk-litseiu-chym-zapam-iatalosia-11-veresnia-u-korabelnomu/",
"Сухий док \"Океану\", скейт-парк і загиблий випускник ліцею: чим запам'яталося 11 вересня у Корабельному"
]
}

ITEMS = [dict(id=k, k=k, date=d, outlet=o, lang=l, bvb=b, status='ok', sum=s, quotes=q, url=SRC[k][0], head=SRC[k][1].strip(), imgs=['alt-' + k] if k in IMGS else []) for k, d, o, l, b, s, q in ROWS]

