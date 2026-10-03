"""Build all pages and push them to WordPress.  Usage:  python3 deploy.py [page ...]   e.g.  python3 deploy.py home fsv
Needs FX_WP_USER / FX_WP_PASS.  Only page content is updated; slugs, languages and SEO meta are set once (see SKILL.md)."""
import json, os, subprocess, sys
from wp import WP
subprocess.run([sys.executable, 'build.py'], check=True, stdout=subprocess.DEVNULL)
only = set(sys.argv[1:])
w = WP(); ids = json.load(open('page_ids.json')); bad = []
for key, pid in ids.items():
    page, k = key.rsplit('_', 1)
    if only and page not in only: continue
    if not os.path.exists('page_%s_%s.txt' % (page, k)): print('skip', key, '(no local build – e.g. archive missing)'); continue
    r = w.req('POST', 'wp/v2/pages/%d' % pid, {'content': open('page_%s_%s.txt' % (page, k)).read()})
    print('ok ' if 'id' in r else 'ERR', key, pid, r.get('error', ''))
    if 'id' not in r: bad.append(key)
sys.exit(1 if bad else 0)
