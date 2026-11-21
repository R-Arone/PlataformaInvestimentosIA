"""Start the shared application in Android's private storage."""

from http.server import ThreadingHTTPServer
import os
from pathlib import Path
import threading


_server = None


def serve(files_dir):
    global _server
    if _server is not None:
        return _server.server_port

    # Retain the directory used by the APK distributed to prototype testers.
    data_dir = Path(files_dir).absolute() / 'spike-data'
    os.environ['APORTE_DATA_DIR'] = str(data_dir)
    import app

    if not (app.ROOT / 'static' / 'index.html').is_file():
        raise RuntimeError('Recursos da interface ausentes no APK.')

    vault = app.private_storage.Vault(data_dir)
    server = ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
    try:
        vault.acquire_instance()
    except Exception:
        server.server_close()
        vault.close()
        raise

    app.VAULT = vault
    app.DB_PATH = data_dir / 'carteira.sqlite3'
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _server = server
    return _server.server_port
