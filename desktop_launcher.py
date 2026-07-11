from __future__ import annotations

import socket
import threading
import webbrowser

from app import app


HOST = "127.0.0.1"
PORT = 5050


def _port_is_available() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        return connection.connect_ex((HOST, PORT)) != 0


def main() -> None:
    url = f"http://{HOST}:{PORT}"
    if not _port_is_available():
        webbrowser.open(url)
        return
    threading.Timer(1.1, lambda: webbrowser.open(url)).start()
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
