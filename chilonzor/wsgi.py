"""WSGI config for Raqamli Qalqon."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'chilonzor.settings')

application = get_wsgi_application()
