import http.server
import urllib.request
import urllib.error
import urllib.parse
import json
import re
import os
import sys

try:
    from bs4 import BeautifulSoup
    USE_BS4 = True
except ImportError:
    USE_BS4 = False

PORT = int(os.environ.get('PORT', 7723))

def fetch_website(url):
    if not url.startswith('http'):
        url = 'https://' + url
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'de-DE,de;q=0.9,en;q=0.8',
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()
            encoding = resp.headers.get_content_charset() or 'utf-8'
            html = raw.decode(encoding, errors='replace')
            return extract_text(html)
    except Exception:
        url_http = url.replace('https://', 'http://', 1)
        req2 = urllib.request.Request(url_http, headers=headers)
        with urllib.request.urlopen(req2, timeout=10) as resp:
            raw = resp.read()
            encoding = resp.headers.get_content_charset() or 'utf-8'
            html = raw.decode(encoding, errors='replace')
            return extract_text(html)

def extract_text(html):
    if USE_BS4:
        soup = BeautifulSoup(html, 'html.parser')
        for tag in soup(['script','style','nav','footer','header','noscript','meta','link']):
            tag.decompose()
        text = soup.get_text(separator='\n')
    else:
        text = re.sub(r'<script[\s\S]*?</script>', '', html, flags=re.IGNORECASE)
        text = re.sub(r'<style[\s\S]*?</style>', '', text, flags=re.IGNORECASE)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'&[a-zA-Z]+;', ' ', text)
    text = re.sub(r'[ \t]{3,}', ' ', text)
    text = re.sub(r'\n{4,}', '\n\n', text)
    return text.strip()[:4000]

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"  → {args[0]} {args[1]}")

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

        print(f"\n  Fetche: {url}")
        try:
            text = fetch_website(url)
            print(f"  ✓ {len(text)} Zeichen extrahiert")
            self._json({'text': text, 'ok': True})
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
