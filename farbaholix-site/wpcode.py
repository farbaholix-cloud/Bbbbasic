"""Save a PHP snippet to WPCode (plugin 'insert-headers-and-footers') through its admin form.
   python3 wpcode.py            → pushes wp-snippets/fx-contact.php to snippet 918"""
import re, sys, urllib.parse
from wp import WP, SITE

SNIPPETS = {918: ('wp-snippets/fx-contact.php', 'Farbaholix Kontakt-Hub (Formular, WhatsApp, Telegram)')}

def save(w, sid, path, title):
    page = SITE + '/wp-admin/admin.php?page=wpcode-snippet-manager&snippet_id=%d' % sid
    h = w.op.open(page).read().decode()
    nonce = re.search(r'name="wpcode-save-snippet-nonce" value="([^"]+)"', h).group(1)
    data = urllib.parse.urlencode({'wpcode-save-snippet-nonce': nonce, '_wp_http_referer': '/wp-admin/admin.php?page=wpcode-snippet-manager&snippet_id=%d' % sid,
        'id': sid, 'wpcode_snippet_title': title, 'wpcode_snippet_type': 'php', 'wpcode_snippet_code': open(path).read(),
        'wpcode_auto_insert': '1', 'wpcode_auto_insert_location': 'everywhere', 'wpcode_active': '1', 'wpcode_priority': '10',
        'wpcode_note': 'Managed by farbaholix-site/' + path, 'button': 'publish'}).encode()
    r = w.op.open(page, data)
    body = r.read().decode()
    err = re.findall(r'class="notice[^"]*error[^"]*"[^>]*>([\s\S]{0,600}?)</div>', body)
    active = re.search(r'name="wpcode_active"[^>]*checked', body) is not None
    return r.geturl()[-60:], [re.sub('<[^>]+>', ' ', x).strip()[:300] for x in err], active

if __name__ == '__main__':
    w = WP()
    for sid, (path, title) in SNIPPETS.items():
        print(sid, save(w, sid, path, title))
