"""Logged-in WordPress session for farbaholix.de. Credentials come from the environment, never from the repo:
FX_WP_USER / FX_WP_PASS (an administrator account)."""
import json, os, urllib.request, urllib.parse, http.cookiejar
SITE = 'https://farbaholix.de'

def session(user, pw):
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.addheaders = [('User-Agent', 'Mozilla/5.0 fx-deploy')]
    op.open(SITE + '/wp-login.php').read()
    op.open(SITE + '/wp-login.php', urllib.parse.urlencode({'log': user, 'pwd': pw, 'wp-submit': 'Log In', 'redirect_to': SITE + '/wp-admin/', 'testcookie': '1'}).encode()).read()
    nonce = op.open(SITE + '/wp-admin/admin-ajax.php?action=rest-nonce').read().decode().strip()   # "0" means the login failed
    if nonce in ('0', '-1'): raise SystemExit('WordPress login failed – check FX_WP_USER / FX_WP_PASS')
    return op, nonce

class WP:
    def __init__(self, user=None, pw=None):
        self.op, self.nonce = session(user or os.environ['FX_WP_USER'], pw or os.environ['FX_WP_PASS'])
    def req(self, method, path, body=None):
        r = urllib.request.Request(SITE + '/wp-json/' + path, data=json.dumps(body).encode() if body is not None else None, method=method,
                                   headers={'X-WP-Nonce': self.nonce, 'Content-Type': 'application/json'})
        try:
            return json.loads(self.op.open(r, timeout=60).read())
        except urllib.error.HTTPError as e:
            return {'error': e.code, 'body': e.read().decode()[:300]}
    def upload(self, path, alt, title=None):
        name = os.path.basename(path); ctype = 'image/webp' if name.endswith('.webp') else 'image/jpeg' if name.endswith('.jpg') else 'image/png'
        r = urllib.request.Request(SITE + '/wp-json/wp/v2/media', data=open(path, 'rb').read(), method='POST',
                                   headers={'X-WP-Nonce': self.nonce, 'Content-Type': ctype, 'Content-Disposition': 'attachment; filename="%s"' % name})
        m = json.loads(self.op.open(r, timeout=120).read())
        self.req('POST', 'wp/v2/media/%d' % m['id'], {'alt_text': alt, 'title': title or alt.split(' – ')[0][:90]})
        return m
