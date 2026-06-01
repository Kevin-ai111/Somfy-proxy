import http.server
import urllib.request
import urllib.error
import urllib.parse
import json
import re
import os
import time
import hashlib
import base64

try:
    from bs4 import BeautifulSoup
    USE_BS4 = True
except ImportError:
    USE_BS4 = False

PORT = int(os.environ.get('PORT', 7723))
CACHE_TTL = int(os.environ.get('CACHE_TTL', 7 * 24 * 3600))

cache = {}

RELEVANT_SLUGS = [
    'antrieb', 'antriebe', 'steuerung', 'motor', 'motoren', 'automation',
    'smart-home', 'smarthome', 'hausautomation', 'automatisierung',
    'rollladen', 'rolladen', 'sonnenschutz', 'markise', 'markisen',
    'jalousie', 'jalousien', 'raffstore', 'raffstores', 'rollo', 'rollos',
    'insektenschutz', 'plissee', 'verdunklung',
    'produkt', 'produkte', 'produktwelt', 'sortiment', 'marken', 'hersteller',
    'lieferant', 'lieferanten', 'partner', 'partners', 'kooperation',
    'katalog', 'shop', 'onlineshop',
    'referenz', 'referenzen', 'projekt', 'projekte', 'galerie', 'gallery',
    'beispiel', 'beispiele', 'portfolio',
    'leistung', 'leistungen', 'service', 'services', 'montage',
    'einbau', 'installation', 'beratung',
    'ueber-uns', 'ueber', 'uber-uns', 'about', 'unternehmen', 'firma',
    'team', 'wir-fuer-sie', 'wir-fuer-euch',
    'tor', 'tore', 'garagentor', 'sektionaltor', 'carport',
]

def url_key(url):
    return hashlib.md5(url.strip().lower().encode()).hexdigest()

def cache_get(url):
    key = url_key(url)
    entry = cache.get(key)
    if entry and (time.time() - entry['ts']) < CACHE_TTL:
        age_h = int((time.time() - entry['ts']) / 3600)
        print("  Cache-Hit ({}h alt): {}".format(age_h, url))
        return entry
    return None

def cache_set(url, data):
    key = url_key(url)
    cache[key] = dict(data)
    cache[key]['ts'] = time.time()
    cache[key]['url'] = url

def cache_stats():
    total = len(cache)
    valid = sum(1 for e in cache.values() if (time.time() - e['ts']) < CACHE_TTL)
    return {'total': total, 'valid': valid, 'expired': total - valid}

def extract_text(html):
    if USE_BS4:
        soup = BeautifulSoup(html, 'html.parser')
        for tag in soup(['script', 'style', 'noscript', 'meta', 'link']):
            tag.decompose()
        text = soup.get_text(separator='\n')
    else:
        text = re.sub(r'<script[\s\S]*?</script>', '', html, flags=re.IGNORECASE)
        text = re.sub(r'<style[\s\S]*?</style>', '', text, flags=re.IGNORECASE)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'&[a-zA-Z#0-9]+;', ' ', text)
    text = re.sub(r'[ \t]{3,}', ' ', text)
    text = re.sub(r'\n{4,}', '\n\n', text)
    return text.strip()

def score_link(path):
    path_lower = path.lower().rstrip('/')
    score = 0
    for slug in RELEVANT_SLUGS:
        if slug in path_lower:
            score += 10
            break
    depth = path_lower.count('/')
    score -= depth
    return score

def find_relevant_links(html, base_url, bonus=0):
    base = urllib.parse.urlparse(base_url)
    base_origin = "{}://{}".format(base.scheme, base.netloc)

    all_hrefs = []

    if USE_BS4:
        soup = BeautifulSoup(html, 'html.parser')
        nav_hrefs = []
        for nav in soup.find_all(['nav', 'header']):
            for a in nav.find_all('a', href=True):
                nav_hrefs.append((a['href'], 5))
        body_hrefs = []
        for a in soup.find_all('a', href=True):
            body_hrefs.append((a['href'], 0))
        all_hrefs = nav_hrefs + body_hrefs
    else:
        hrefs = re.findall(r'href=["\']([^"\'> ]+)["\']', html, re.IGNORECASE)
        all_hrefs = [(h, 0) for h in hrefs]

    seen = set()
    scored = []
    file_ext = re.compile(r'\.(pdf|jpg|jpeg|png|gif|svg|css|js|xml|zip|ico)$', re.I)

    for href, link_bonus in all_hrefs:
        href = href.strip()
        if not href:
            continue
        if href.startswith('#') or href.startswith('mailto:') or href.startswith('tel:') or href.startswith('javascript:'):
            continue
        if file_ext.search(href):
            continue
        if href.startswith('http'):
            full = href
        elif href.startswith('/'):
            full = base_origin + href
        else:
            full = base_origin + '/' + href
        parsed = urllib.parse.urlparse(full)
        if parsed.netloc != base.netloc:
            continue
        path = parsed.path.rstrip('/')
        if not path or full in seen:
            continue
        seen.add(full)
        s = score_link(path) + link_bonus + bonus
        if s > 0:
            scored.append((s, full))

    scored.sort(key=lambda x: -x[0])
    return [url for _, url in scored[:10]]

