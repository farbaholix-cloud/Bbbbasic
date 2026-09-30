"""Builds the Farbaholix preview pages in DE / EN / UA: home, projects, opening package, about Slavik, magazine."""
import json, html, importlib, base64, urllib.parse

SITE = 'https://farbaholix.de/'
U = SITE + 'wp-content/uploads/'
imgs = json.load(open('imgs.json'))
keep = json.load(open('keep.json'))
MEDIA = json.load(open('media_seo.json'))
from articles import ARTICLES
from calc_texts import CALC
from cases import CASE_PAGES, CAP, UI
from gallery import GALLERY, CATS, CAT, EXTRA
SIZES = json.load(open('gallery_sizes.json'))
ICON_X = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>'
e = html.escape

def old(n):   # existing gallery image, n = number in the alt-text table
    return imgs[keep[n - 1]][0]
def img(key):  # new image under its SEO file name
    return MEDIA[key]['url']

LANGS = {k: importlib.import_module('lang_' + k).L for k in ('de', 'en', 'uk')}
PAGES = ('home', 'projects', 'opening', 'about', 'magazine', 'calc', 'fsv', 'georgen', 'braubach', 'wellen')
URL = {  # WordPress slugs; the home pages are the Polylang front pages
    'de': dict(home='startseite', projects='projekte', opening='eroeffnungspaket', about='ueber-slavik', magazine='magazin', calc='preisrechner', fsv='projekte/fsv-frankfurt-stadion', georgen='projekte/sankt-georgen-mural', braubach='projekte/schaufenster-graffiti-braubachstrasse', wellen='projekte/restaurant-wandgestaltung-wellenlaenge'),
    'en': dict(home='home-en', projects='projects', opening='opening-package', about='about-slavik', magazine='magazine', calc='price-calculator', fsv='projects/fsv-frankfurt-stadium', georgen='projects/sankt-georgen-mural-100-years', braubach='projects/window-graffiti-braubachstrasse', wellen='projects/restaurant-mural-wellenlaenge'),
    'uk': dict(home='holovna', projects='proiekty', opening='paket-vidkryttia', about='pro-slavika', magazine='zhurnal', calc='kalkuliator', fsv='proiekty/stadion-fsv-frankfurt', georgen='proiekty/mural-sankt-georgen', braubach='proiekty/graffiti-vitryny-braubachstrasse', wellen='proiekty/restoran-wellenlange'),
}
LANG_PATH = dict(de='', en='en/', uk='uk/')
def url(k, page):
    return SITE + LANG_PATH[k] + ('' if page == 'home' else URL[k][page] + '/')

HOME_WORKS = [11, 6, 17, 23, 27, 7, 12, 10, 29, 35]
OPENING_WORKS = [9, 30, 25, 32, 20, 42]
WORK_ALT = {
 'de': {11: 'Hip-Hop-Porträtwand in einer Bar', 6: 'Billardraum mit Gangster-Porträts', 17: 'Fitnessstudio-Mural: Bodybuilder', 23: 'Unterwasser-Mural an einem Aquapark',
        27: 'Realistischer Sportwagen als Graffiti', 7: 'Neon-Lounge mit UV-Farben', 12: 'Büro mit Weltkarte an der Wand', 10: 'Basketballhalle mit Streifen-Design',
        29: 'Kriegsschiff-Mural an einer Mauer', 35: 'Oldtimer im Realismus-Stil',
        9: 'Empfang eines Sportzentrums mit Logo-Wand', 30: 'Logo-Mural an einer Firmenfassade', 25: 'Eingangsbereich eines Aquaparks', 32: 'Fassade eines Sportzentrums',
        20: 'Airbrush-Rauch in einer Shisha-Bar', 42: 'Fotospot-Spiegel in einem Kinder-Friseursalon'},
 'en': {11: 'Hip-hop portrait wall in a bar', 6: 'Billiard room with gangster portraits', 17: 'Gym mural: bodybuilder', 23: 'Underwater mural on an aquapark',
        27: 'Realistic sports car as graffiti', 7: 'Neon lounge with UV paint', 12: 'Office with a world map on the wall', 10: 'Basketball hall with stripe design',
        29: 'Warship mural on a wall', 35: 'Vintage car in realistic style',
        9: 'Sports centre reception with logo wall', 30: 'Logo mural on a company facade', 25: 'Aquapark entrance', 32: 'Sports centre facade',
        20: 'Airbrushed smoke in a hookah bar', 42: 'Photo-spot mirror in a kids’ barbershop'},
 'uk': {11: 'Стіна з портретами хіп-хоп-артистів у барі', 6: 'Більярдна з гангстерськими портретами', 17: 'Мурал у спортзалі: бодибілдер', 23: 'Підводний мурал на аквапарку',
        27: 'Реалістичний спорткар у графіті', 7: 'Неоновий лаунж з УФ-фарбами', 12: 'Офіс із картою світу на стіні', 10: 'Баскетбольна зала з розписом смугами',
        29: 'Мурал з військовим кораблем', 35: 'Ретро-автомобіль у реалізмі',
        9: 'Рецепція спортцентру зі стіною-логотипом', 30: 'Мурал-логотип на фасаді компанії', 25: 'Вхід до аквапарку', 32: 'Фасад спортивного центру',
        20: 'Аерографія: дим у кальянній', 42: 'Дзеркало-фотозона в дитячій перукарні'},
}

# testimonials: quoted verbatim, never shortened; translations shown separately
VOICES = [
    ('Als Pharmaunternehmen benötigten wir hochqualifizierte Fachkräfte, die unsere Meilensteine in einem klaren, geradlinigen Stil umsetzen können. Farbaholix hat dies perfekt umgesetzt, indem sie kreative Skizzenideen mit ihrem umfangreichen Erfahrungsschatz in der Malerei verbunden haben. Wir sind äußerst zufrieden mit der Kommunikation und dem Ergebnis und empfehlen Farbaholix uneingeschränkt allen Unternehmen, die professionelle Dienstleistungen suchen.',
     'Benedikt Sons', 'Mitgründer, Geschäftsführer und CEO der Cansativa Group', 54, {
     'uk': 'Як фармацевтичній компанії нам були потрібні висококваліфіковані фахівці, здатні втілити наші віхи в чіткому, лаконічному стилі. Farbaholix зробили це бездоганно, поєднавши креативні ідеї ескізів зі своїм великим досвідом у живописі. Ми надзвичайно задоволені комунікацією та результатом і беззастережно рекомендуємо Farbaholix усім компаніям, які шукають професійні послуги.',
     'en': 'As a pharmaceutical company, we needed highly qualified professionals who could bring our milestones to life in a clear, straightforward style. Farbaholix did this perfectly by combining creative sketch ideas with their extensive experience in painting. We are extremely satisfied with the communication and the result and recommend Farbaholix without reservation to every company looking for professional services.'}),
    ('Slavik, Gründer von Farbaholix, hat in dem Zeitraum von anderthalb Jahren, die künstlerische Gestaltung unseres Fußballstadions durchgeführt. Kreativität, Ausführung, Flexibilität und Zuverlässigkeit waren auf allerhöchstem Niveau. Ich kann Slavik uneingeschränkt und mit Nachdruck weiterempfehlen.',
     'Robert Lempka', 'FSV Frankfurt Geschäftsführer', 55, {
     'uk': 'Славік, засновник Farbaholix, упродовж півтора року виконував художнє оформлення нашого футбольного стадіону. Креативність, виконання, гнучкість і надійність були на найвищому рівні. Я беззастережно й наполегливо рекомендую Славіка.',
     'en': 'Slavik, founder of Farbaholix, carried out the artistic design of our football stadium over a period of one and a half years. Creativity, execution, flexibility and reliability were at the very highest level. I recommend Slavik without reservation and emphatically.'}),
    ('Slavik ist in erster Linie ein guter Mensch und zugleich ein Künstler mit echter Leidenschaft und Professionalität. Seine Kunst verbindet Menschen, schafft Atmosphäre und verleiht Räumen eine besondere Bedeutung. Ich empfehle Slavik meinen Freunden und Bekannten mit voller Überzeugung. Seine Arbeit zeichnet sich durch Engagement, Zuverlässigkeit und eine starke kreative Vision aus.',
     'Dr. Stefan Söhngen', 'Brückenbauer, Netzwerker, Speaker, Autor', 56, {
     'uk': 'Славік – насамперед хороша людина і водночас художник зі справжньою пристрастю та професіоналізмом. Його мистецтво об’єднує людей, створює атмосферу й надає просторам особливого значення. Я з повною переконаністю рекомендую Славіка своїм друзям і знайомим. Його роботу вирізняють відданість, надійність і сильне творче бачення.',
     'en': 'Slavik is first and foremost a good person and at the same time an artist with genuine passion and professionalism. His art connects people, creates atmosphere and gives spaces a special meaning. I recommend Slavik to my friends and acquaintances with full conviction. His work is characterised by commitment, reliability and a strong creative vision.'}),
]

