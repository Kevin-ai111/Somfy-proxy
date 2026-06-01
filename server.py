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
CACHE_TTL = int(os.environ.get('CACHE_TTL', 7 * 24 * 3600))  # 7 Tage default

# In-Memory Cache: { url_hash: { text, pages, screenshot, timestamp } }
cache = {}

RELEVANT_SLUGS = [
    'referenz', 'referenzen', 'partner', 'partners', 'hersteller',
    'produkt', 'produkte', 'produktwelt', 'sortiment', 'marken',
    'leistung', 'leistungen', 'service', 'services',
    'lieferant', 'lieferanten', 'kooperationen', 'kooperation',
    'ueber-uns', 'ueber', 'uber-uns', 'about', 'unternehmen',
    'team', 'galerie', 'gallery', 'projekte', 'projekt',
    'shop', 'onlineshop', 'katalog',
]

def url_key(url):
    return hashlib.md5(url.strip().lower().encode()).hexdigest()

def cache_get(url):
    key = url_key(url)
    entry = cache.get(key)
    if entry and (time.time() - entry['ts']) < CACHE_TTL:
        age_h = int((time.time() - entry['ts']) / 3600)
        print(f"  ✓ Cache-Hit ({age_h}h alt): {url}")
        return entry
    return None

def cache_set(url, data):
    key = url_key(url)
    cache[key] = {**data, 'ts': time.time(), 'url': url}

def cache_stats():
    total = len(cache)
    valid = sum(1 for e in cache.values() if (time.time() - e['ts']) < CACHE_TTL)
    return {'total': total, 'valid': valid, 'expired': total - valid}

def extract_text(html):
    if USE_BS4:
        soup = BeautifulSoup(html, 'html.parser')
        for tag in soup(['script','style','noscript','meta','link']):
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

def find_relevant_links(html, base_url):
    found = []
    base = urllib.parse.urlparse(base_url)
    base_origin = f"{base.scheme}://{base.netloc}"
    if USE_BS4:
        soup = BeautifulSoup(html, 'html.parser')
        links = [a.get('href','') for a in soup.find_all('a', href=True)]
    else:
        links = re.findall(r'href=["\']([^"\']+)["\']', html, re.IGNORECASE)
    seen = set()
    for href in links:
        href = href.strip()
        if not href or href.startswith('#') or href.startswith('mailto:') or href.startswith('tel:'):
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
        path_lower = parsed.path.lower().rstrip('/')
        if any(s in path_lower for s in RELEVANT_SLUGS) and full not in seen:
            seen.add(full)
            found.append(full)
    return found[:8]

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
    print(f"    Startseite: {url}")
    main_html = fetch_url(url)
    main_text = extract_text(main_html)
    results[url] = main_text
    subpages = find_relevant_links(main_html, url)
    print(f"    Unterseiten gefunden: {len(subpages)}")
    for sub_url in subpages:
        if len(results) >= 6:
            break
        try:
            print(f"    Unterseite: {sub_url}")
            html = fetch_url(sub_url, timeout=8)
            text = extract_text(html)
            if text and len(text) > 100:
                results[sub_url] = text
        except Exception as e:
            print(f"    ✗ {sub_url}: {e}")
    per_page_limit = max(1500, 6000 // len(results))
    combined = []
    for page_url, text in results.items():
        slug = urllib.parse.urlparse(page_url).path.strip('/') or 'startseite'
        combined.append(f"=== {slug} ===\n{text[:per_page_limit]}")
    full_text = '\n\n'.join(combined)
    print(f"    ✓ {len(full_text)} Zeichen aus {len(results)} Seiten")
    return full_text, list(results.keys())

def fetch_screenshot(url):
    if not url.startswith('http'):
        url = 'https://' + url
    ss_url = f"https://api.screenshotone.com/take?url={urllib.parse.quote(url)}&format=png&viewport_width=1280&viewport_height=900&image_quality=80&block_ads=true&block_cookie_banners=true&access_key=free"
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
                entries.append({'url': e.get('url','?'), 'age_h': age_h, 'valid': age_h * 3600 < CACHE_TTL})
            self._json({'stats': cache_stats(), 'entries': entries})
            return

        if path == '/cache/clear':
            url_param = params.get('url', [''])[0]
            if url_param:
                # Einzelne URL löschen
                key = url_key(url_param)
                if key in cache:
                    del cache[key]
                    print(f"  Cache gelöscht: {url_param}")
                    self._json({'ok': True, 'cleared': 1})
                else:
                    self._json({'ok': True, 'cleared': 0, 'msg': 'Nicht im Cache'})
            else:
                # Alles löschen
                count = len(cache)
                cache.clear()
                print(f"  Cache komplett geleert ({count} Einträge)")
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
            print(f"\n  Screenshot: {url}")
            try:
                b64 = fetch_screenshot(url)
                # Screenshot in Cache mergen falls fetch-Eintrag existiert
                key = url_key(url)
                if key in cache:
                    cache[key]['screenshot'] = b64
                print(f"  ✓ Screenshot ok")
                self._json({'image': b64, 'ok': True, 'from_cache': False})
            except Exception as e:
                print(f"  ✗ Screenshot: {e}")
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

        # Cache prüfen
        cached = cache_get(url)
        if cached:
            self._json({'text': cached['text'], 'pages': cached['pages'], 'ok': True, 'from_cache': True})
            return

        print(f"\n  Fetche (neu): {url}")
        try:
            text, pages = fetch_website_deep(url)
            cache_set(url, {'text': text, 'pages': pages, 'screenshot': None})
            self._json({'text': text, 'pages': pages, 'ok': True, 'from_cache': False})
        except Exception as e:
            print(f"  ✗ {e}")
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
    print(f"Somfy Proxy-Server läuft auf Port {PORT}")
    print(f"Cache TTL: {CACHE_TTL // 3600}h")
    server = http.server.HTTPServer(('0.0.0.0', PORT), Handler)
    server.serve_forever()
