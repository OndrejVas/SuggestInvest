import os
import sys
import json
import webbrowser
import threading
import logging
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from main import run_scanner

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("LocalServer")

PORT = 8000
DIRECTORY = os.path.dirname(os.path.abspath(__file__))


class MarketScannerRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def do_POST(self):
        """Obslouží požadavek na manuální spuštění nového skenu."""
        if self.path == "/api/scan":
            logger.info("Přijat požadavek na aktualizaci tržních dat (/api/scan)...")
            try:
                # Spuštění skeneru a generování nového index.html
                run_scanner(allow_mock_fallback=True)
                
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                response = {"status": "success", "message": "Tržní report byl úspěšně aktualizován."}
                self.wfile.write(json.dumps(response, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                logger.error(f"Chyba při aktualizaci: {e}", exc_info=True)
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                response = {"status": "error", "message": str(e)}
                self.wfile.write(json.dumps(response, ensure_ascii=False).encode("utf-8"))
        else:
            self.send_error(404, "Endpoint nenalezen")

    def do_GET(self):
        """Obslouží GET requesty včetně možnosti spustit sken přes GET /api/scan."""
        if self.path == "/api/scan":
            self.do_POST()
        elif self.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
        else:
            super().do_GET()

    def log_message(self, format, *args):
        # Potlačení běžných přístupových logů pro přehlednější konzoli
        try:
            msg = format % args
            if " 200 " in msg and (".ico" in msg or ".css" in msg):
                return
            logger.info("%s - %s", self.address_string(), msg)
        except Exception:
            pass


def open_browser():
    url = f"http://localhost:{PORT}"
    logger.info(f"Otevírám webový prohlížeč na: {url}")
    webbrowser.open(url)


def start_server():
    # 1. Zkontrolujeme, zda existuje index.html. Pokud ne, vygenerujeme úvodní.
    index_path = os.path.join(DIRECTORY, "index.html")
    if not os.path.exists(index_path):
        logger.info("Soubor index.html zatím neexistuje. Provádím první sken...")
        try:
            run_scanner(allow_mock_fallback=True)
        except Exception as e:
            logger.error(f"Chyba při úvodním skenu: {e}")

    server_address = ("127.0.0.1", PORT)
    httpd = ThreadingHTTPServer(server_address, MarketScannerRequestHandler)
    
    local_url = f"http://localhost:{PORT}"
    print("\n" + "=" * 65)
    print(f"🚀 Lokální server běží!")
    print(f"👉 Otevřete v prohlížeči: {local_url}")
    print(f"💡 Na stránce můžete kliknout na tlačítko 'Aktualizovat data'")
    print(f"🛑 Pro ukončení stiskněte: Ctrl + C")
    print("=" * 65 + "\n")

    # Automatické otevření prohlížeče za 1 sekundu
    threading.Timer(1.0, open_browser).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nZastavuji server...")
        httpd.server_close()
        logger.info("Server byl v pořádku zastaven.")


if __name__ == "__main__":
    start_server()