# press: headline stays in the original language; link = original article or our project
PRESS = [
    dict(pub='Offenbach-Post', date='2026-09-26', title='Große Wandkunst für große Zukunftsfrage', img='presse-offenbach-post', link=('projects', 'enso'), home=True, note={'de': 'Titelseite', 'en': 'front page', 'uk': 'перша шпальта'}),
    dict(pub='Offenbach-Post', date='2026-09-26', title='Luft kann man sehen und hören', img='presse-op-seite37', link=('projects', 'enso'), home=False, note={'de': 'Seite 37, Christina Langenbahn', 'en': 'page 37, Christina Langenbahn', 'uk': 'с. 37, Christina Langenbahn'}),
    dict(pub='Kreis Offenbach', date=None, title='Mensch, Natur, Zusammenhalt – ENSO', img='enso-neu-isenburg', link='https://www.kreis-offenbach.de/enso', home=False),
    dict(pub='hessenschau.de (hr)', date='2024-11-27', title='FSV Frankfurt: Künstler verschönert Stadion am Bornheimer Hang', img='presse-hessenschau', link='https://www.hessenschau.de/sport/fussball/regionalliga/fsv-frankfurt-kuenstler-verschoenert-stadion-am-bornheimer-hang-v1,fsv-grafitti-100.html', home=True),
    dict(pub='hessenschau (Video)', date='2024-11-27', title='Große Kunst am Bornheimer Hang', img='fsv-stadion-arena', link='https://www.hessenschau.de/panorama/riesiges-fsv-wappen-grosse-kunst-am-bornheimer-hang,video-204422.html', home=False),
    dict(pub='sportschau.de (hr)', date='2024-11-27', title='FSV Frankfurt: Künstler verschönert Stadion am Bornheimer Hang', img='fsv-panorama', link='https://www.sportschau.de/regional/hr/hr-fsv-frankfurt-kuenstler-verschoenert-stadion-am-bornheimer-hang-100.html', home=False),
    dict(pub='frankfurt-live.com', date='2025-10-02', title='Graffiti für Frieden und Freiheit', img='presse-frankfurt-live', link='https://www.frankfurt-live.com/graffiti-fuer-frieden-und-freiheit', home=True),
    dict(pub='Frankfurter Neue Presse', date='2026-04-29', title='Aus seiner Sprühdose kommen Blumen', img='georgen-presse', link=('georgen', 'quellen'), home=True, note={'de': 'Seite 32, Stefanie Wehr', 'en': 'page 32, Stefanie Wehr', 'uk': 'с. 32, Stefanie Wehr'}),
    dict(pub='Hochschule Sankt Georgen', date='2026-04-14', title='Kunstprojekt an der Mauer', img='georgen-strassenbahn', link='https://www.sankt-georgen.de/button-menue/mediathek/nachrichten-aus-sankt-georgen/detail/kunstprojekt-an-der-mauer-1100/', home=False),
    dict(pub='stefansoehngen.de', date='2025-09-04', title='Kreative Raumgestaltung mit Wirkung – Wie Slaviks Kunst Unternehmen in Szene setzt', img=None, link='https://stefansoehngen.de/kreative-raumgestaltung-mit-wirkung/', home=False),
    dict(pub='Вечірній Миколаїв', date='2021-09-14', title='В память о корабелах и шахматистах', img=None, link='https://vn.mk.ua/ru/v-pamyat-o-korabelah-i-shahmatistah/', home=False),
    dict(pub='Monochronicle', date=None, title='BVB – Artist profile', img=None, link='https://monochronicle.com/artist/bvb/', home=False),
    dict(pub='Weltexpresso', date='2025-10-02', title='Graffiti für Frieden und Freiheit', img='bb-iimori', link='https://weltexpresso.de/index.php/heimspiel/35600-graffiti-fuer-frieden-und-freiheit', home=False),
    dict(pub='Mykolaiv Future', date=None, title='Мурали Миколаєва: слідами street-художників', img=None, link='https://mykolaiv-future.com.ua/uk/articles-muraly-mykolayeva-slidamy-street-hudozhnykiv', home=False),
]
def fdate(k, iso):
    if not iso: return ''
    y, m, d = iso.split('-')
    return '%s.%s.%s' % (d, m, y) if k != 'en' else '%s/%s/%s' % (d, m, y)

CASES = {  # key: (anchor id, main image, thumbs, on home)
 'georgen': ('sankt-georgen', 'sg-strelitzien', ['sg-blueten', 'sg-monstera', 'georgen-strassenbahn', 'georgen-kuenstler'], True),
 'fsv': ('fsv-frankfurt', 'fsv-stadion-arena', ['fsv-wappen-flammen'], True),
 'braubach': ('braubachstrasse', 'bb-philokalist', ['bb-salon', 'bb-iimori'], False),
 'wellen': ('wellenlaenge', 'wellenlaenge-panorama', ['wellenlaenge-interieur', 'wellenlaenge-portrait', 'wl-fassade-seite', 'wellenlaenge-fassade'], True),
 'cansativa': ('cansativa', 'cansativa-treppenhaus', ['cansativa-abkleben', 'cansativa-geruest', 'cansativa-detail', 'cansativa-lettering'], False),
 'enso': ('enso', 'enso-neu-isenburg', ['presse-offenbach-post', 'presse-op-seite37'], False),   # ENSO only on the projects page and in the press
}
CASE_VIDEOS = {'cansativa': dict(src='vid-cansativa', poster='vid-cansativa-poster', len='0:49')}   # case blocks without a report page
CASE_PLACE = {'braubach': 'Frankfurt am Main, Braubachstraße', 'georgen': 'Frankfurt am Main', 'fsv': 'Frankfurt am Main', 'wellen': 'Rüsselsheim am Main', 'cansativa': 'Frankfurt am Main', 'enso': 'Neu-Isenburg'}

WA = '4915172450347'   # WhatsApp Business (German number)
TG_USER = 'slavik_ffm'   # Telegram button → Slavik's personal account (the bot @Farbaholix_chat_bot is only his inbox for the form)
IG = 'https://www.instagram.com/farbaholix/'
SAME_AS = ['https://www.instagram.com/farbaholix/', 'https://www.facebook.com/farbaholix', 'https://www.linkedin.com/company/farbaholix/', 'https://t.me/farbaholix']

# ---------------- structured data (schema.org) ----------------
def ld_base(k):
    L = LANGS[k]
    person = {'@type': 'Person', '@id': SITE + '#slavik', 'name': 'Viacheslav Balabaiev',
              'alternateName': ['Slavik', 'Slavik Balabaiev', 'BVB', 'Вячеслав Балабаєв', 'Вячеслав Балабаев', 'Viacheslav “Slavik” Balabaiev'],
              'jobTitle': {'de': 'Graffiti- und Mural-Künstler', 'en': 'Graffiti and mural artist', 'uk': 'Художник графіті й муралів'}[k],
              'nationality': {'@type': 'Country', 'name': 'Ukraine'},
              'homeLocation': {'@type': 'City', 'name': 'Frankfurt am Main'},
              'image': img('slavik-portrait'), 'url': url(k, 'about'),
              'worksFor': {'@id': SITE + '#farbaholix'}, 'sameAs': SAME_AS + ['https://www.instagram.com/slavik.ffm/', 'https://www.instagram.com/bvb_southfront/', 'https://www.facebook.com/bvbsouthfront', 'https://monochronicle.com/artist/bvb/'],
              'knowsLanguage': ['de', 'en', 'uk', 'ru'],
              'knowsAbout': ['Graffiti', 'Mural', 'Street Art', 'Wandgestaltung', 'Hip-Hop', 'Kalligrafie', 'Interior Design'],
              'subjectOf': [p['link'] for p in PRESS if isinstance(p['link'], str)]}
    org = {'@type': ['ProfessionalService', 'LocalBusiness'], '@id': SITE + '#farbaholix', 'name': 'Farbaholix',
           'alternateName': 'Farbaholix – Frankfurt Mural Movement', 'url': SITE, 'logo': img('logo-badge'), 'image': [img('fsv-stadion-arena'), img('sg-strelitzien')],
           'description': L['org_desc'], 'telephone': '+49 151 72450347', 'email': 'farbaholix@gmail.com',
           'address': {'@type': 'PostalAddress', 'addressLocality': 'Frankfurt am Main', 'addressRegion': 'Hessen', 'addressCountry': 'DE'},
           'areaServed': ['Frankfurt am Main', 'Rhein-Main', 'Offenbach', 'Neu-Isenburg', 'Darmstadt', 'Rüsselsheim'],
           'founder': {'@id': SITE + '#slavik'}, 'sameAs': SAME_AS, 'knowsLanguage': ['de', 'en', 'uk', 'ru'],
           'makesOffer': [{'@type': 'Offer', 'itemOffered': {'@type': 'Service', 'name': t, 'description': d}} for t, d in L['services']]}
    return [org, person, {'@type': 'WebSite', '@id': SITE + '#website', 'url': SITE, 'name': 'Farbaholix', 'inLanguage': ['de', 'en', 'uk'], 'publisher': {'@id': SITE + '#farbaholix'}}]

