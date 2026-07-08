import http.server
import urllib.request
import urllib.parse
import json
import re
import os
import time
import hashlib
import concurrent.futures

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
        print("  Cache-Hit ({}h): {}".format(age_h, url))
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

# Seiten die besonders wahrscheinlich Mitarbeiterzahlen enthalten
EMPLOYEE_SLUGS = [
    'team', 'ueber-uns', 'ueber', 'uber-uns', 'about', 'about-us',
    'unternehmen', 'firma', 'wir', 'wir-ueber-uns', 'wir-fuer-sie',
    'portrait', 'profil', 'geschichte', 'mitarbeiter', 'jobs', 'karriere',
    'impressum',
]

# Seiten mit Antrieben/Steuerung = höchste Priorität für Wettbewerber-Erkennung
HIGH_VALUE_SLUGS = [
    'smart-home', 'smarthome', 'steuerung', 'steuerungen', 'antrieb', 'antriebe',
    'automation', 'partner', 'hersteller', 'marken',
]

def score_link(path):
    path_lower = path.lower().rstrip('/')
    score = 0
    # Smart-Home / Steuerung / Antriebe = höchste Prio (dort stehen Antriebshersteller)
    for slug in HIGH_VALUE_SLUGS:
        if slug in path_lower:
            score += 30
            break
    # Mitarbeiter-relevante Seiten
    for slug in EMPLOYEE_SLUGS:
        if slug in path_lower:
            score += 20
            break
    # Sonstige relevante Seiten
    for slug in RELEVANT_SLUGS:
        if slug in path_lower:
            score += 10
            break
    score -= path_lower.count('/')
    return score

def find_relevant_links(html, base_url):
    base = urllib.parse.urlparse(base_url)
    base_origin = "{}://{}".format(base.scheme, base.netloc)
    all_hrefs = []
    file_ext = re.compile(r'\.(pdf|jpg|jpeg|png|gif|svg|css|js|xml|zip|ico|woff|ttf)$', re.I)

    if USE_BS4:
        soup = BeautifulSoup(html, 'html.parser')
        for nav in soup.find_all(['nav', 'header']):
            for a in nav.find_all('a', href=True):
                all_hrefs.append((a['href'], 5))
        for a in soup.find_all('a', href=True):
            all_hrefs.append((a['href'], 0))
    else:
        hrefs = re.findall(r'href=["\']([^"\'> ]+)["\']', html, re.IGNORECASE)
        all_hrefs = [(h, 0) for h in hrefs]

    seen = set()
    scored = []
    for href, bonus in all_hrefs:
        href = href.strip()
        if not href or href.startswith('#') or href.startswith('mailto:') \
           or href.startswith('tel:') or href.startswith('javascript:'):
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
        s = score_link(path) + bonus
        if s > 0:
            scored.append((s, full))

    scored.sort(key=lambda x: -x[0])
    return [url for _, url in scored[:15]]

def fetch_url(url, timeout=10):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'de-DE,de;q=0.9,en;q=0.8',
    }
    # Redirects folgen (www -> non-www, http -> https etc.)
    opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler())
    urls_to_try = [url]
    if url.startswith('https://www.'):
        urls_to_try.append('https://' + url[12:])
    elif url.startswith('https://') and not url.startswith('https://www.'):
        urls_to_try.append('https://www.' + url[8:])
    if not url.startswith('http://'):
        urls_to_try.append(url.replace('https://', 'http://', 1))

    last_err = None
    for try_url in urls_to_try:
        try:
            req = urllib.request.Request(try_url, headers=headers)
            with opener.open(req, timeout=timeout) as resp:
                raw = resp.read()
                enc = resp.headers.get_content_charset() or 'utf-8'
                return raw.decode(enc, errors='replace')
        except Exception as e:
            last_err = e
            continue
    raise last_err

def fetch_single(args):
    sub_url, timeout = args
    try:
        html = fetch_url(sub_url, timeout=timeout)
        text = extract_text(html)
        if text and len(text) > 100:
            return sub_url, html, text
    except Exception as e:
        print("  Fehler {}: {}".format(sub_url, e))
    return sub_url, None, None

