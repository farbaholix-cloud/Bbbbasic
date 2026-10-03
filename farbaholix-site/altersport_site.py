"""Standalone tribute site for the Mykolaiv youth NGO "Alter-Sport" and its head Roland Bairozian.
Generates ../altersport/{index.html (uk), en/index.html, de/index.html}; served by GitHub Pages of this repo:
https://farbaholix-cloud.github.io/Bbbbasic/altersport/  — no link to farbaholix.de.
Facts only from the press reports collected in altersport.py (sources listed on the page)."""
import html, os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'altersport')
e = lambda s: html.escape(s, quote=True)

T = {
 'uk': dict(
  lang='uk', title='«Альтер-Спорт» · Миколаїв · Роланд Байрозян',
  desc='Історія миколаївської молодіжної організації «Альтер-Спорт» і її незмінного лідера Роланда Байрозяна: скейт-парки, BMX, Велодень, Велофорум.',
  kicker='Миколаїв · з 2004 року', h1='«Альтер-Спорт»', sub='Двадцять років тому кілька хлопців на BMX вирішили, що місту потрібен скейт-парк. Відтоді в Миколаєві з’явилися скейт-парки, Велодень на тисячу людей і міжнародний Велофорум. На чолі цієї історії весь час – одна людина: Роланд Байрозян.',
  scroll='Гортайте вниз',
  rol_k='Людина, з якої все почалося', rol_h='Роланд Байрозян',
  rol_p=['У 2001 році Роланд захопився BMX – трюковим велосипедом. За кілька років таких, як він, у Миколаєві стало багато, і з’явилося просте питання: хто домовлятиметься з містом про скейт-парк? У травні 2004 року Роланд разом із друзями зареєстрував громадську організацію «Альтер-Спорт» і став її головою.',
          'Відтоді він – той, хто пише заявки на гранти, ходить по кабінетах, виводить сотні велосипедистів на вулиці й прибирає скейт-парк разом із волонтерами. Про нього кажуть: «Не скромничай, люди мають знати своїх героїв в обличчя».'],
  quotes=[('Найбільша нестача відчувається завжди у справжніх лідерах та коштах.', 'Роланд Байрозян, 2013'),
          ('Починалося все з 15–20 людей. А тепер буває, що збирається понад 1200 учасників – рух росте й розвивається.', 'Роланд Байрозян, 2019'),
          ('Справа не в кількості учасників, а в тому, що щороку серед них щонайменше 80–100 новачків.', 'Роланд Байрозян, 2019')],
  nums_h='«Альтер-Спорт» у цифрах',
  nums=[('2004', 'рік реєстрації'), ('17–18', 'видів спорту – від BMX до хокею на роликах'), ('120', 'членів у 2013 році'), ('2', 'скейт-парки, збудовані за гранти'), ('1200+', 'учасників на Велодні'), ('8', 'країн на Велофорумі-2017')],
  hist_h='Історія', hist=[
   ('2001–2004', 'Народження', 'BMX, скейти, ролики – у Миколаєві росте покоління екстремалів. У травні 2004 року вони отримують голос: громадську організацію «Альтер-Спорт».', None),
   ('2010', 'Перший Велодень', 'Починається традиція, що стане наймасовішою велоакцією міста. Того ж року вперше проходить крос-кантрі «Гонка Перемоги» в парку Перемоги.', 'gonka-2016'),
   ('2012', 'Перший скейт-парк міста', 'Перемога в конкурсах «Територія РУСАЛу» та «Серце міста» – і 22 вересня в парку Перемоги відкривається перший скейт-парк Миколаєва з безкоштовними секціями BMX, роликів, скейтбордингу, тріалу й флетленду.', 'bmx-1'),
   ('2012–2016', 'Кіно під відкритим небом', 'Разом із кіноклубом RealityShiftCinema – щорічний Манхеттенський фестиваль короткометражок і «Відкрита ніч» у Миколаєві.', None),
   ('2013', 'Парк спорту «Корабельний»', 'Другий грант РУСАЛу – 300 тисяч гривень. За 30–40 днів біля басейну «Водолій» виростає спортмістечко зі скейт-парком і воркаутом. Капсулу з посланням «Миколаєву майбутнього» закладає активіст організації В’ячеслав Балабаєв (BVB). 4 листопада – урочисте відкриття.', 'bmx-3'),
   ('2013–2015', 'Велосипед – це транспорт', 'Велодорожки, велопарковки, перша шкільна велостоянка, велоконцепція міста. Велодень 2014-го – 600 учасників, 2017-го – понад тисячу.', 'olymp-2013'),
   ('2014–2015', 'Шоу, змагання, свята', 'Екстрим-шоу та змагання у скейт-парку, показові виступи на чемпіонаті України з велоспорту, на святах для дітей і акціях здоров’я; проєкт «Літній сезон у скейт-парку».', 'chempionat-2015'),
   ('2016', 'Місто, зручне для людей', 'Разом з Агенцією розвитку Миколаєва – тиждень міського розвитку Mykolaiv Urban Days і велопарад до Дня міста: близько тисячі велосипедистів.', 'urban-days-2016'),
   ('2017', 'Велофорум у Миколаєві', 'Головна велоподія України приїжджає до Миколаєва: понад 100 учасників із 8 країн Європи. «Альтер-Спорт» – співорганізатор.', 'veloden-2017'),
   ('2019', 'Ми тут, щоб творити', 'Велодень збирає сотні людей, серед них щороку десятки новачків. А на пустирі біля спортшколи «Надія» Роланд починає новий скейт-парк – з великим графіті «Мы здесь, чтобы творить».', 'veloden-2019')],
  gal_h='Як це виглядає', gal_note='Фото з публікацій миколаївських медіа (Шипшина, NikLife, «Вечірній Миколаїв», Свідок, НікВісті).',
  call_k='Замість епілогу', call_h='Ми тут, щоб творити.',
  call_p=['Скейт-парки виростали на пустирях. Велодень почався з п’ятнадцяти людей. Усе, що зробив «Альтер-Спорт», колись здавалося неможливим – доки хтось не взявся.',
          'Тож тримаймо оптимізм. Сідаймо на велосипед, виходьмо на майданчик, підтримуймо одне одного й новачків. Добра енергія, як і швидкість, накопичується в русі. Миколаїв – місто на хвилі, і ця хвиля ще попереду.'],
  call_btn='Дякуємо, Роланде! 🚲',
  src_h='Джерела', foot='Сторінку зроблено з повагою та вдячністю другом організації – В’ячеславом «BVB» Балабаєвим. Усі факти – з публікацій ЗМІ, перелік нижче.',
  other='Мова'),
 'en': dict(
  lang='en', title='“Alter-Sport” · Mykolaiv · Roland Bairozian',
  desc='The story of the Mykolaiv youth organisation “Alter-Sport” and its leader Roland Bairozian: skate parks, BMX, Velo Day, Velo Forum.',
  kicker='Mykolaiv · since 2004', h1='“Alter-Sport”', sub='Twenty years ago a few guys on BMX bikes decided their city needed a skate park. Since then Mykolaiv has gained skate parks, a Velo Day for a thousand riders and an international Velo Forum. One person has led this story all along: Roland Bairozian.',
  scroll='Scroll down',
  rol_k='The man it all started with', rol_h='Roland Bairozian',
  rol_p=['In 2001 Roland got hooked on BMX – the trick bike. Within a few years Mykolaiv had plenty of riders like him, and a simple question: who would talk the city into building a skate park? In May 2004 Roland and his friends registered the NGO “Alter-Sport”, and he became its head.',
         'Ever since, he has been the one writing grant applications, knocking on office doors, leading hundreds of cyclists onto the streets and cleaning up the skate park with volunteers. As one official put it on stage: “Don’t be modest – people should know their heroes by sight.”'],
  quotes=[('What we always lack most is real leaders and money.', 'Roland Bairozian, 2013'),
          ('It started with 15–20 people. Now there are sometimes more than 1,200 – the movement keeps growing.', 'Roland Bairozian, 2019'),
          ('It’s not about the numbers – it’s that every year at least 80–100 newcomers join us.', 'Roland Bairozian, 2019')],
  nums_h='“Alter-Sport” in numbers',
  nums=[('2004', 'year of registration'), ('17–18', 'disciplines – from BMX to roller hockey'), ('120', 'members in 2013'), ('2', 'skate parks built with grants'), ('1,200+', 'riders on Velo Day'), ('8', 'countries at Velo Forum 2017')],
  hist_h='History', hist=[
   ('2001–2004', 'The beginning', 'BMX, skateboards, inline skates – a generation of extreme-sport fans grows up in Mykolaiv. In May 2004 they get a voice: the NGO “Alter-Sport”.', None),
   ('2010', 'The first Velo Day', 'A tradition begins that will become the city’s biggest cycling event. The same year sees the first cross-country race “Gonka Pobedy” in Peremohy Park.', 'gonka-2016'),
   ('2012', 'The city’s first skate park', 'Wins in the “Territory of RUSAL” and “Heart of the City” competitions – and on 22 September Mykolaiv’s first skate park opens in Peremohy Park, with free classes in BMX, inline, skateboarding, trial and flatland.', 'bmx-1'),
   ('2012–2016', 'Cinema under the sky', 'With the film club RealityShiftCinema: the annual Manhattan Short Film Festival and the “Open Night” in Mykolaiv.', None),
   ('2013', 'Korabelnyi sports park', 'A second RUSAL grant – 300,000 hryvnias. In 30–40 days a sports ground with skate park and workout area rises next to the Vodoliy pool. The time capsule “To the Mykolaiv of the future” is laid by activist Viacheslav Balabaiev (BVB). Grand opening on 4 November.', 'bmx-3'),
   ('2013–2015', 'The bicycle is transport', 'Cycle lanes, bike racks, the first school bike stand, the city’s cycling concept. Velo Day 2014 – 600 riders; 2017 – more than a thousand.', 'olymp-2013'),
   ('2014–2015', 'Shows, contests, festivals', 'Extreme-sport shows and contests at the skate park, demonstrations at the Ukrainian cycling championship, children’s festivals and health events; the project “Summer season at the skate park”.', 'chempionat-2015'),
   ('2016', 'A city made for people', 'With the Mykolaiv Development Agency: the urban development week “Mykolaiv Urban Days” and a City Day bike parade with about a thousand riders.', 'urban-days-2016'),
   ('2017', 'Velo Forum in Mykolaiv', 'Ukraine’s main cycling event comes to Mykolaiv: more than 100 participants from 8 European countries. Alter-Sport is a co-organiser.', 'veloden-2017'),
   ('2019', 'We are here to create', 'Velo Day draws hundreds of people, with dozens of newcomers every year. And on a wasteland next to the Nadezhda sports school Roland starts a new skate park – with a big graffiti: “We are here to create”.', 'veloden-2019')],
  gal_h='What it looks like', gal_note='Photos from Mykolaiv media reports (Shypshyna, NikLife, Vechirnii Mykolaiv, Svidok, NikVesti).',
  call_k='Instead of an epilogue', call_h='We are here to create.',
  call_p=['Skate parks grew on wastelands. Velo Day started with fifteen people. Everything Alter-Sport achieved once looked impossible – until someone simply started.',
          'So let’s keep our optimism. Get on the bike, go out to the park, support each other and every newcomer. Good energy, like speed, builds up in motion. Mykolaiv is a city on the wave – and the best part of that wave is still ahead.'],
  call_btn='Thank you, Roland! 🚲',
  src_h='Sources', foot='Made with respect and gratitude by a friend of the organisation – Viacheslav “BVB” Balabaiev. All facts are taken from media reports, listed below.',
  other='Language'),
 'de': dict(
  lang='de', title='„Alter-Sport“ · Mykolajiw · Roland Bajrosjan',
  desc='Die Geschichte der Jugendorganisation „Alter-Sport“ aus Mykolajiw und ihres Leiters Roland Bajrosjan: Skateparks, BMX, Fahrradtag, Welo-Forum.',
  kicker='Mykolajiw · seit 2004', h1='„Alter-Sport“', sub='Vor zwanzig Jahren beschlossen ein paar Jungs auf BMX-Rädern, dass ihre Stadt einen Skatepark braucht. Seitdem hat Mykolajiw Skateparks, einen Fahrradtag mit tausend Menschen und ein internationales Welo-Forum bekommen. An der Spitze dieser Geschichte stand die ganze Zeit ein Mensch: Roland Bajrosjan.',
  scroll='Nach unten scrollen',
  rol_k='Der Mensch, mit dem alles begann', rol_h='Roland Bajrosjan',
  rol_p=['2001 entdeckte Roland das BMX – das Trickfahrrad. Ein paar Jahre später gab es in Mykolajiw viele wie ihn und eine einfache Frage: Wer verhandelt mit der Stadt über einen Skatepark? Im Mai 2004 gründete Roland mit Freunden die Organisation „Alter-Sport“ und wurde ihr Vorsitzender.',
         'Seitdem ist er derjenige, der Förderanträge schreibt, von Amt zu Amt geht, Hunderte Radfahrer auf die Straße bringt und mit Freiwilligen den Skatepark aufräumt. Ein Bezirkschef sagte einmal auf der Bühne: „Sei nicht so bescheiden – die Leute sollen ihre Helden kennen.“'],
  quotes=[('Am meisten fehlt es immer an echten Führungspersönlichkeiten und an Geld.', 'Roland Bajrosjan, 2013'),
          ('Angefangen hat es mit 15–20 Leuten. Heute kommen manchmal über 1.200 – die Bewegung wächst.', 'Roland Bajrosjan, 2019'),
          ('Es geht nicht um die Zahl, sondern darum, dass jedes Jahr mindestens 80–100 Neue dazukommen.', 'Roland Bajrosjan, 2019')],
  nums_h='„Alter-Sport“ in Zahlen',
  nums=[('2004', 'Jahr der Gründung'), ('17–18', 'Disziplinen – von BMX bis Rollhockey'), ('120', 'Mitglieder im Jahr 2013'), ('2', 'Skateparks aus Fördermitteln'), ('1.200+', 'Teilnehmende am Fahrradtag'), ('8', 'Länder beim Welo-Forum 2017')],
  hist_h='Geschichte', hist=[
   ('2001–2004', 'Der Anfang', 'BMX, Skateboards, Inliner – in Mykolajiw wächst eine Generation von Extremsportlern heran. Im Mai 2004 bekommt sie eine Stimme: die Organisation „Alter-Sport“.', None),
   ('2010', 'Der erste Fahrradtag', 'Eine Tradition beginnt, die zur größten Fahrradaktion der Stadt wird. Im selben Jahr findet zum ersten Mal das Cross-Country-Rennen „Gonka Pobedy“ im Park Peremohy statt.', 'gonka-2016'),
   ('2012', 'Der erste Skatepark der Stadt', 'Siege in den Wettbewerben „Territorija RUSALa“ und „Herz der Stadt“ – und am 22. September eröffnet im Park Peremohy der erste Skatepark Mykolajiws, mit kostenlosen Kursen in BMX, Inline, Skateboard, Trial und Flatland.', 'bmx-1'),
   ('2012–2016', 'Kino unter freiem Himmel', 'Mit dem Filmklub RealityShiftCinema: jährlich das Manhattan-Kurzfilmfestival und die „Offene Nacht“ in Mykolajiw.', None),
   ('2013', 'Sportpark „Korabelnyj“', 'Ein zweiter RUSAL-Zuschuss – 300.000 Hrywnja. In 30–40 Tagen entsteht neben dem Schwimmbad „Wodolij“ ein Sportgelände mit Skatepark und Workout-Fläche. Die Zeitkapsel „An das Mykolajiw der Zukunft“ legt der Aktivist Viacheslav Balabaiev (BVB). Feierliche Eröffnung am 4. November.', 'bmx-3'),
   ('2013–2015', 'Das Fahrrad ist Verkehrsmittel', 'Radwege, Fahrradständer, der erste Schul-Fahrradständer, das Fahrradkonzept der Stadt. Fahrradtag 2014 – 600 Teilnehmende, 2017 – über tausend.', 'olymp-2013'),
   ('2014–2015', 'Shows, Wettbewerbe, Feste', 'Extremsport-Shows und Wettbewerbe im Skatepark, Auftritte bei der ukrainischen Radsportmeisterschaft, bei Kinderfesten und Gesundheitsaktionen; das Projekt „Sommersaison im Skatepark“.', 'chempionat-2015'),
   ('2016', 'Eine Stadt für Menschen', 'Mit der Agentur für Entwicklung Mykolajiws: die Stadtentwicklungswoche „Mykolaiv Urban Days“ und eine Fahrradparade zum Stadttag mit rund tausend Teilnehmenden.', 'urban-days-2016'),
   ('2017', 'Welo-Forum in Mykolajiw', 'Die wichtigste Fahrradveranstaltung der Ukraine kommt nach Mykolajiw: über 100 Teilnehmende aus 8 Ländern Europas. „Alter-Sport“ ist Mitveranstalter.', 'veloden-2017'),
   ('2019', 'Wir sind hier, um zu kreieren', 'Der Fahrradtag zieht Hunderte an, jedes Jahr Dutzende Neue. Und auf einer Brache bei der Sportschule „Nadeschda“ beginnt Roland einen neuen Skatepark – mit einem großen Graffiti: „Wir sind hier, um zu kreieren“.', 'veloden-2019')],
  gal_h='So sieht es aus', gal_note='Fotos aus Berichten der Medien in Mykolajiw (Schypschyna, NikLife, Wetschirnij Mykolajiw, Swidok, NikWisti).',
  call_k='Statt eines Nachworts', call_h='Wir sind hier, um zu kreieren.',
  call_p=['Skateparks wuchsen auf Brachflächen. Der Fahrradtag begann mit fünfzehn Leuten. Alles, was „Alter-Sport“ geschafft hat, schien einmal unmöglich – bis jemand einfach angefangen hat.',
          'Also bewahren wir uns den Optimismus. Aufs Rad, raus in den Park, füreinander und für alle Neuen da sein. Gute Energie entsteht – wie Tempo – in Bewegung. Mykolajiw ist eine Stadt auf der Welle, und der beste Teil dieser Welle liegt noch vor uns.'],
  call_btn='Danke, Roland! 🚲',
  src_h='Quellen', foot='Mit Respekt und Dankbarkeit gestaltet von einem Freund der Organisation – Viacheslav „BVB“ Balabaiev. Alle Fakten stammen aus Medienberichten, siehe unten.',
  other='Sprache'),
}