def image_obj(key, caption):
    return {'@type': 'ImageObject', 'contentUrl': img(key), 'caption': caption, 'creator': {'@id': SITE + '#slavik'},
            'creditText': 'Farbaholix / Viacheslav Balabaiev', 'copyrightNotice': '© Farbaholix'}

def breadcrumb(k, name, page):
    L = LANGS[k]
    return {'@type': 'BreadcrumbList', 'itemListElement': [
        {'@type': 'ListItem', 'position': 1, 'name': L['breadcrumb_home'], 'item': url(k, 'home')},
        {'@type': 'ListItem', 'position': 2, 'name': name, 'item': url(k, page)}]}

def ld_script(graph):
    return '<script type="application/ld+json">%s</script>' % json.dumps({'@context': 'https://schema.org', '@graph': graph}, ensure_ascii=False).replace('</', '<\\/')

# ---------------- page chrome ----------------
def chrome_top(k, page, static_logo):
    L = LANGS[k]
    lb = ''.join('<a class="fx-lang%s" href="%s" hreflang="%s">%s</a>' % (' is-on' if c == k else '', url(c, page), c, lbl) for c, lbl in (('de', 'DE'), ('en', 'EN'), ('uk', 'UA')))
    def href(t): return url(k, 'home') + t if t.startswith('#') else url(k, t)
    items = []
    for t, lbl in L['menu']:
        items.append((t, lbl))
        if t == 'opening': items.append(('calc', CALC[k]['menu']))
    menu = ''.join('<a href="%s"%s>%s</a>' % (href(t), ' class="fx-menu-hl"' if t == 'calc' else '', e(lbl)) for t, lbl in items)
    o = ['<div class="fx%s" lang="%s"><div class="fx-light" aria-hidden="true"></div><div class="fx-tube" aria-hidden="true"></div>' % (' fx-sub' if static_logo else '', L['lang'])]
    o.append('<header class="fx-top"><nav class="fx-langs">%s</nav><button class="fx-burger" id="fxBurger" aria-label="%s" aria-expanded="false"><span></span><span></span><span></span></button></header>' % (lb, e(L['menu_label'])))
    o.append('<nav class="fx-menu" id="fxMenu" aria-hidden="true"><button class="fx-menu-close" id="fxMenuClose" aria-label="%s">×</button>%s<p class="fx-menu-foot"><a href="tel:+4915172450347">+49 151 724 50347</a> · <a href="mailto:farbaholix@gmail.com">E-Mail</a> · <a href="https://www.instagram.com/farbaholix/" target="_blank" rel="noopener">Instagram</a></p></nav>' % (e(L['close_label']), menu))
    if static_logo:
        o.append('<a class="fx-logo fx-logo-static" href="%s"><img src="%s" alt="%s"></a>' % (url(k, 'home'), img('logo-badge'), e(L['logo_alt'])))
    else:
        o.append('<a class="fx-logo" id="fxLogo" href="%s"><img src="%s" alt="%s" fetchpriority="high"></a>' % (url(k, 'home'), img('logo-badge'), e(L['logo_alt'])))
    return o

def photo_case(k, key, with_thumbs, artist=False):
    L = LANGS[k]; cid, im, thumbs, _ = CASES[key]; title, text, facts = L['cases'][key]
    a = ''
    if artist:
        a = ('<div class="fx-artist" id="fxArtist"><div class="fx-artist-clip"><img src="%s" alt="Viacheslav „Slavik“ Balabaiev"></div>'
             '<div class="fx-bubble" role="note"><p>%s</p><a href="tel:+4915172450347">%s</a><button type="button" data-fx-contact>%s</button></div></div>') % (img('artist-slavik-v3'), e(L['bubble']), e(L['bubble_call']), e(L['bubble_write']))
    report = url(k, key) if key in CASE_PAGES else None
    th = ''
    if with_thumbs and thumbs:
        th = '<div class="fx-thumbs">%s</div>' % ''.join('<a class="fx-lb" data-lb="%s" href="%s" data-cap="%s"><img loading="lazy" src="%s" alt="%s"></a>' % (
            cid, img(t), e(CAP[t][('de', 'en', 'uk').index(k)] if t in CAP else title), img(t), e(title)) for t in thumbs)
    vd = CASE_VIDEOS.get(key) or (CASE_PAGES.get(key) or {}).get('video')
    if vd:   # video tile first in the thumbnail row: poster + play + length, opens the full-screen player
        vt = ('<button type="button" class="fx-vthumb" data-video="%s" data-poster="%s" aria-label="%s"><img loading="lazy" src="%s" alt="%s">'
              '<span class="fx-vplay" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M8 5.5v13l11-6.5z"/></svg></span><span class="fx-vlen">%s</span></button>') % (
            img(vd['src']), img(vd['poster']), e(UI[k]['video_play']), img(vd['poster']), e(MEDIA[vd['src']].get('alt_de', title)), vd.get('len', ''))
        th = th.replace('<div class="fx-thumbs">', '<div class="fx-thumbs">' + vt, 1) if th else '<div class="fx-thumbs">%s</div>' % vt
    main = '<img loading="lazy" src="%s" alt="%s">' % (img(im), e(title + ' – ' + facts[0]))
    main = ('<a class="fx-case-link" href="%s">%s</a>' % (report, main)) if report else ('<a class="fx-lb" data-lb="%s" href="%s" data-cap="%s">%s</a>' % (cid, img(im), e(title), main))
    h = ('<a href="%s">%s</a>' % (report, e(title))) if report else e(title)
    more = '<a class="fx-case-more" href="%s">%s →</a>' % (report, e(UI[k]['more'])) if report else ''
    return ('<figure class="fx-photo%s" id="%s"><div class="fx-stage">%s%s</div>%s'
            '<figcaption><h3>%s</h3><p>%s</p><span class="fx-meta">%s</span>%s</figcaption></figure>') % (
            ' fx-photo-artist' if artist else '', cid, a, main, th, h, e(text), e(' · '.join(facts)), more)

def works_grid(k, nums):
    """10 works on the page + every portfolio photo as a hidden lightbox link (data-cat) + the "all works" overview skeleton."""
    L = LANGS[k]; caps = {n: c[k] for n, c in GALLERY}
    sz = lambda u: SIZES.get(u, {'t': u, 'l': u})
    def link(url, cap, cat, inner='', hidden=False, recent=False):
        return '<a class="fx-lb" data-lb="works" data-cat="%s" data-thumb="%s" href="%s" data-cap="%s"%s%s>%s</a>' % (cat, sz(url)['t'], sz(url)['l'], e(cap), ' data-recent="1"' if recent else '', ' hidden' if hidden else '', inner)
    shown = ''.join('<figure class="fx-photo fx-photo-sm">%s<figcaption>%s</figcaption></figure>' % (
        link(old(n), caps.get(n, WORK_ALT[k][n]), CAT[n], '<img loading="lazy" src="%s" alt="%s">' % (sz(old(n))['t'], e(WORK_ALT[k][n] + ' – Farbaholix'))), e(WORK_ALT[k][n])) for n in nums)
    rest = ''.join(link(img(key), cap[k], cat, hidden=True, recent=True) for key, cat, cap in EXTRA)
    rest += ''.join(link(old(n), c, CAT[n], hidden=True) for n, c in caps.items() if n not in nums)
    total = len(EXTRA) + len(caps)
    counts = {c: sum(1 for _, cc, _ in EXTRA if cc == c) + sum(1 for n in caps if CAT[n] == c) for c in CATS}
    chips = '<button type="button" class="is-on" data-cat="all">%s <span>%d</span></button>' % (e(L['go_all']), total)
    chips += ''.join('<button type="button" data-cat="%s">%s <span>%d</span></button>' % (c, e(L['services'][i][0]), counts[c]) for i, c in enumerate(CATS))
    overlay = ('<div class="fx-go" id="fxGo" hidden role="dialog" aria-modal="true" aria-label="%s"><div class="fx-go-head"><div class="fx-go-top"><h2>%s</h2>'
               '<button type="button" class="fx-go-x" aria-label="%s">%s</button></div><div class="fx-go-cats" role="tablist">%s</div></div><div class="fx-go-grid"></div></div>') % (
               e(L['go_title']), e(L['go_title']), e(L['close_label']), ICON_X, chips)
    return ('<div class="fx-grid">%s</div><div hidden>%s</div><p class="fx-more fx-more-btn"><button type="button" class="fx-btn fx-btn-ghost" data-go-open="all">%s (%d) →</button><a class="fx-more-ig" href="%s" target="_blank" rel="noopener">%s%s →</a></p>%s' % (
        shown, rest, e(UI[k]['all_works']), total, IG, SVG_IG, e(LANGS[k]['insta_more']), overlay))