def fetch_google_reviews(name, address, api_key):
    if not api_key:
        return None
    try:
        query = "{} {}".format(name, address).strip()
        search_url = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json?input={}&inputtype=textquery&fields=place_id,name,rating,user_ratings_total&key={}".format(
            urllib.parse.quote(query), api_key
        )
        req = urllib.request.Request(search_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        candidates = data.get('candidates', [])
        if not candidates:
            return None
        place = candidates[0]
        return {
            'rating': place.get('rating'),
            'review_count': place.get('user_ratings_total'),
            'place_name': place.get('name', ''),
        }
    except Exception as e:
        print("  Google Places Fehler: {}".format(e))
        return None

SCREENSHOT_PRIORITY_SLUGS = [
    'partner', 'hersteller', 'marken', 'marke', 'lieferant',
    'kooperation', 'produkt', 'sortiment',
    'antrieb', 'steuerung', 'steuerungen', 'referenz',
    'smart-home', 'smarthome', 'smart', 'somfy',
    'rollladen', 'rolladen', 'markise', 'jalousie', 'raffstore', 'sonnenschutz',
]

def screenshot_score(url):
    """Hoeherer Score = wahrscheinlicher Logos/Marken. Somfy/Partner/Hersteller ganz oben."""
    path = urllib.parse.urlparse(url).path.lower()
    top = ['somfy', 'partner', 'hersteller', 'marken', 'marke', 'lieferant', 'steuerung', 'smart-home', 'smarthome', 'antrieb']
    mid = ['produkt', 'sortiment', 'kooperation']
    low = ['rollladen', 'rolladen', 'markise', 'jalousie', 'raffstore', 'sonnenschutz', 'referenz']
    for s in top:
        if s in path:
            return 3
    for s in mid:
        if s in path:
            return 2
    for s in low:
        if s in path:
            return 1
    return 0

def is_screenshot_worthy(url):
    return screenshot_score(url) > 0

def fetch_apiflash_screenshot(target_url, apiflash_key):
    """Holt Screenshot via ApiFlash (echtes Chromium, rendert auch lazy Logos)."""
    if not apiflash_key:
        return None
    try:
        import base64
        params = urllib.parse.urlencode({
            'access_key': apiflash_key,
            'url': target_url,
            'format': 'png',
            'width': 1280,
            'full_page': 'true',
            'scroll_page': 'true',
            'full_page_max_height': 4000,
            'no_cookie_banners': 'true',
            'no_ads': 'true',
            'fresh': 'true',
            'wait_until': 'network_idle',
            'delay': 2,
            'response_type': 'image',
        })
        ss_url = "https://api.apiflash.com/v1/urltoimage?{}".format(params)
        req = urllib.request.Request(ss_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=40) as resp:
            img_data = resp.read()
            if len(img_data) < 1000:
                return None
            b64 = base64.b64encode(img_data).decode('utf-8')
            print("  ApiFlash Screenshot: {} bytes von {}".format(len(img_data), target_url))
            return b64
    except Exception as e:
        print("  ApiFlash Fehler: {}".format(e))
        return None

def fetch_website_deep(url, apiflash_key=None):
    if not url.startswith('http'):
        url = 'https://' + url
    results = {}

    # 1. Startseite
    print("  Startseite: {}".format(url))
    main_html = fetch_url(url)
    main_text = extract_text(main_html)
    results[url] = main_text

    # 2. Kandidaten
    candidates = find_relevant_links(main_html, url)
    print("  Kandidaten: {}".format(len(candidates)))

    # 3. Unterseiten parallel per urllib
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        futures = list(ex.map(fetch_single, [(u, 8) for u in candidates[:12]]))

    subpage_data = {}
    for sub_url, html, text in futures:
        if text and len(results) < 8:
            results[sub_url] = text
            if html:
                subpage_data[sub_url] = html

    # 4. Tiefe 2
    for sub_url, html in list(subpage_data.items()):
        if len(results) >= 10:
            break
        deep_candidates = find_relevant_links(html, sub_url)
        for deep_url in deep_candidates[:2]:
            if deep_url not in results and len(results) < 8:
                try:
                    deep_html = fetch_url(deep_url, timeout=6)
                    deep_text = extract_text(deep_html)
                    if deep_text and len(deep_text) > 100:
                        results[deep_url] = deep_text
                        print("  Tiefe 2: {}".format(deep_url))
                except Exception:
                    pass

    # 5. Screenshot via ApiFlash: STRENGE Auswahl
    #    Nur wenn (a) relevante Seite UND (b) Marken-Signale im Text
    screenshots = []
    if apiflash_key:
        # Bekannte Marken/Hersteller die auf Logos erscheinen
        BRAND_SIGNALS = [
            'somfy', 'becker', 'elero', 'warema', 'rademacher', 'selve', 'gira',
            'griesser', 'weinor', 'markilux', 'roma', 'schellenberg', 'lux-z',
            'coulisse', 'hunter douglas', 'verosol', 'hörmann', 'hoermann',
            'sommer', 'novoferm', 'marantec', 'velux', 'heroal', 'schüco', 'schueco',
            'kömmerling', 'koemmerling', 'rehau', 'internorm', 'aluprof',
            'partner', 'hersteller', 'markenpartner', 'premiumpartner',
            'fachpartner', 'vertragspartner', 'lieferant', 'marken',
            'io-homecontrol', 'io homecontrol', 'tahoma', 'connexoon',
        ]

        def brand_signal_count(text):
            t = text.lower()
            return sum(1 for b in BRAND_SIGNALS if b in t)

        # Kandidaten: nur Seiten mit screenshot_score > 0 (Partner/Hersteller/Antrieb/Smart-Home/Produkt)
        candidates_ss = []
        for page_url, text in results.items():
            sc = screenshot_score(page_url)
            if sc == 0:
                continue
            signals = brand_signal_count(text)
            # Strenge Regel: Score >= 2 (echte Partner/Hersteller/Antriebsseite)
            #   ODER mindestens 2 Markennamen im Text
            if sc >= 2 or signals >= 2:
                # Kombinierter Rang: Seiten-Score + Anzahl Marken-Signale
                rank = sc * 10 + signals
                candidates_ss.append((rank, signals, page_url))

        candidates_ss.sort(key=lambda x: -x[0])

        if candidates_ss:
            rank, signals, ss_target = candidates_ss[0]
            slug = urllib.parse.urlparse(ss_target).path.strip('/').split('/')[-1] or 'startseite'
            print("  Screenshot-Auswahl: {} (rank={}, {} Marken-Signale)".format(slug, rank, signals))
            img = fetch_apiflash_screenshot(ss_target, apiflash_key)
            if img:
                screenshots.append({'url': ss_target, 'image': img, 'slug': slug, 'kind': 'logo', 'signals': signals})
        else:
            print("  Kein Screenshot: keine Seite mit ausreichenden Marken-Signalen")

    # 6. Text zusammenfuehren - Team/Über-uns-Seiten bekommen mehr Platz
    team_slugs = ['team', 'ueber', 'uber-uns', 'uber', 'about', 'ansprechpartner',
                  'mitarbeiter', 'unternehmen', 'wir', 'firma', 'karriere', 'jobs', 'impressum']
    def is_team_page(page_url):
        path = urllib.parse.urlparse(page_url).path.lower()
        return any(t in path for t in team_slugs)

    base_limit = max(800, 7000 // len(results))
    combined = []
    for page_url, text in results.items():
        slug = urllib.parse.urlparse(page_url).path.strip('/') or 'startseite'
        # Team-Seiten: doppeltes Limit, damit Mitarbeiterinfos nicht abgeschnitten werden
        limit = base_limit * 2 if is_team_page(page_url) else base_limit
        marker = " [TEAM/MITARBEITER-SEITE]" if is_team_page(page_url) else ""
        combined.append("=== {}{} ===\n{}".format(slug, marker, text[:limit]))
    full_text = '\n\n'.join(combined)
    print("  Gesamt: {} Zeichen aus {} Seiten, {} Screenshots".format(
        len(full_text), len(results), len(screenshots)))
    return full_text, list(results.keys()), screenshots

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print("HTTP {} {}".format(args[0], args[1]))

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        path = parsed.path

        if path == '/health':
            self._json({'status': 'ok', 'playwright': False, 'cache': cache_stats()})
            return

        if path == '/cache/stats':
            entries = []
            for e in sorted(cache.values(), key=lambda x: x['ts'], reverse=True):
                age_h = round((time.time() - e['ts']) / 3600, 1)
                entries.append({'url': e.get('url', '?'), 'age_h': age_h,
                                 'valid': (age_h * 3600) < CACHE_TTL})
            self._json({'stats': cache_stats(), 'entries': entries})
            return

        if path == '/cache/clear':
            url_param = params.get('url', [''])[0]
            if url_param:
                key = url_key(url_param)
                removed = 1 if cache.pop(key, None) else 0
                self._json({'ok': True, 'cleared': removed})
            else:
                count = len(cache)
                cache.clear()
                print("  Cache geleert ({})".format(count))
                self._json({'ok': True, 'cleared': count})
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

        name_param      = params.get('name', [''])[0]
        address_param   = params.get('address', [''])[0]
        gkey_param      = params.get('gkey', [''])[0]
        afkey_param     = params.get('afkey', [''])[0]

        cached = cache_get(url)
        if cached:
            self._json({'text': cached['text'], 'pages': cached['pages'],
                        'screenshots': cached.get('screenshots', []), 'reviews': cached.get('reviews'),
                        'ok': True, 'from_cache': True})
            return

        print("\n  Fetche: {}".format(url))
        try:
            text, pages, screenshots = fetch_website_deep(url, apiflash_key=afkey_param)
            reviews = None
            if gkey_param and name_param:
                reviews = fetch_google_reviews(name_param, address_param, gkey_param)
                if reviews:
                    print("  Google: {} Sterne ({} Bewertungen)".format(
                        reviews.get('rating'), reviews.get('review_count')))
            cache_set(url, {'text': text, 'pages': pages, 'reviews': reviews, 'screenshots': screenshots})
            self._json({'text': text, 'pages': pages, 'screenshots': screenshots,
                        'reviews': reviews, 'ok': True, 'from_cache': False})
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
    print("Somfy Proxy auf Port {}".format(PORT))
    server = http.server.HTTPServer(('0.0.0.0', PORT), Handler)
    server.serve_forever()
