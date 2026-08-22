import os


def build_database_config(getenv=os.getenv):
    return {
        "ENGINE": getenv("DB_ENGINE", "django.db.backends.postgresql"),
        "NAME": getenv("DB_NAME", "buyez_db"),
        "USER": getenv("DB_USER", "buyez_user"),
        "PASSWORD": getenv("DB_PASSWORD", "strongpassword"),
        "HOST": getenv("DB_HOST", "10.0.0.105"),
        "PORT": getenv("DB_PORT", "5432"),
        "CONN_MAX_AGE": _int_env(getenv, "DB_CONN_MAX_AGE", "600"),
    }


def _int_env(getenv, name, default):
    raw = getenv(name, default)
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc
