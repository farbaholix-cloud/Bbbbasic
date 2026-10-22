"""One-off: publish the SHIFT Summit page (DE/EN/UK) – upload the photos, create the three pages, link the translations,
set Rank Math SEO and deploy the content.  Safe to run again: existing media keys and page ids are reused.
Needs FX_WP_USER / FX_WP_PASS.   Usage:  python3 shift_publish.py"""
import json, subprocess, sys
from wp import WP
import lang
from shift import UI

PHOTOS = {  # media key → (file in media-new/, German alt text)
    'shift-leinwand-detail': ('media-new/kalligrafie-leinwand-shift-summit-farbaholix.webp',
                              'Kalligrafie-Leinwand für die Benefiz-Auktion beim SHIFT Summit – Farbaholix und Wolodymyr Wlastin'),
    'shift-zeichen': ('media-new/zeichen-farbaholix-relationing-shift-summit.webp',
                      'Zeichen auf der Leinwand beim SHIFT Summit: Monogramm Farbaholix, Logo Relationing'),
}
SLUG = {'de': 'shift-summit', 'en': 'shift-summit-en', 'uk': 'shift-summit-uk'}

w = WP()
media = json.load(open('media_seo.json'))
for key, (path, alt) in PHOTOS.items():
    if key not in media:
        m = w.upload(path, alt)
        media[key] = {'id': m['id'], 'url': m['source_url'], 'alt_de': alt}
        print('uploaded', key, m['source_url'])
json.dump(media, open('media_seo.json', 'w'), ensure_ascii=False, indent=1)

ids = json.load(open('page_ids.json'))
for k in ('de', 'en', 'uk'):
    key = 'shift_' + k
    if key not in ids:
        r = w.req('POST', 'wp/v2/pages', {'slug': SLUG[k], 'title': UI[k]['crumb'], 'template': 'elementor_canvas', 'status': 'publish', 'content': ''})
        if 'id' not in r: sys.exit('create %s failed: %s' % (key, r))
        ids[key] = r['id']; print('created', key, r['id'], r.get('link'))
json.dump(ids, open('page_ids.json', 'w'), indent=1)

tr = {k: ids['shift_' + k] for k in ('de', 'en', 'uk')}
for k, pid in tr.items():
    lang.set_lang(w, pid, k, tr)
    w.req('POST', 'wp/v2/pages/%d' % pid, {'title': UI[k]['crumb'], 'slug': SLUG[k]})  # the classic form must never leave the title empty
    title, desc, kw = UI[k]['meta']
    r = w.req('POST', 'rankmath/v1/updateMeta', {'objectType': 'post', 'objectID': pid, 'meta': {
        'rank_math_robots': ['index', 'follow'], 'rank_math_title': title, 'rank_math_description': desc, 'rank_math_focus_keyword': kw}})
    print('lang+seo', k, pid, 'ok' if 'error' not in r else r)

subprocess.run([sys.executable, 'deploy.py', 'shift'], check=True)
print('live:', 'https://farbaholix.de/shift-summit/')
