#!/usr/bin/env python3
"""FerreGest AR — punto de entrada del servidor de desarrollo/producción ligera."""
import os

from app import create_app
from app.config import bind_host

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    debug = os.environ.get("FERREGEST_DEBUG", "0") == "1"
    app.run(host=bind_host(), port=port, debug=debug)