def fetch_url(url, timeout=10):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'de-DE,de;q=0.9,en;q=0.8',
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            enc = resp.headers.get_content_charset() or 'utf-8'
            return raw.decode(enc, errors='replace')
    except Exception:
        url_http = url.replace('https://', 'http://', 1)
        req2 = urllib.request.Request(url_http, headers=headers)
        with urllib.request.urlopen(req2, timeout=timeout) as resp:
            raw = resp.read()
            enc = resp.headers.get_content_charset() or 'utf-8'
            return raw.decode(enc, errors='replace')

def fetch_website_deep(url):
    if not url.startswith('http'):
        url = 'https://' + url
    results = {}

    print("    Startseite: {}".format(url))
    main_html = fetch_url(url)
    main_text = extract_text(main_html)
    results[url] = main_text

    candidates = find_relevant_links(main_html, url)
    print("    Kandidaten: {}".format(len(candidates)))

    for sub_url in candidates:
        if len(results) >= 8:
            break
        try:
            print("    Crawle: {}".format(sub_url))
            html = fetch_url(sub_url, timeout=8)
            text = extract_text(html)
            if text and len(text) > 100:
                results[sub_url] = text
                sub_candidates = find_relevant_links(html, sub_url)
                for deep_url in sub_candidates[:3]:
                    if deep_url not in results and len(results) < 8:
                        try:
                            deep_html = fetch_url(deep_url, timeout=6)
                            deep_text = extract_text(deep_html)
                            if deep_text and len(deep_text) > 100:
                                results[deep_url] = deep_text
                                print("    Tiefe 2: {}".format(deep_url))
                        except Exception:
                            pass
        except Exception as e:
            print("    Fehler {}: {}".format(sub_url, e))

    per_page_limit = max(800, 8000 // len(results))
    combined = []
    for page_url, text in results.items():
        slug = urllib.parse.urlparse(page_url).path.strip('/') or 'startseite'
        combined.append("=== {} ===\n{}".format(slug, text[:per_page_limit]))
    full_text = '\n\n'.join(combined)
    print("    Gesamt: {} Zeichen aus {} Seiten".format(len(full_text), len(results)))
    return full_text, list(results.keys())

def fetch_screenshot(url):
    if not url.startswith('http'):
        url = 'https://' + url
    ss_url = "https://api.screenshotone.com/take?url={}&format=png&viewport_width=1280&viewport_height=900&image_quality=80&block_ads=true&block_cookie_banners=true&access_key=free".format(
        urllib.parse.quote(url)
    )
    req = urllib.request.Request(ss_url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=15) as resp:
        img_data = resp.read()
        return base64.b64encode(img_data).decode('utf-8')

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        path = parsed.path

        if path == '/health':
            self._json({'status': 'ok', 'cache': cache_stats()})
            return

        if path == '/cache/stats':
            entries = []
            for e in sorted(cache.values(), key=lambda x: x['ts'], reverse=True):
                age_h = round((time.time() - e['ts']) / 3600, 1)
                entries.append({'url': e.get('url', '?'), 'age_h': age_h, 'valid': (age_h * 3600) < CACHE_TTL})
            self._json({'stats': cache_stats(), 'entries': entries})
            return

        if path == '/cache/clear':
            url_param = params.get('url', [''])[0]
            if url_param:
                key = url_key(url_param)
                if key in cache:
                    del cache[key]
                    self._json({'ok': True, 'cleared': 1})
                else:
                    self._json({'ok': True, 'cleared': 0})
            else:
                count = len(cache)
                cache.clear()
                print("  Cache geleert ({} Eintraege)".format(count))
                self._json({'ok': True, 'cleared': count})
            return

        if path == '/screenshot':
            url = params.get('url', [''])[0]
            if not url:
                self._json({'error': 'Kein URL'}, 400)
                return
            cached = cache_get(url)
            if cached and cached.get('screenshot'):
                self._json({'image': cached['screenshot'], 'ok': True, 'from_cache': True})
                return
            print("\n  Screenshot: {}".format(url))
            try:
                b64 = fetch_screenshot(url)
                key = url_key(url)
                if key in cache:
                    cache[key]['screenshot'] = b64
                self._json({'image': b64, 'ok': True, 'from_cache': False})
            except Exception as e:
                print("  Screenshot Fehler: {}".format(e))
                self._json({'ok': False, 'error': str(e)})
            return

        if path != '/fetch':
            self.send_response(404)
            self._cors()
            self.end_headers()
            return

        url = params.get('url', [''])[0]
        if not url:
            self._json({'error': 'Kein URL'}, 400)
            return

        cached = cache_get(url)
        if cached:
            self._json({'text': cached['text'], 'pages': cached['pages'], 'ok': True, 'from_cache': True})
            return

        print("\n  Fetche (neu): {}".format(url))
        try:
            text, pages = fetch_website_deep(url)
            cache_set(url, {'text': text, 'pages': pages, 'screenshot': None})
            self._json({'text': text, 'pages': pages, 'ok': True, 'from_cache': False})
        except Exception as e:
            print("  Fehler: {}".format(e))
            self._json({'error': str(e), 'ok': False})

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', '*')

    def _json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self._cors()
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

if __name__ == '__main__':
    print("Somfy Proxy-Server laeuft auf Port {}".format(PORT))
    print("Cache TTL: {}h".format(CACHE_TTL // 3600))
    server = http.server.HTTPServer(('0.0.0.0', PORT), Handler)
    server.serve_forever()
