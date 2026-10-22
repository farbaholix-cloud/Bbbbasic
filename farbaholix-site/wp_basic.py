"""WP REST client with an application password (Basic Auth) – works when the cookie login (wp.py) is not available.
FX_WP_USER / FX_WP_APP_PASS from the environment, never committed."""
import base64, json, mimetypes, os, urllib.request, urllib.error
SITE = 'https://farbaholix.de'

class WPBasic:
    def __init__(self, user=None, app_pass=None):
        u = user or os.environ['FX_WP_USER']; p = app_pass or os.environ['FX_WP_APP_PASS']
        self.auth = 'Basic ' + base64.b64encode(('%s:%s' % (u, p)).encode()).decode()
    def req(self, method, path, body=None):
        r = urllib.request.Request(SITE + '/wp-json/' + path, data=json.dumps(body).encode() if body is not None else None, method=method,
                                   headers={'Authorization': self.auth, 'Content-Type': 'application/json'})
        try:
            return json.loads(urllib.request.urlopen(r, timeout=90).read())
        except urllib.error.HTTPError as e:
            return {'error': e.code, 'body': e.read().decode()[:300]}
    def upload(self, path, alt, title=None):
        name = os.path.basename(path); ctype = mimetypes.guess_type(name)[0] or 'application/octet-stream'
        r = urllib.request.Request(SITE + '/wp-json/wp/v2/media', data=open(path, 'rb').read(), method='POST',
                                   headers={'Authorization': self.auth, 'Content-Type': ctype, 'Content-Disposition': 'attachment; filename="%s"' % name})
        m = json.loads(urllib.request.urlopen(r, timeout=120).read())
        self.req('POST', 'wp/v2/media/%d' % m['id'], {'alt_text': alt, 'title': title or alt.split(' – ')[0][:90]})
        return m