PRESS_LOGOS = {'Offenbach-Post': 'plogo-op', 'Kreis Offenbach': 'plogo-ko', 'hessenschau.de (hr)': 'plogo-hessenschau', 'hessenschau (Video)': 'plogo-hessenschau',
               'sportschau.de (hr)': 'plogo-sportschau', 'frankfurt-live.com': 'plogo-fl', 'Frankfurter Neue Presse': 'plogo-fnp', 'Hochschule Sankt Georgen': 'plogo-sg', 'Weltexpresso': 'plogo-welt'}

def press_cards(k, items):
    L = LANGS[k]; o = ['<div class="fx-press">']
    for p in items:
        internal = not isinstance(p['link'], str)
        link = url(k, p['link'][0]) + '#' + p['link'][1] if internal else p['link']
        meta = ' · '.join(x for x in (fdate(k, p['date']), p.get('note', {}).get(k, '')) if x)
        lg = PRESS_LOGOS.get(p['pub'])
        badge = '<img class="fx-press-logo" loading="lazy" src="%s" alt="%s">' % (img(lg), e(MEDIA[lg]['alt_de'])) if lg else ''
        pic = '<div class="fx-press-img"><img loading="lazy" src="%s" alt="%s – %s">%s</div>' % (img(p['img']), e(p['pub']), e(p['title']), badge) if p['img'] else ''
        o.append('<a class="fx-press-card%s" href="%s"%s>%s<div class="fx-press-body"><span class="fx-press-pub">%s</span><h3 lang="%s">%s</h3><span class="fx-press-meta">%s%s →</span></div></a>' % (
            '' if p['img'] else ' fx-press-text', link, '' if internal else ' target="_blank" rel="noopener"', pic, e(p['pub']),
            'ru' if p['pub'] == 'Вечірній Миколаїв' else ('uk' if 'Mykolaiv' in p['pub'] else 'de'), e(p['title']), e(meta + ' · ' if meta else ''), e(L['press_project'] if internal else L['press_more'])))
    o.append('</div>')
    return ''.join(o)

SVG_WA = '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 2a10 10 0 0 0-8.6 15.1L2 22l5-1.3A10 10 0 1 0 12 2zm5.3 14.1c-.2.6-1.3 1.2-1.8 1.2-.5.1-1 .2-3.4-.7-2.8-1.1-4.6-4-4.8-4.2-.1-.2-1.1-1.5-1.1-2.9s.7-2 1-2.3c.2-.3.5-.3.7-.3h.5c.2 0 .4 0 .6.5l.8 2c.1.2.1.4 0 .6l-.3.5-.4.4c-.1.1-.3.3-.1.6.2.3.8 1.3 1.7 2.1 1.2 1 2.1 1.3 2.4 1.5.3.1.5.1.6-.1l.9-1c.2-.3.4-.2.6-.1l1.9.9c.3.1.5.2.5.3.1.2.1.8-.1 1.3z"/></svg>'
SVG_TG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M21.4 3.6 2.9 10.8c-1.3.5-1.3 1.2-.2 1.5l4.7 1.5 1.8 5.6c.2.6.4.8.9.8.4 0 .6-.2.9-.4l2.3-2.2 4.7 3.5c.9.5 1.5.2 1.7-.8l3.1-14.6c.3-1.3-.5-1.9-1.4-1.5ZM8.6 13.5l8.9-5.6c.4-.3.8-.1.5.2l-7.6 6.9-.3 3.2-1.5-4.7Z"/></svg>'
SVG_IG = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="5.5" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="12" cy="12" r="4.2" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="17.3" cy="6.7" r="1.3" fill="currentColor"/></svg>'
SVG_MAIL = '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" d="M3.5 6h17v12h-17zM3.5 6l8.5 7 8.5-7"/></svg>'
SVG_MSG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" d="M4 5h16v11H9l-5 4z"/><path stroke="currentColor" stroke-width="2" stroke-linecap="round" d="M8 9.5h8M8 12.5h5"/></svg>'
MAIL = 'farbaholix@gmail.com'

def contact_form(k, compact=False):
    """Neutral enquiry form – posts to /wp-json/fx/v1/contact (stored in wp-admin, e-mailed and forwarded to the owner)."""
    L = LANGS[k]
    consent = e(L['f_consent']).replace('{ds}', '<a href="/datenschutzerklarung/">%s</a>' % e(L['f_ds']))
    fx_attrs = ' '.join('data-%s="%s"' % (a.replace('_', '-'), e(L[a])) for a in ('ch_name', 'ch_contact', 'ch_msg', 'ch_img', 'ch_ready', 'f_att_bad', 'f_att_max', 'f_att_rm'))
    paint = ('<div class="fx-paint" aria-hidden="true"><svg viewBox="0 0 300 18" preserveAspectRatio="none"><defs><linearGradient id="fxPg%s" x1="0" x2="1">'
             '<stop offset="0" stop-color="#d9b26a"/><stop offset=".45" stop-color="#f0854b"/><stop offset=".75" stop-color="#e0457b"/><stop offset="1" stop-color="#8a63ff"/></linearGradient></defs>'
             '<path class="fx-paint-bg" d="M4 10 C 60 4, 110 15, 160 9 S 250 5, 296 10"/><path class="fx-paint-fg" stroke="url(#fxPg%s)" pathLength="100" d="M4 10 C 60 4, 110 15, 160 9 S 250 5, 296 10"/></svg>'
             '<span class="fx-paint-can">%s</span></div><p class="fx-cheer" aria-live="polite"></p>') % ('c' if compact else 'm', 'c' if compact else 'm', SVG_CAN)
    attach = ('<label class="fx-att"><input type="file" accept="image/jpeg,image/png,image/webp,image/gif,image/heic,image/heif,.heic,.heif" multiple>'
              '<span class="fx-att-ic">%s</span><span class="fx-att-tx"><b>%s</b><small>%s</small></span><span class="fx-att-plus" aria-hidden="true">+</span></label>'
              '<div class="fx-att-list"></div><p class="fx-att-err" role="alert"></p>') % (SVG_PHOTO, e(L['f_att']), e(L['f_att_sub']))
    return ('<form class="fx-cform%s" data-fx-form novalidate %s %s><p class="fx-cform-lead">%s</p>' + paint + 
            '<input type="text" name="name" autocomplete="name" placeholder="%s" aria-label="%s" maxlength="120">'
            '<input type="text" name="contact" autocomplete="email" inputmode="email" required placeholder="%s" aria-label="%s" maxlength="160">'
            '<textarea name="message" rows="%d" required placeholder="%s" aria-label="%s" maxlength="5000"></textarea>' + attach + 
            '<input type="text" name="website" tabindex="-1" autocomplete="off" class="fx-hp" aria-hidden="true">'
            '<button type="submit" class="fx-btn fx-cform-send" data-sending="%s">%s</button><p class="fx-cform-note">%s</p>'
            '<p class="fx-cform-status" role="status" aria-live="polite" data-ok="%s" data-err="%s"></p></form>') % (
            ' fx-cform-compact' if compact else '', th_attrs(k), fx_attrs, e(L['form_lead']), e(L['f_name']), e(L['f_name']), e(L['f_contact']), e(L['f_contact']),
            3 if compact else 5, e(L['f_msg']), e(L['f_msg']), e(L['f_sending']), e(L['f_send']), consent, e(L['f_ok']), e(L['f_err']))

def th_attrs(k):   # texts for the chat view that replaces the form after sending (fx.js)
    L = LANGS[k]
    return ' '.join('data-%s="%s"' % (a, e(L[b])) for a, b in (('th-you', 'th_you'), ('th-me', 'th_me'), ('th-wait', 'th_wait'), ('th-mail', 'th_mail'), ('th-ph', 'th_ph'), ('th-send', 'th_send'), ('th-new', 'th_new')))

