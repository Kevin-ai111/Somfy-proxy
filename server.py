import http.server
import urllib.request
import urllib.error
import urllib.parse
import json
import re
import os

try:
    from bs4 import BeautifulSoup
    USE_BS4 = True
except ImportError:
    USE_BS4 = False

PORT = int(os.environ.get('PORT', 7723))

# Unterseiten die besonders relevant für Lieferanten/Partner-Erkennung sind
RELEVANT_SLUGS = [
    'referenz', 'referenzen', 'partner', 'partners', 'hersteller',
    'produkt', 'produkte', 'produktwelt', 'sortiment', 'marken',
    'leistung', 'leistungen', 'service', 'services',
    'lieferant', 'lieferanten', 'kooperationen', 'kooperation',
    'ueber-uns', 'ueber', 'uber-uns', 'about', 'unternehmen',
    'team', 'galerie', 'gallery', 'projekte', 'projekt',
    'shop', 'onlineshop', 'katalog',
]

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
    """Findet relevante Unterseiten-URLs aus dem HTML."""
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
        # Absolute URL bauen
        if href.startswith('http'):
            full = href
        elif href.startswith('/'):
            full = base_origin + href
        else:
            full = base_origin + '/' + href

        # Nur gleiche Domain
        parsed = urllib.parse.urlparse(full)
        if parsed.netloc != base.netloc:
            continue

        # Prüfen ob Slug relevant ist
        path_lower = parsed.path.lower().rstrip('/')
        slug = path_lower.split('/')[-1] if '/' in path_lower else path_lower
        # Auch Teilstrings prüfen
        is_relevant = any(s in path_lower for s in RELEVANT_SLUGS)

        if is_relevant and full not in seen:
            seen.add(full)
            found.append(full)

    return found[:8]  # Max 8 Unterseiten

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
    """Startseite + relevante Unterseiten abrufen, Text zusammenführen."""
    if not url.startswith('http'):
        url = 'https://' + url

    results = {}  # url -> text

    # 1. Startseite
    print(f"    Startseite: {url}")
    main_html = fetch_url(url)
    main_text = extract_text(main_html)
    results[url] = main_text

    # 2. Relevante Unterseiten finden
    subpages = find_relevant_links(main_html, url)
    print(f"    Gefundene Unterseiten: {len(subpages)}")

    for sub_url in subpages:
        if len(results) >= 6:  # Max 6 Seiten gesamt (1 Start + 5 Unter)
            break
        try:
            print(f"    Unterseite: {sub_url}")
            html = fetch_url(sub_url, timeout=8)
            text = extract_text(html)
            if text and len(text) > 100:
                results[sub_url] = text
        except Exception as e:
            print(f"    ✗ {sub_url}: {e}")
            continue

    # 3. Alles zusammenführen, pro Seite gekürzt
    combined = []
    per_page_limit = max(1500, 6000 // len(results))
    for page_url, text in results.items():
        slug = urllib.parse.urlparse(page_url).path.strip('/') or 'startseite'
        combined.append(f"=== {slug} ===\n{text[:per_page_limit]}")

    full_text = '\n\n'.join(combined)
    print(f"    ✓ Gesamt: {len(full_text)} Zeichen aus {len(results)} Seiten")
    return full_text, list(results.keys())

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Eigenes Logging

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if parsed.path == '/health':
            self._json({'status': 'ok'})
            return

        if parsed.path != '/fetch':
            self.send_response(404)
            self._cors()
            self.end_headers()
            return

        url = params.get('url', [''])[0]
        if not url:
            self._json({'error': 'Kein URL angegeben'}, 400)
            return

        print(f"\n  Analysiere: {url}")
        try:
            text, pages = fetch_website_deep(url)
            self._json({'text': text, 'pages': pages, 'ok': True})
        except Exception as e:
            print(f"  ✗ Fehler: {e}")
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
    print(f"Server läuft auf Port {PORT}")
    server = http.server.HTTPServer(('0.0.0.0', PORT), Handler)
    server.serve_forever()
