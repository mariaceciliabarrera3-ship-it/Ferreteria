"""WSGI para gunicorn (producción)."""
from app import create_app

app = create_app()