SVG_PHONE = '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" d="M5 3.5h3.2l1.6 4.2-2.2 1.4a11 11 0 0 0 7.3 7.3l1.4-2.2 4.2 1.6V19a1.5 1.5 0 0 1-1.6 1.5C10.8 20 4 13.2 3.5 5.1A1.5 1.5 0 0 1 5 3.5z"/></svg>'
SVG_FB = '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M13.5 21v-7.5h2.6l.4-3h-3V8.6c0-.9.3-1.5 1.5-1.5h1.6V4.4c-.3 0-1.2-.1-2.3-.1-2.3 0-3.8 1.4-3.8 3.9v2.3H8v3h2.5V21z"/></svg>'
SVG_LI = '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M6.9 8.8H3.8V20h3.1zM5.3 3.5a1.8 1.8 0 1 0 0 3.6 1.8 1.8 0 0 0 0-3.6zM20.2 13.6c0-3-1.6-4.9-4.2-4.9-1.4 0-2.4.8-2.8 1.5V8.8h-3V20h3.1v-5.8c0-1.5.6-2.6 2-2.6s1.8 1.2 1.8 2.7V20h3.1z"/></svg>'
SVG_PHOTO = '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" d="M3.5 7.5A2 2 0 0 1 5.5 5.5h2.3l1.4-2h5.6l1.4 2h2.3a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/><circle cx="12" cy="12.5" r="3.8" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>'
SVG_CAN = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="7" y="8" width="9" height="14" rx="2" fill="#f3ece0"/><rect x="7" y="12" width="9" height="5" fill="#e0457b"/><rect x="9.5" y="4.5" width="4" height="3.5" rx="1" fill="#cfc6b8"/><rect x="10.5" y="2.5" width="2" height="2" fill="#1a1109"/><circle cx="4" cy="3" r="1" fill="#f0854b"/><circle cx="6" cy="1.6" r=".8" fill="#e0457b"/><circle cx="3" cy="5.6" r=".7" fill="#d9b26a"/></svg>'
SVG_PIN = '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2" d="M12 21s-6.5-6-6.5-11a6.5 6.5 0 0 1 13 0c0 5-6.5 11-6.5 11z"/><circle cx="12" cy="10" r="2.3" fill="currentColor"/></svg>'

def direct_buttons(k, small=False):
    """Direct channels as a minimal row of round brand icons with a tiny caption (they open the visitor's own app)."""
    L = LANGS[k]
    items = [('wa', 'https://wa.me/%s?text=%s' % (WA, urllib.parse.quote(L['direct_hello'])), SVG_WA, L['direct_wa'], 'WhatsApp +49 151 724 50347', True),
             ('tg', 'https://t.me/%s' % TG_USER, SVG_TG, L['direct_tg'], 'Telegram @' + TG_USER, True),
             ('mail', 'mailto:%s' % MAIL, SVG_MAIL, L['direct_mail'], MAIL, False)]
    if not small:
        items += [('ig', IG, SVG_IG, 'Instagram', 'Instagram @farbaholix', True),
                  ('tel', 'tel:+4915172450347', SVG_PHONE, L['phone_l'], '+49 151 724 50347', False)]
    btns = ''.join('<a class="fx-direct-btn fx-d-%s" href="%s" title="%s" aria-label="%s"%s><span class="fx-d-ic">%s</span><span class="fx-d-l">%s</span></a>' % (
        c, e(h), e(t), e(t), ' target="_blank" rel="noopener"' if blank else '', ic, e(lbl)) for c, h, ic, lbl, t, blank in items)
    return '<div class="fx-direct%s"><p class="fx-direct-t">%s</p><div class="fx-direct-btns">%s</div></div>' % (' fx-direct-sm' if small else '', e(L['direct_t']), btns)

def call_card(k):
    L = LANGS[k]
    return ('<div class="fx-call"><div class="fx-call-top"><span class="fx-call-face"><img src="%s" alt="Slavik"><i class="fx-call-dot" aria-hidden="true"></i></span>'
            '<span><b>Slavik</b> · <span class="fx-call-role">%s</span><br><span class="fx-call-status" data-on="%s" data-off="%s">%s</span></span></div>'
            '<p class="fx-call-hook">%s</p><a class="fx-call-btn" href="tel:+4915172450347"><span class="fx-call-ring" aria-hidden="true">📞</span>%s</a><p class="fx-call-micro">%s</p></div>') % (
            img('slavik-portrait'), e(L['call_role']), e(L['call_on']), e(L['call_off']), e(L['call_on']), e(L['call_hook']), e(L['call_btn']), e(L['call_micro']))

def contact_section(k):
    L = LANGS[k]
    return ('<section class="fx-sec" id="kontakt"><h2>%s</h2><p>%s</p><div class="fx-contact-grid">%s<div class="fx-cform-card"><h3>%s</h3>%s</div></div>%s'
            '<p class="fx-city">%s%s</p></section>') % (
            e(L['s_contact']), e(L['contact_lead']), call_card(k), e(L['form_t']), contact_form(k), direct_buttons(k),
            SVG_PIN, e(L['city']))

def contact_open(k):   # kept name: every page ends with the contact section
    return contact_section(k)

def chrome_bottom(k):
    L = LANGS[k]
    fab = ('<button class="fx-fab" id="fxFab" aria-label="%s" aria-expanded="false">%s</button>'
           '<div class="fx-pop" id="fxPop" hidden role="dialog" aria-label="%s"><button class="fx-pop-x" id="fxPopX" aria-label="%s">%s</button>'
           '<div class="fx-pop-head"><img src="%s" alt="Slavik"><span><b>Slavik</b><br><small>%s</small></span></div>%s%s</div>') % (
           e(L['fab_label']), SVG_MSG, e(L['fab_label']), e(L['close_label']), ICON_X, img('slavik-portrait'), e(L['call_role']), contact_form(k, compact=True), direct_buttons(k, small=True))
    return ('%s<footer class="fx-foot"><nav class="fx-social">'
            '<a href="https://www.instagram.com/farbaholix/" aria-label="Instagram" title="Instagram">%s</a><a href="https://www.facebook.com/farbaholix" aria-label="Facebook" title="Facebook">%s</a>'
            '<a href="https://www.linkedin.com/company/farbaholix/" aria-label="LinkedIn" title="LinkedIn">%s</a></nav>'
            '<a href="/impressum/">%s</a> · <a href="/datenschutzerklarung/">%s</a><br>© Farbaholix · Viacheslav Balabaiev · Frankfurt am Main</footer></div>') % (fab, SVG_IG, SVG_FB, SVG_LI, L['footer_imp'], L['footer_ds'])

