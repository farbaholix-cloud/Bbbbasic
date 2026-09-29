# Portfolio lightbox: numbers from the alt-text table (alts.py / keep.json). Maik's own works and testimonial portraits are left out.
from alts import A

UK = {
 1: 'Художник Farbaholix розписує балончиком великий чорно-білий мурал із риштування',
 2: 'Розпис фасаду графічними смугами: робота з автовишки на багатоповерхівці',
 3: 'Художник малює балончиком морську черепаху на синій цегляній стіні',
 4: 'Мурал: білий шаховий кінь в арці, напис «Кінь / Knight»',
 5: 'Великий мурал на фасаді зі скейтерами та BMX-райдером, напис «Ми тут, щоб творити!»',
 6: 'Більярдна з чорно-білими портретами в стилі гангстерського кіно',
 7: 'Неоновий інтер’єр кальянної: УФ-фарби, мотиви губ і 3D-голови',
 8: 'Розпис на висоті: червоні смуги у спортивному центрі, робота з риштування',
 9: 'Рецепція спортивного центру: червоні діагональні смуги й логотип на стіні',
 10: 'Баскетбольна зала з динамічним розписом кольоровими смугами та логотипом',
 11: 'Стіна з портретами хіп-хоп-артистів: Erykah Badu, MC Fame і The Notorious B.I.G. у кальянній',
 12: 'Розпис офісу: карта світу з фото об’єктів в агентстві нерухомості RE/MAX',
 13: 'УФ-мурал: величезний геймпад із неоново-зеленими бризками',
 14: 'Лазертаг-арена з психоделічним УФ-розписом',
 15: 'Лазертаг-арена: світні вогняні портали УФ-фарбою на перегородках',
 16: 'Ігрова кімната: райдужні переходи й ефект патьоків на стінах',
 17: 'Мурал у спортзалі: чорно-білий бодибілдер на червоному тлі',
 18: 'Вітальня з геометричним розписом із чорних і сірих трикутників',
 19: 'Лаунж із кріслами-мішками, геометричними стінами й намальованим синім спорткаром',
 20: 'Аерографія: білий дим на чорній стіні в кальянній',
 21: 'Коридор лаунжу: УФ-мультяшні персонажі й сузір’я на темних стінах',
 22: 'Графіті-художник малює велику морську черепаху на цегляній стіні',
 23: 'Підводний мурал із китами, рибами й білим ведмедем на фасаді аквапарку',
 24: 'Підводний розпис фасаду: білий ведмідь, морська черепаха й корали',
 25: 'Вхід до аквапарку: папуга й пальми в стилі джунглів',
 26: 'Розпис даху «Musica del Mar» зі скрипковим ключем, Кінбурн',
 27: 'Художник малює реалістичний спорткар KTM X-Bow на стіні',
 28: 'Деталь: реалістична червона троянда, намальована балончиком',
 29: 'Мурал із військовим кораблем на стіні в Миколаєві',
 30: 'Логотип «Rainbow Ecosystem» на фасаді компанії',
 31: 'Мурал на фасаді з хвилями й голубами в Рюссельсгаймі',
 32: 'Фасад спортивного центру з графічними смугами й фігурами спортсменів',
 33: 'Мінімалістичний мурал на фасаді аквапарку із силуетами пальм',
 34: 'Деталь фасаду: тіні пальм в оранжевих тонах, графіті в Генічеську',
 35: 'Реалістичне графіті: ретроавтомобіль Rolls-Royce, Коблеве',
 36: 'Деталь фасаду: світний мотив листа й вогню, графіті 2010 року',
 38: 'Каліграфія «Vielen Dank» фіолетовим, у рамці',
 39: 'Арт-інсталяція «Used for Art» із порожніх балончиків, виставка',
 40: 'Два BMX-велосипеди, розписані в стилі графіті',
 42: 'Розписане дзеркало для фотозони в дитячій перукарні',
 44: 'Графіті-воркшоп для дітей в Internationales Kinderhaus у Франкфурті',
 45: 'Школа графіті: підлітки разом малюють на стіні',
 46: 'Діти після воркшопу в Internationales Kinderhaus, Франкфурт',
 47: 'Дитячий воркшоп: група з буквами, які діти намалювали самі',
 48: 'Хіп-хоп-воркшоп просто неба в Дармштадті',
 49: 'Балончик Montana MTN 94 під час малювання візерунка',
 50: 'Воркшоп: відпрацювання техніки букв з MTN 94',
 51: 'Воркшоп: юна учасниця робить перші кроки з балончиком',
 52: 'Воркшоп: юна учасниця малює класичне графіті',
 53: 'Воркшоп із фотореалізму: реалістична кросівка Nike у графіті',
}
FIX = {  # remove Maik from captions
 31: ('Fassaden-Mural mit Wellen und Tauben in Rüsselsheim', 'Facade mural with waves and doves in Rüsselsheim'),
 46: ('Kinder nach dem Workshop im Internationalen Kinderhaus Frankfurt', 'Children after the workshop at Internationales Kinderhaus Frankfurt'),
}
GALLERY = []
for n in UK:
    de, en, _ = A[n - 1]
    if n in FIX: de, en = FIX[n]
    GALLERY.append((n, {'de': de, 'en': en, 'uk': UK[n]}))

