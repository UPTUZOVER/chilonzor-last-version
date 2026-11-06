"""ASGI config for Raqamli Qalqon."""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'chilonzor.settings')

application = get_asgi_application()