def page_home(k):
    SERVICE_IMGS = [SIZES.get(u, {'t': u})['t'] for u in (img('tile-fassaden'), img('tile-innenraeume'), old(44), img('cansativa-lettering'))]   # 768px versions
    L = LANGS[k]; o = chrome_top(k, 'home', False)
    o.append('<div class="fx-intro"></div>')
    o.append('<div class="fx-video-wrap"><div class="fx-video-box"><video class="fx-video" id="fxVideo" src="%s2026/06/farbaholix_video1.mp4" autoplay muted loop playsinline preload="metadata" aria-label="Farbaholix Graffiti Frankfurt" data-video="%s2026/06/farbaholix_video1.mp4"></video>'
             '<button type="button" class="fx-vfull" data-video="%s2026/06/farbaholix_video1.mp4" aria-label="Vollbild"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/></svg></button></div></div>' % (U, U, U))
    o.append('<section class="fx-hero"><p class="fx-tagline">%s</p><h1>%s</h1><p class="fx-lead">%s</p>' % (e(L['tagline']), e(L['h1']), e(L['lead'])))
    o.append('<div class="fx-ctas"><a class="fx-btn" href="#kontakt">%s</a><a class="fx-btn fx-btn-ghost" href="#projekte">%s</a></div>' % (e(L['cta1']), e(L['cta2'])))
    o.append('<div class="fx-stats">%s</div>' % ''.join('<div><b>%s</b><span>%s</span></div>' % (e(n), e(t)) for n, t in L['stats']))
    o.append('<div class="fx-partners"><p class="fx-partners-t">%s</p><div class="fx-partners-logos">'
             '<a href="https://www.mtn-shop.de/" target="_blank" rel="noopener"><img class="fx-logo-mtn" src="%s" alt="Montana Colors" width="560" height="150"></a><i aria-hidden="true"></i>'
             '<a href="https://www.caparol.de/" target="_blank" rel="noopener"><img class="fx-logo-cap" src="%s" alt="Caparol" width="291" height="230"></a></div>'
             '<p class="fx-trust-line">%s</p></div></section>' % (e(L['proud']), img('logo-montana'), img('logo-caparol'), e(L['trust'][3])))
    o.append('<section class="fx-sec" id="leistungen"><h2>%s</h2><div class="fx-tiles">' % e(L['s_services']))
    for (t, _), short, src, cat in zip(L['services'], L['services_short'], SERVICE_IMGS, CATS):
        o.append('<a class="fx-tile" href="#arbeiten" data-go-open="%s"><img loading="lazy" src="%s" alt="%s"><div class="fx-tile-t"><h3>%s</h3><p>%s</p><span class="fx-tile-go">%s →</span></div></a>' % (cat, src, e(t), e(t).replace('Innenraumgestaltung', 'Innenraum&shy;gestaltung'), e(short), e(L['tile_more'])))
    o.append('<a class="fx-tile fx-tile-promo" href="%s"><img loading="lazy" src="%s" alt="%s"><div class="fx-tile-t"><h3>%s</h3><p>%s</p><span class="fx-tile-go">%s →</span></div></a></div>' % (
        url(k, 'opening'), old(30), e(L['promo_t']), e(L['promo_t']), e(L['promo_short']), e(L['promo_a'])))
    o.append('<p class="fx-swipe" aria-hidden="true">%s →</p></section>' % e(L['svc_more']))
    C = CALC[k]
    o.append('<section class="fx-sec"><a class="fx-calc-teaser" href="%s"><span class="fx-calc-ico" aria-hidden="true">€</span><span><b>%s</b><br>%s</span><span class="fx-btn">%s →</span></a></section>' % (url(k, 'calc'), e(C['teaser_t']), e(C['teaser_p']), e(C['teaser_a'])))
    home_cases = [c for c in CASES if CASES[c][3]]
    o.append('<div class="fx-lit" id="fxLit"><section class="fx-sec" id="projekte"><h2>%s</h2>' % e(L['s_projects']))
    for i, c in enumerate(home_cases):
        o.append(photo_case(k, c, False, artist=(i == len(home_cases) - 1)))
    o.append('<p class="fx-more"><a href="%s">%s →</a></p></section>' % (url(k, 'projects'), e(L['all_projects'])))
    o.append('<section class="fx-sec" id="arbeiten"><h2>%s</h2>%s</section></div>' % (e(L['s_gallery']), works_grid(k, HOME_WORKS)))
    o.append('<section class="fx-sec" id="stimmen"><h2>%s</h2><div class="fx-voices">' % e(L['s_voices']))
    for q, n, r, im, tr in VOICES:
        t = '<p class="fx-tr"><span>%s:</span> %s</p>' % (e(L['translated']), e(tr[k])) if k in tr else ''
        o.append('<blockquote class="fx-voice"><p lang="de">„%s“</p>%s<footer><img loading="lazy" src="%s" alt="%s"><span><b>%s</b><br><span lang="de">%s</span></span></footer></blockquote>' % (e(q), t, old(im), e(n), e(n), e(r)))
    o.append('</div></section>')
    o.append('<section class="fx-sec" id="partner"><h2>%s</h2><div class="fx-logos"><img loading="lazy" src="%s" alt="%s"></div></section>' % (e(L['s_partners']), img('partner-kunden-logos'), e(L['partners_alt'])))
    o.append('<section class="fx-sec" id="presse"><h2>%s</h2>%s</section>' % (e(L['s_press']), press_cards(k, [p for p in PRESS if p['home']])))
    o.append('<section class="fx-sec" id="ablauf"><h2>%s</h2><ol class="fx-steps">%s</ol></section>' % (e(L['s_process']), ''.join('<li><b>%s</b><span>%s</span></li>' % (e(a), e(b)) for a, b in L['steps'])))
    o.append('<section class="fx-sec fx-about-sec" id="ueber"><img class="fx-about-img" loading="lazy" src="%s" alt="%s"><div><h2>%s</h2><p class="fx-about">%s</p><a class="fx-btn fx-btn-ghost" href="%s">%s →</a></div></section>' % (
        img('slavik-portrait'), e(L['a_h1']), e(L['s_about']), e(L['about']), url(k, 'about'), e(L['about_more'])))
    o.append('<section class="fx-sec" id="faq"><h2>%s</h2>%s</section>' % (e(L['s_faq']), ''.join('<details class="fx-faq"><summary>%s</summary><p>%s</p></details>' % (e(q), e(a)) for q, a in L['faq'])))
    o.append(contact_open(k))
    graph = ld_base(k) + [{'@type': 'WebPage', '@id': url(k, 'home'), 'name': L['meta_home'][0], 'description': L['meta_home'][1], 'inLanguage': k, 'about': {'@id': SITE + '#farbaholix'}},
                          {'@type': 'FAQPage', 'mainEntity': [{'@type': 'Question', 'name': q, 'acceptedAnswer': {'@type': 'Answer', 'text': a}} for q, a in L['faq']]}]
    return '\n'.join(o), graph

def page_projects(k):
    L = LANGS[k]; o = chrome_top(k, 'projects', True)
    o.append('<div class="fx-lit fx-lit-page" id="fxLit"><section class="fx-sec fx-page-head"><h1>%s</h1><p class="fx-lead">%s</p></section><section class="fx-sec">' % (e(L['p_title']), e(L['p_lead'])))
    for c in CASES:
        o.append(photo_case(k, c, True))
    o.append('</section></div>')
    o.append(contact_open(k))
    works = [{'@type': 'VisualArtwork', 'name': L['cases'][c][0], 'description': L['cases'][c][1], 'artform': 'Mural', 'artMedium': 'Spray paint, acrylic',
              'creator': {'@id': SITE + '#slavik'}, 'locationCreated': {'@type': 'Place', 'name': CASE_PLACE[c]}, 'url': url(k, 'projects') + '#' + CASES[c][0],
              'image': image_obj(CASES[c][1], L['cases'][c][0])} for c in CASES]
    graph = ld_base(k) + [breadcrumb(k, L['p_title'], 'projects'),
                          {'@type': 'CollectionPage', '@id': url(k, 'projects'), 'name': L['meta_projects'][0], 'inLanguage': k, 'hasPart': works}]
    return '\n'.join(o), graph

def page_opening(k):
    L = LANGS[k]; o = chrome_top(k, 'opening', True)
    o.append('<div class="fx-lit fx-lit-page" id="fxLit"><section class="fx-sec fx-page-head"><p class="fx-tagline">%s</p><h1>%s</h1><p class="fx-lead fx-lead-left">%s</p>' % (e(L['o_title']), e(L['o_h1']), e(L['o_text'])))
    o.append('<a class="fx-btn" href="#kontakt">%s</a></section>' % e(L['o_cta']))
    o.append('<section class="fx-sec"><h2>%s</h2>%s</section>' % (e(L['o_works']), works_grid(k, OPENING_WORKS)))
    o.append('<section class="fx-sec"><h2>%s</h2><ul class="fx-list">%s</ul></section></div>' % (e(L['o_inc_t']), ''.join('<li>%s</li>' % e(x) for x in L['o_inc'])))
    o.append(contact_open(k))
    graph = ld_base(k) + [breadcrumb(k, L['o_title'], 'opening'),
                          {'@type': 'Service', 'name': L['o_title'], 'description': L['o_text'], 'provider': {'@id': SITE + '#farbaholix'}, 'areaServed': 'Frankfurt am Main', 'url': url(k, 'opening')}]
    return '\n'.join(o), graph

def page_about(k):
    L = LANGS[k]; o = chrome_top(k, 'about', True)
    o.append('<div class="fx-lit fx-lit-page" id="fxLit"><section class="fx-sec fx-page-head fx-about-head"><img class="fx-portrait" src="%s" alt="%s" fetchpriority="high"><div><p class="fx-tagline">%s</p><h1>%s</h1><p class="fx-lead fx-lead-left">%s</p></div></section>' % (
        img('slavik-portrait'), e(L['a_h1']), e(L['a_kicker']), e(L['a_h1']), e(L['a_lead'])))
    o.append('<section class="fx-sec"><dl class="fx-facts-table">%s</dl></section>' % ''.join('<div><dt>%s</dt><dd>%s</dd></div>' % (e(a), e(b)) for a, b in L['a_facts']))
    for i, (h, paras) in enumerate(L['a_sections']):
        o.append('<section class="fx-sec fx-text"><h2>%s</h2>%s</section>' % (e(h), ''.join('<p>%s</p>' % e(p) for p in paras)))
        if i == 0:
            o.append('<section class="fx-sec"><div class="fx-grid">%s</div></section>' % ''.join(
                '<figure class="fx-photo fx-photo-sm"><img loading="lazy" src="%s" alt="%s"><figcaption>%s</figcaption></figure>' % (img(key), e(alt), e(alt)) for key, alt in L['a_photos']))
    o.append('<section class="fx-sec"><h2>%s</h2><ol class="fx-timeline">%s</ol></section>' % (e(L['a_timeline_t']), ''.join('<li><b>%s</b><span>%s</span></li>' % (e(y), e(x)) for y, x in L['a_timeline'])))
    o.append('<section class="fx-sec"><blockquote class="fx-bigquote"><p>„%s“</p><cite>%s</cite></blockquote><img class="fx-signature" src="%s" alt="Slavik – Kalligrafie-Signatur"></section>' % (e(L['a_quote']), e(L['a_quote_src']), img('signatur-slavik-dunkel')))
    o.append('<section class="fx-sec"><h2>%s</h2>%s</section>' % (e(L['s_partners']), '<div class="fx-logos"><img loading="lazy" src="%s" alt="%s"></div>' % (img('partner-kunden-logos'), e(L['partners_alt']))))
    o.append('<section class="fx-sec"><h2>%s</h2>%s</section></div>' % (e(L['a_press_t']), press_cards(k, PRESS)))
    o.append(contact_open(k))
    person = ld_base(k)[1]
    person.update({'description': L['a_lead'], 'image': [img('slavik-portrait'), img('slavik-sankt-georgen-monstera')]})
    graph = ld_base(k)[::2] + [breadcrumb(k, L['a_kicker'], 'about'),
                               {'@type': 'ProfilePage', '@id': url(k, 'about'), 'name': L['meta_about'][0], 'inLanguage': k, 'mainEntity': person}]
    return '\n'.join(o), graph