# categories = the four service tiles on the home page
CATS = ('facade', 'indoor', 'workshop', 'objects')
CAT = {n: 'facade' for n in (1, 2, 3, 4, 5, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36)}
CAT.update({n: 'indoor' for n in range(6, 22)})
CAT.update({n: 'workshop' for n in range(44, 54)})
CAT.update({n: 'objects' for n in (38, 39, 40, 42)})
# recent projects shown first in "all works" (media_seo keys)
EXTRA = [
 ('sg-strelitzien', 'facade', {'de': 'Strelitzien-Mural, Hochschule Sankt Georgen, Frankfurt', 'en': 'Bird-of-paradise mural, Sankt Georgen, Frankfurt', 'uk': 'Мурал зі стрелітціями, Sankt Georgen, Франкфурт'}),
 ('sg-monstera-mauer', 'facade', {'de': 'Monstera an der Campusmauer von Sankt Georgen', 'en': 'Monstera on the Sankt Georgen campus wall', 'uk': 'Монстера на стіні кампусу Sankt Georgen'}),
 ('fsv-stadion-arena', 'facade', {'de': 'FSV Frankfurt: Stadionfassade am Bornheimer Hang', 'en': 'FSV Frankfurt: stadium facade at Bornheimer Hang', 'uk': 'FSV Frankfurt: фасад стадіону на Борнгаймер Ганг'}),
 ('fsv-wappen-flammen', 'indoor', {'de': 'FSV-Wappen in blauen Flammen, Innenraum', 'en': 'FSV crest in blue flames, interior', 'uk': 'Герб FSV у синьому полум’ї, інтер’єр'}),
 ('fsv-immer-weiter', 'indoor', {'de': '„Immer weiter“ – Innenraum im FSV-Stadion', 'en': '“Immer weiter” – interior of the FSV stadium', 'uk': '«Immer weiter» – інтер’єр стадіону FSV'}),
 ('wellenlaenge-panorama', 'facade', {'de': 'Restaurant Wellenlänge, Rüsselsheim – Fassaden-Mural', 'en': 'Restaurant Wellenlänge, Rüsselsheim – facade mural', 'uk': 'Ресторан Wellenlänge, Рюссельсгайм – мурал на фасаді'}),
 ('wellenlaenge-interieur', 'indoor', {'de': 'Restaurant Wellenlänge – ornamentale Wände', 'en': 'Restaurant Wellenlänge – ornamental walls', 'uk': 'Ресторан Wellenlänge – орнаментальні стіни'}),
 ('wellenlaenge-welcome', 'objects', {'de': '„Welcome“-Flügel als Fotospot am Tor', 'en': '“Welcome” wings as a photo spot on the gate', 'uk': 'Крила «Welcome» – фотозона на воротах'}),
 ('enso-neu-isenburg', 'facade', {'de': 'ENSO-Mural „Luft“, Neu-Isenburg (Entwurf: Miruna Costa)', 'en': 'ENSO mural “Air”, Neu-Isenburg (design: Miruna Costa)', 'uk': 'Мурал ENSO «Повітря», Ной-Ізенбург (ескіз: Міруна Коста)'}),
 ('cansativa-treppenhaus', 'objects', {'de': 'Firmen-Timeline der Cansativa Group im Treppenhaus', 'en': 'Cansativa Group company timeline in the stairwell', 'uk': 'Таймлайн Cansativa Group на сходах'}),
 ('cansativa-lettering', 'objects', {'de': 'Lettering im Büro der Cansativa Group, Frankfurt', 'en': 'Office lettering for Cansativa Group, Frankfurt', 'uk': 'Леттеринг в офісі Cansativa Group, Франкфурт'}),
 ('bb-philokalist', 'objects', {'de': 'Schaufenster „Frau, Leben, Freiheit“, Braubachstraße', 'en': 'Shop window “Frau, Leben, Freiheit”, Braubachstraße', 'uk': 'Вітрина «Frau, Leben, Freiheit», Braubachstrasse'}),
 ('bb-iimori', 'objects', {'de': 'Schaufenster mit Willy-Brandt-Zitat, Braubachstraße', 'en': 'Shop window with a Willy Brandt quote, Braubachstraße', 'uk': 'Вітрина з цитатою Віллі Брандта, Braubachstrasse'}),
 ('bb-salon', 'objects', {'de': 'Schaufenster „Demokratie lebt vom Mitmachen“', 'en': 'Shop window “Demokratie lebt vom Mitmachen”', 'uk': 'Вітрина «Demokratie lebt vom Mitmachen»'}),
]
