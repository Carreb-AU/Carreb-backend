from .base import *
import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration


DEBUG = env.bool('DEBUG', default=False)
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS')

# Shared cache across gunicorn/celery/celery-beat processes: the estimate
# warmers (spec sheet / ANCAP / engine) write from celery workers and the
# web workers must see those values. LocMemCache is per-process and would
# silently break that pipeline.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env('REDIS_CACHE_URL', default='redis://redis:6379/1'),
        "TIMEOUT": 300,
    }
}
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True
USE_X_FORWARDED_PROTO = True
CSRF_TRUSTED_ORIGINS = [
    "https://api.carreb.com.au",
    "http://api.carreb.com.au",
    "https://carreb.com",
    "https://www.carreb.com",
    "https://carreb-web.netlify.app",
    "http://carreb-web.netlify.app",
    "https://www.carreb.com.au",
    "https://carreb.com.au",
    "https://carreb-developement.vercel.app",
    "https://www.carreb-developement.vercel.app",
    "https://carreb-developement-lovat.vercel.app",
]

# CORS settings
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://carreb.com",
    "https://www.carreb.com",
    "https://app.carreb.com.au",
    "https://carreb-web.netlify.app",
    "https://www.carreb.com.au",
    "https://carreb.com.au",
    "https://carreb-developement.vercel.app",
    "https://www.carreb-developement.vercel.app",
    "https://carreb-developement-lovat.vercel.app",
]
CORS_ALLOW_CREDENTIALS = True


# Security settings
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False

# Email settings
EMAIL_BACKEND = env('EMAIL_BACKEND')
EMAIL_HOST = env('EMAIL_HOST')
EMAIL_PORT = env.int('EMAIL_PORT')
EMAIL_USE_TLS = env.bool('EMAIL_USE_TLS', default=False)
EMAIL_USE_SSL = env.bool('EMAIL_USE_SSL', default=True)
EMAIL_HOST_USER = env('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD')
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default=EMAIL_HOST_USER)

SENTRY_DSN = env('SENTRY_DSN', default=None)
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration()],
        traces_sample_rate=1.0,
        send_default_pii=True
    )


LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'WARNING',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': True,
        },
    },
}