def page_magazine(k):
    L = LANGS[k]; o = chrome_top(k, 'magazine', True)
    arts = [a for a in ARTICLES if a['lang'] == k]
    o.append('<div class="fx-lit fx-lit-page" id="fxLit"><section class="fx-sec fx-page-head"><h1>%s</h1><p class="fx-lead fx-lead-left">%s</p><ul class="fx-toc">%s</ul></section>' % (
        e(L['m_title']), e(L['m_lead']), ''.join('<li><a href="#%s">%s</a> <span>%s %s</span></li>' % (a['slug'], e(a['title']), e(L['m_planned']), fdate(k, a['date'])) for a in arts)))
    graph = ld_base(k) + [breadcrumb(k, L['m_title'], 'magazine')]
    for a in arts:
        body = a['body'].replace('{opening}', url(k, 'opening')).replace('{calc}', url(k, 'calc'))
        o.append('<article class="fx-sec fx-article" id="%s"><figure class="fx-photo"><img loading="lazy" src="%s" alt="%s"></figure><h2>%s</h2>%s</article>' % (
            a['slug'], img(a['image']), e(a['image_alt']), e(a['title']), body))
        graph.append({'@type': 'BlogPosting', 'headline': a['title'], 'description': a['desc'], 'inLanguage': k, 'datePublished': a['date'], 'keywords': ', '.join(a['keywords']),
                      'author': {'@id': SITE + '#slavik'}, 'publisher': {'@id': SITE + '#farbaholix'}, 'image': image_obj(a['image'], a['image_alt']), 'url': url(k, 'magazine') + '#' + a['slug']})
    o.append('<section class="fx-sec" id="projektberichte"><h2>%s</h2><div class="fx-press">%s</div></section>' % (e(L['s_projects']), ''.join(
        '<a class="fx-press-card" href="%s"><div class="fx-press-img"><img loading="lazy" src="%s" alt="%s"></div><div class="fx-press-body"><span class="fx-press-pub">%s</span><h3>%s</h3><span class="fx-press-meta">%s →</span></div></a>' % (
            url(k, c), img(CASE_PAGES[c]['hero']), e(CASE_PAGES[c]['t'][k]['h1']), e(CASE_PAGES[c]['t'][k]['kicker']), e(CASE_PAGES[c]['t'][k]['h1']), e(UI[k]['more'])) for c in ('georgen', 'fsv', 'wellen', 'braubach'))))
    o.append('</div>')
    o.append(contact_open(k))
    return '\n'.join(o), graph

CALC_JS_TEXT = {}

def page_calc(k):
    L = LANGS[k]; C = CALC[k]; o = chrome_top(k, 'calc', True)
    def chips(name, opts, default):
        return ''.join('<label class="fx-chip"><input type="radio" name="%s" value="%s"%s>%s</label>' % (name, v, ' checked' if v == default else '', e(t)) for v, t in opts)
    defaults = dict(what='indoor', detail='medium', height='h1', design='ours', surface='ready', when='normal')
    o.append('<div class="fx-lit fx-lit-page" id="fxLit"><section class="fx-sec fx-page-head"><p class="fx-tagline">%s</p><h1>%s</h1><p class="fx-lead fx-lead-left">%s</p></section>' % (e(C['kicker']), e(C['h1']), e(C['lead'])))
    q = C['q']
    f = ['<section class="fx-sec"><form class="fx-calc" id="fxCalc" onsubmit="return false">']
    f.append('<fieldset><legend>%s</legend><div class="fx-chips">%s</div></fieldset>' % (e(q['what']), chips('what', C['o']['what'], defaults['what'])))
    f.append('<fieldset><legend>%s <output id="fxAreaVal">20 m²</output></legend><input type="range" name="area" min="1" max="400" step="1" value="20" aria-label="%s"></fieldset>' % (e(q['area']), e(q['area'])))
    for n in ('detail', 'height', 'design', 'surface', 'when'):
        f.append('<fieldset><legend>%s</legend><div class="fx-chips">%s</div></fieldset>' % (e(q[n]), chips(n, C['o'][n], defaults[n])))
    f.append('<fieldset><legend>%s</legend><select name="where">%s</select></fieldset>' % (e(q['where']), ''.join('<option value="%s">%s</option>' % (v, e(t)) for v, t in C['o']['where'])))
    f.append('<fieldset><legend>%s</legend><div class="fx-chips fx-chips-col">%s</div></fieldset>' % (e(q['extras']), ''.join('<label class="fx-chip"><input type="checkbox" name="%s">%s</label>' % (v, e(t)) for v, t in C['extras'])))
    f.append('</form></section>')
    o.extend(f)
    o.append('<section class="fx-sec fx-calc-result"><div class="fx-result" id="fxCalcOut"><p class="fx-result-t">%s</p><p class="fx-price" id="fxPrice">–</p><p class="fx-net">%s · <span id="fxGross"></span></p><ul class="fx-rows" id="fxRows"></ul><p class="fx-note" id="fxDesignNote">%s</p><p class="fx-note">%s</p><button type="button" class="fx-btn fx-calc-send" id="fxCalcSend">%s</button><a class="fx-mail-alt" id="fxCalcMail" href="mailto:farbaholix@gmail.com">%s</a></div>'
             '<div class="fx-result fx-stop" id="fxCalcStop" hidden><p class="fx-price">🚽✋</p><h3>%s</h3><p>%s</p></div></section>' % (
             e(C['result_t']), e(C['net']), e(C['design_note']), e(C['disclaimer']), e(C['cta']), e(C['mail']), e(C['stop_t']), e(C['stop_p'])))
    o.append('<section class="fx-sec" id="faq"><h2>%s</h2>%s</section></div>' % (e(L['s_faq']), ''.join('<details class="fx-faq"><summary>%s</summary><p>%s</p></details>' % (e(a), e(b)) for a, b in C['faq'])))
    js_text = dict(locale=C['locale'], gross=C['gross'], net=C['net'], days=C['days'], daysUnit=C['daysUnit'], discRow=C['discRow'], uaRow=C['uaRow'],
                   minRow=C['minRow'], briefTitle=C['briefTitle'], briefPrice=C['briefPrice'], qArea=q['area'], q=q, payRows=C['payRows'], hiphopRow=C['hiphopRow'], wa=WA)
    CALC_JS_TEXT[k] = js_text
    o.append(contact_open(k))
    graph = ld_base(k) + [breadcrumb(k, C['kicker'], 'calc'),
                          {'@type': 'WebApplication', 'name': C['meta'][0], 'description': C['meta'][1], 'applicationCategory': 'BusinessApplication', 'operatingSystem': 'Any',
                           'offers': {'@type': 'Offer', 'price': '0', 'priceCurrency': 'EUR'}, 'url': url(k, 'calc'), 'inLanguage': k, 'provider': {'@id': SITE + '#farbaholix'}},
                          {'@type': 'FAQPage', 'mainEntity': [{'@type': 'Question', 'name': a, 'acceptedAnswer': {'@type': 'Answer', 'text': b}} for a, b in C['faq']]}]
    return '\n'.join(o), graph