SOURCES = [
 ('ГУРТ, 13.03.2013', 'https://gurt.org.ua/interviews/17320/'),
 ('Korabelov.info, 20.09.2012', 'https://korabelov.info/ru/2012/09/222541/molod-zaproshuyut-na-vidkrittya-skeyt-parku/'),
 ('Korabelov.info, 04.11.2013', 'https://korabelov.info/ru/2013/11/223779/video-pod-fanfary-i-zolotoj-dozhd-torzhestvenno-otkryt-park-sporta-korabelnyj/'),
 ('Korabelov.info, 06.09.2013', 'https://korabelov.info/ru/2013/09/223578/poslanie-potomkam-torzhestvenno-zakopali-pod-parkom-sporta-v-korabelnom-video/'),
 ('Korabelov.info, 31.05.2014', 'https://korabelov.info/ru/2014/05/5696/veloden-v-nikolaeve-okolo-600-velosipedistov-edinoj-kolonnoj-proekhalis-po-tsentru-goroda/'),
 ('Korabelov.info, 14.05.2015', 'https://korabelov.info/ru/2015/05/225986/16-pobeditelej-konkursa-formula-budushchego-2015-poluchat-finansirovanie/'),
 ('Korabelov.info / NikLife, 28.03.2016', 'https://korabelov.info/ru/2016/03/3140/gonka-pobedy-velosipedisty-nakatali-800/'),
 ('Миколаївська правда, 19.09.2016', 'https://www.nikpravda.com.ua/nikolaev-primet-uchastie-v-festivale-korotkometrazhek/'),
 ('Миколаївська правда, 03.01.2017', 'https://www.nikpravda.com.ua/mykolaiv-urban-days-pidviv-pidsumki-minulogo-roku/'),
 ('Korabelov.info, 27.05.2017', 'https://korabelov.info/ru/2017/05/44751/bolee-tysyachi-nikolaevcev-prokatili/'),
 ('НікВісті, 06.10.2017', 'https://nikvesti.com/news/photoreportage/117136'),
 ('Heinrich-Böll-Stiftung, 09.10.2017', 'https://ua.boell.org/uk/2017/10/09/veloforum-v-ukrayini-zibrav-ponad-100-uchasnikiv-i-uchasnic-z-8-krayin-ievropi'),
 ('Шипшина, 25.06.2017', 'https://shipovnik.ua/longrid/16390'),
 ('Миколаївська правда, 27.05.2019', 'https://www.nikpravda.com.ua/u-mykolayevi-vidbuvsya-veloprobig/'),
 ('Вечірній Миколаїв, 29.05.2019', 'https://vn.mk.ua/ru/veloden-na-sobornoj-ploshhadi/'),
 ('Свідок, 17.09.2019', 'https://svidok.info/ru/news/33371'),
]
GAL = ['bmx-2', 'bmx-4', 'parkour', 'gonka-2016', 'veloden-2019', 'cans']
PATHS = {'uk': '', 'en': 'en/', 'de': 'de/'}

