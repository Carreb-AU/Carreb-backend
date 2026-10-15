from django.apps import AppConfig
from django.db.backends.signals import connection_created


def _trigrams(value):
    value = '  ' + str(value).lower() + ' '
    return {value[i:i + 3] for i in range(len(value) - 2)}


def _sqlite_similarity(a, b):
    """Python equivalent of Postgres pg_trgm similarity() for SQLite.

    Only registered for SQLite connections (dev/test); production runs on
    Postgres, which provides the real function.
    """
    if not a or not b:
        return 0.0
    ta, tb = _trigrams(a), _trigrams(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def register_sqlite_functions(connection, **kwargs):
    if connection.vendor == 'sqlite':
        connection.connection.create_function('similarity', 2, _sqlite_similarity)


class VehiclesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.vehicles"

    def ready(self):
        connection_created.connect(register_sqlite_functions)