def page_case(k, key):
    L = LANGS[k]; P = CASE_PAGES[key]; T = P['t'][k]; U = UI[k]; li = ('de', 'en', 'uk').index(k)
    o = chrome_top(k, key, True)
    cap = lambda im: CAP[im][li] if im in CAP else ''
    o.append('<div class="fx-lit fx-lit-page" id="fxLit"><article class="fx-report">')
    o.append('<section class="fx-sec fx-page-head"><nav class="fx-crumbs"><a href="%s">%s</a> › <a href="%s">%s</a></nav><p class="fx-tagline">%s</p><h1>%s</h1><p class="fx-lead fx-lead-left fx-answer">%s</p></section>' % (
        url(k, 'home'), e(L['breadcrumb_home']), url(k, 'projects'), e(L['p_title']), e(T['kicker']), e(T['h1']), e(T['lead'])))
    o.append('<section class="fx-sec"><figure class="fx-photo fx-report-hero"><a class="fx-lb" data-lb="report" href="%s" data-cap="%s"><img src="%s" alt="%s" fetchpriority="high"></a></figure>' % (
        img(P['hero']), e(cap(P['hero'])), img(P['hero']), e(T['focus'] + ' – ' + cap(P['hero']))))
    o.append('<div class="fx-facts-box"><h2 class="fx-facts-t">%s</h2><dl class="fx-facts">%s</dl></div></section>' % (e(U['facts_t']), ''.join('<div><dt>%s</dt><dd>%s</dd></div>' % (e(a), e(v)) for a, v in T['facts'])))
    for i, (h, parts) in enumerate(T['sections']):
        o.append('<section class="fx-sec fx-report-sec"><h2>%s</h2>%s</section>' % (e(h), ''.join(parts)))
        if i == 1 and P['wide']:
            o.append('<section class="fx-sec"><a class="fx-lb fx-wide" data-lb="report" href="%s" data-cap="%s"><img loading="lazy" src="%s" alt="%s"></a></section>' % (
                img(P['wide']), e(cap(P['wide'])), img(P['wide']), e(cap(P['wide']))))
    q, src = T['quote']
    o.append('<section class="fx-sec"><blockquote class="fx-quote"><p>„%s“</p><footer>%s</footer></blockquote></section>' % (e(q), e(src)) if k == 'de' else
             '<section class="fx-sec"><blockquote class="fx-quote"><p>“%s”</p><footer>%s</footer></blockquote></section>' % (e(q), e(src)))
    if T['review']:
        o.append('<section class="fx-sec"><h2>%s</h2><blockquote class="fx-voice"><p>%s</p><footer><span><b>%s</b></span></footer></blockquote></section>' % (e(U['review_t']), e(T['review'][0]), e(T['review'][1])))
    if P.get('video'):   # project video: vertical reel (tap = full screen) + two silent process loops
        Vd = P['video']
        exp = '<svg class="fx-vexp" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/></svg>'
        clips = ''.join('<button type="button" class="fx-vcard fx-vclip" data-video="%s" data-poster="%s" aria-label="%s"><video src="%s" poster="%s" muted loop playsinline preload="none" data-autoplay></video>%s</button>' % (
            img(v), img(p), e(U['video_play']), img(v), img(p), exp) for v, p in Vd.get('clips', []))
        o.append('<section class="fx-sec fx-vsec" id="video"><h2>%s</h2><div class="fx-vgrid"><button type="button" class="fx-vcard fx-vmain" data-video="%s" data-poster="%s" aria-label="%s">'
                 '<img loading="lazy" src="%s" alt="%s"><span class="fx-vplay" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M8 5.5v13l11-6.5z"/></svg></span><span class="fx-vlen">%s</span></button>'
                 '<div class="fx-vside"><p class="fx-vlead">%s</p>%s</div></div></section>' % (
            e(U['video_t']), img(Vd['src']), img(Vd['poster']), e(U['video_play']), img(Vd['poster']), e(MEDIA[Vd['src']].get('alt_de', '')), Vd.get('len', ''),
            e(U['video_lead']), ('<p class="fx-vclips-t">%s</p><div class="fx-vclips">%s</div>' % (e(U['video_clips']), clips)) if clips else ''))
    gal = [g for g in P['gallery'] if g != P['hero']]
    o.append('<section class="fx-sec" id="galerie"><h2>%s</h2><p class="fx-hint">%s</p><div class="fx-gal">%s</div></section>' % (
        e(T['gallery_t']), e(U['gallery_hint']), ''.join('<a class="fx-lb" data-lb="report" href="%s" data-cap="%s"><img loading="lazy" src="%s" alt="%s"></a>' % (
            img(g), e(cap(g)), img(g), e(MEDIA[g].get('alt_de', cap(g)) if k == 'de' else cap(g))) for g in gal)))
    o.append('<section class="fx-sec" id="quellen"><h2>%s</h2><ul class="fx-sources">%s</ul></section>' % (e(U['sources_t']), ''.join(
        ('<li><a href="%s" target="_blank" rel="noopener">%s</a></li>' % (u, e(t))) if u else '<li>%s</li>' % e(t) for t, u in T['sources'])))
    o.append('<section class="fx-sec" id="faq"><h2>%s</h2>%s</section>' % (e(U['faq_t']), ''.join('<details class="fx-faq"><summary>%s</summary><p>%s</p></details>' % (e(a), e(b)) for a, b in T['faq'])))
    R = CASE_PAGES[P['related']]['t'][k]
    o.append('<section class="fx-sec"><div class="fx-report-cta"><h2>%s</h2><div class="fx-ctas"><a class="fx-btn" href="%s">%s →</a><a class="fx-btn fx-btn-ghost" href="#kontakt">%s</a></div></div>'
             '<p class="fx-report-next"><span>%s:</span> <a href="%s">%s →</a><br><a href="%s">← %s</a></p></section>' % (
             e(U['cta_t']), url(k, 'calc'), e(U['cta_calc']), e(U['cta_contact']), e(U['related']), url(k, P['related']), e(R['h1']), url(k, 'projects'), e(U['back'])))
    o.append('</article></div>')
    o.append(contact_open(k))
    page_url = url(k, key)
    graph = ld_base(k) + [
        {'@type': 'BreadcrumbList', 'itemListElement': [
            {'@type': 'ListItem', 'position': 1, 'name': L['breadcrumb_home'], 'item': url(k, 'home')},
            {'@type': 'ListItem', 'position': 2, 'name': L['p_title'], 'item': url(k, 'projects')},
            {'@type': 'ListItem', 'position': 3, 'name': T['h1'], 'item': page_url}]},
        {'@type': 'Article', '@id': page_url + '#article', 'headline': T['h1'], 'description': T['meta'][1], 'inLanguage': k, 'datePublished': P['date'], 'dateModified': '2026-09-30',
         'mainEntityOfPage': page_url, 'author': {'@id': SITE + '#slavik'}, 'publisher': {'@id': SITE + '#farbaholix'},
         'image': [img(P['hero'])] + [img(g) for g in gal[:6]], 'about': {'@type': 'CreativeWork', 'name': T['h1'], 'creator': {'@id': SITE + '#slavik'}},
         'citation': [u for t, u in T['sources'] if u]},
        {'@type': 'FAQPage', 'mainEntity': [{'@type': 'Question', 'name': a, 'acceptedAnswer': {'@type': 'Answer', 'text': b}} for a, b in T['faq']]}]
    return '\n'.join(o), graph

BUILDERS = dict(wellen=lambda k: page_case(k, 'wellen'), braubach=lambda k: page_case(k, 'braubach'), fsv=lambda k: page_case(k, 'fsv'), georgen=lambda k: page_case(k, 'georgen'), calc=page_calc, home=page_home, projects=page_projects, opening=page_opening, about=page_about, magazine=page_magazine)

def wrap(k, top, graph, page=None):
    css, js = open('fx.css').read(), open('fx.js').read()
    if page == 'calc': js += '\nvar FX_CALC_TEXT = ' + json.dumps(CALC_JS_TEXT[k], ensure_ascii=False) + ';\n' + open('calc.js').read()
    # scripts ship base64-encoded so WordPress' texturize can never alter them
    js64 = base64.b64encode(js.encode('utf-8')).decode('ascii')
    wp = ('<!-- wp:html -->\n<style>%s</style>\n%s\n%s\n%s\n<script src="data:text/javascript;base64,%s"></script>\n<!-- /wp:html -->') % (css, ld_script(graph), top, chrome_bottom(k), js64)
    local = ('<!doctype html><html lang="%s"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body>'
             '<style>%s</style>%s%s<script>%s</script></body></html>') % (k, css, top, chrome_bottom(k), js)
    return wp, local

if __name__ == '__main__':
    for k in LANGS:
        for name in PAGES:
            top, graph = BUILDERS[name](k)
            wp, local = wrap(k, top, graph, name)
            open('page_%s_%s.txt' % (name, k), 'w').write(wp)
            open('local_%s_%s.html' % (name, k), 'w').write(local)
            print(name, k, len(wp))