CSS = r'''
:root{--bg:#0e1116;--ink:#f4f1ea;--mut:#a9b0bb;--acc:#ff6a2b;--acc2:#2bd4c0;--card:#171b22;--line:#262c36}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%;scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.6 "Inter",system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
img{max-width:100%;display:block}a{color:var(--acc2)}
.wrap{max-width:1080px;margin:0 auto;padding:0 20px}
.langs{position:fixed;top:14px;right:14px;z-index:9;display:flex;gap:4px;background:rgba(0,0,0,.45);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);border-radius:999px;padding:4px}
.langs a{color:#fff;text-decoration:none;font-weight:800;font-size:.8rem;padding:6px 10px;border-radius:999px}.langs a.on{background:var(--acc);color:#140b06}
.hero{position:relative;min-height:100svh;display:flex;align-items:flex-end;overflow:hidden}
.hero img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;object-position:60% 30%;transform:scale(1.04);animation:kb 18s ease-out forwards}
@keyframes kb{to{transform:scale(1)}}
.hero:after{content:"";position:absolute;inset:0;background:linear-gradient(180deg,rgba(14,17,22,.15) 0%,rgba(14,17,22,.35) 45%,rgba(14,17,22,.96) 100%)}
.hero .wrap{position:relative;z-index:2;padding-bottom:9vh}
.kick{display:inline-block;font-weight:800;letter-spacing:.14em;text-transform:uppercase;font-size:.78rem;color:var(--acc);margin:0 0 10px}
h1{font-size:clamp(3rem,11vw,7.5rem);line-height:.95;margin:0 0 18px;letter-spacing:-.02em;font-weight:900}
.sub{max-width:720px;font-size:clamp(1.05rem,2.2vw,1.3rem);color:#e6e2da;margin:0}
.scroll{margin-top:26px;font-size:.8rem;color:var(--mut);letter-spacing:.1em;text-transform:uppercase}
section{padding:80px 0}h2{font-size:clamp(2rem,5vw,3.2rem);line-height:1.05;margin:0 0 24px;font-weight:900}
.rol{display:grid;gap:36px}@media(min-width:860px){.rol{grid-template-columns:1.1fr .9fr;align-items:start}}
.rol p{color:#dcd8d0}
.q{margin:0 0 14px;padding:20px 22px;background:var(--card);border:1px solid var(--line);border-left:4px solid var(--acc);border-radius:16px}
.q p{margin:0;font-size:1.12rem;font-weight:700;font-style:italic}.q span{display:block;margin-top:8px;color:var(--mut);font-size:.85rem}
.nums{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}@media(min-width:760px){.nums{grid-template-columns:repeat(3,1fr)}}
.num{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:22px}.num b{display:block;font-size:clamp(2rem,6vw,3rem);line-height:1;color:var(--acc);font-weight:900}.num span{color:var(--mut);font-size:.92rem}
.tl{position:relative;display:grid;gap:22px}.tl:before{content:"";position:absolute;left:11px;top:6px;bottom:6px;width:2px;background:linear-gradient(var(--acc),var(--acc2))}
.st{position:relative;padding-left:40px}.st:before{content:"";position:absolute;left:4px;top:8px;width:16px;height:16px;border-radius:50%;background:var(--bg);border:3px solid var(--acc)}
.st .y{font-weight:900;color:var(--acc2);letter-spacing:.04em}.st h3{margin:2px 0 6px;font-size:1.35rem}.st p{margin:0;color:#d6d2ca}
.st img{margin-top:14px;border-radius:14px;width:100%;max-width:560px;aspect-ratio:16/10;object-fit:cover}
.gal{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}@media(min-width:760px){.gal{grid-template-columns:repeat(3,1fr)}}
.gal img{width:100%;aspect-ratio:4/3;object-fit:cover;border-radius:12px}.note{color:var(--mut);font-size:.85rem;margin-top:12px}
.call{position:relative;overflow:hidden;text-align:center;padding:110px 0;background:radial-gradient(circle at 50% 0%,rgba(255,106,43,.25),transparent 60%)}
.call img{border-radius:22px;margin:0 auto 34px;width:min(860px,100%);box-shadow:0 30px 80px rgba(0,0,0,.5)}
.call h2{font-size:clamp(2.4rem,8vw,5rem);background:linear-gradient(90deg,var(--acc),#ffd23f,var(--acc2));-webkit-background-clip:text;background-clip:text;color:transparent}
.call p{max-width:720px;margin:0 auto 16px;font-size:1.15rem;color:#e6e2da}
.btn{display:inline-block;margin-top:18px;padding:16px 28px;border-radius:999px;background:var(--acc);color:#140b06;font-weight:900;font-size:1.1rem;text-decoration:none;border:0;cursor:pointer;transition:transform .2s}
.btn:active{transform:scale(.96)}
.conf{position:fixed;width:10px;height:10px;border-radius:2px;pointer-events:none;z-index:20;animation:fall 1.6s ease-in forwards}
@keyframes fall{to{transform:translate(var(--x),110vh) rotate(720deg);opacity:.2}}
footer{padding:50px 0 70px;border-top:1px solid var(--line);color:var(--mut);font-size:.88rem}footer ul{padding-left:18px;columns:1}@media(min-width:760px){footer ul{columns:2}}
footer li{margin:0 0 6px;break-inside:avoid}
.rv{opacity:0;transform:translateY(24px);transition:opacity .8s,transform .8s}.rv.in{opacity:1;transform:none}
@media(prefers-reduced-motion:reduce){.hero img{animation:none}.rv{opacity:1;transform:none}}
'''

