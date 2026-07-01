from __future__ import annotations

import threading
import webbrowser

from app import app


def open_local_browser() -> None:
    webbrowser.open("http://127.0.0.1:5000")


def main() -> None:
    threading.Timer(1.2, open_local_browser).start()
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
