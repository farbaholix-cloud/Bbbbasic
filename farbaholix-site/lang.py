import re, urllib.parse
from wp import SITE
def set_lang(w, pid, lang, tr):
    """tr: {lang: post_id} translations incl. itself"""
    h = w.op.open(SITE + '/wp-admin/post.php?post=%d&action=edit' % pid).read().decode()
    nonce = re.search(r'name="_wpnonce" value="([^"]+)', h).group(1)
    pll = re.search(r'name="_pll_nonce" value="([^"]+)', h)
    f = [('_wpnonce', nonce), ('action', 'editpost'), ('post_ID', str(pid)), ('post_type', 'page'), ('originalaction', 'editpost'),
         ('post_lang_choice', lang)]
    if pll: f.append(('_pll_nonce', pll.group(1)))
    for l, i in tr.items():
        if l != lang: f.append(('post_tr_lang[%s]' % l, str(i)))
    w.op.open(SITE + '/wp-admin/post.php', urllib.parse.urlencode(f).encode()).read()