JS = r'''
const io=new IntersectionObserver(es=>es.forEach(x=>{if(x.isIntersecting){x.target.classList.add('in');io.unobserve(x.target)}}),{threshold:.12});
document.querySelectorAll('.rv').forEach(el=>io.observe(el));
document.getElementById('thx').addEventListener('click',()=>{const c=['#ff6a2b','#ffd23f','#2bd4c0','#7c5cff','#fff'];
 for(let i=0;i<70;i++){const d=document.createElement('i');d.className='conf';d.style.left=Math.random()*100+'vw';d.style.top='-10px';d.style.background=c[i%c.length];
 d.style.setProperty('--x',(Math.random()*200-100)+'px');d.style.animationDelay=Math.random()*.5+'s';document.body.appendChild(d);setTimeout(()=>d.remove(),2400)}});
'''

def page(k):
    t = T[k]; up = '../' if PATHS[k] else ''
    img = lambda n: up + 'img/%s.webp' % n
    langs = ''.join('<a href="%s%s"%s>%s</a>' % (up, PATHS[c], ' class="on"' if c == k else '', lbl) for c, lbl in (('uk', 'UA'), ('en', 'EN'), ('de', 'DE')))
    hist = ''.join('<div class="st rv"><div class="y">%s</div><h3>%s</h3><p>%s</p>%s</div>' % (e(y), e(h), e(p), ('<img loading="lazy" src="%s" alt="%s">' % (img(i), e(h))) if i else '') for y, h, p, i in t['hist'])
    return '''<!doctype html><html lang="%(lang)s"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>%(title)s</title><meta name="description" content="%(desc)s"><meta property="og:title" content="%(title)s"><meta property="og:description" content="%(desc)s"><meta property="og:image" content="%(hero)s">
<link rel="alternate" hreflang="uk" href="%(up)s./"><link rel="alternate" hreflang="en" href="%(up)sen/"><link rel="alternate" hreflang="de" href="%(up)sde/">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🚲</text></svg>">
<link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;700;800;900&display=swap" rel="stylesheet">
<style>%(css)s</style></head><body>
<nav class="langs" aria-label="%(other)s">%(langs)s</nav>
<header class="hero"><img src="%(hero)s" alt="BMX, Mykolaiv" fetchpriority="high"><div class="wrap"><p class="kick">%(kicker)s</p><h1>%(h1)s</h1><p class="sub">%(sub)s</p><p class="scroll">↓ %(scroll)s</p></div></header>
<main>
<section><div class="wrap rol"><div class="rv"><p class="kick">%(rol_k)s</p><h2>%(rol_h)s</h2>%(rol_p)s</div><div class="rv">%(quotes)s</div></div></section>
<section style="padding-top:0"><div class="wrap"><h2 class="rv">%(nums_h)s</h2><div class="nums">%(nums)s</div></div></section>
<section><div class="wrap"><h2 class="rv">%(hist_h)s</h2><div class="tl">%(hist)s</div></div></section>
<section style="padding-top:0"><div class="wrap"><h2 class="rv">%(gal_h)s</h2><div class="gal rv">%(gal)s</div><p class="note">%(gal_note)s</p></div></section>
<section class="call"><div class="wrap"><img class="rv" loading="lazy" src="%(mural)s" alt="%(call_h)s"><p class="kick">%(call_k)s</p><h2>%(call_h)s</h2>%(call_p)s<button class="btn" id="thx" type="button">%(call_btn)s</button></div></section>
</main>
<footer><div class="wrap"><p>%(foot)s</p><h3>%(src_h)s</h3><ul>%(src)s</ul></div></footer>
<script>%(js)s</script></body></html>''' % dict(
        {**t, **{x: e(t[x]) for x in ('title', 'desc', 'kicker', 'h1', 'sub', 'scroll', 'rol_k', 'rol_h', 'nums_h', 'hist_h', 'gal_h', 'gal_note', 'call_k', 'call_h', 'call_btn', 'foot', 'src_h', 'other')}}, up=up, css=CSS, js=JS, hero=img('hero'), mural=img('mural'), langs=langs, hist=hist,
        rol_p=''.join('<p>%s</p>' % e(p) for p in t['rol_p']),
        quotes=''.join('<blockquote class="q"><p>„%s“</p><span>— %s</span></blockquote>' % (e(q), e(a)) for q, a in t['quotes']),
        nums=''.join('<div class="num rv"><b>%s</b><span>%s</span></div>' % (e(n), e(l)) for n, l in t['nums']),
        gal=''.join('<img loading="lazy" src="%s" alt="Alter-Sport">' % img(g) for g in GAL),
        call_p=''.join('<p>%s</p>' % e(p) for p in t['call_p']),
        src=''.join('<li><a href="%s" target="_blank" rel="noopener">%s</a></li>' % (e(u), e(n)) for n, u in SOURCES))

if __name__ == '__main__':
    for k in T:
        d = os.path.join(OUT, PATHS[k]); os.makedirs(d, exist_ok=True)
        open(os.path.join(d, 'index.html'), 'w').write(page(k)); print(k, os.path.join(d, 'index.html'))
