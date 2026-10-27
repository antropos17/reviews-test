"""WSGI entry point for a stateless Python hosting platform."""
from app import create_app

app = create_app()
