import pytest

from ordering_platform.database import build_database_config


def _getenv(env):
    return lambda key, default=None: env[key] if key in env else default


def test_build_database_config_reads_from_env():
    env = {
        "DB_ENGINE": "django.db.backends.postgresql",
        "DB_NAME": "env_db",
        "DB_USER": "env_user",
        "DB_PASSWORD": "env_pass",
        "DB_HOST": "db.example",
        "DB_PORT": "6543",
        "DB_CONN_MAX_AGE": "120",
    }

    config = build_database_config(env.get)

    assert config["ENGINE"] == "django.db.backends.postgresql"
    assert config["NAME"] == "env_db"
    assert config["USER"] == "env_user"
    assert config["PASSWORD"] == "env_pass"
    assert config["HOST"] == "db.example"
    assert config["PORT"] == "6543"
    assert config["CONN_MAX_AGE"] == 120


def test_build_database_config_uses_current_defaults_when_env_missing():
    config = build_database_config(lambda key, default=None: default)

    assert config["ENGINE"] == "django.db.backends.postgresql"
    assert config["NAME"] == "buyez_db"
    assert config["USER"] == "buyez_user"
    assert config["PASSWORD"] == "strongpassword"
    assert config["HOST"] == "localhost"
    assert config["PORT"] == "5432"
    assert config["CONN_MAX_AGE"] == 600


def test_blank_password_is_used_instead_of_fallback():
    config = build_database_config(_getenv({"DB_PASSWORD": ""}))

    assert config["PASSWORD"] == ""


def test_reads_from_os_environ(monkeypatch):
    monkeypatch.setenv("DB_ENGINE", "django.db.backends.postgresql")
    monkeypatch.setenv("DB_NAME", "from_os")
    monkeypatch.setenv("DB_USER", "from_os_user")
    monkeypatch.setenv("DB_PASSWORD", "from_os_pass")
    monkeypatch.setenv("DB_HOST", "from.os.host")
    monkeypatch.setenv("DB_PORT", "5555")
    monkeypatch.setenv("DB_CONN_MAX_AGE", "90")

    config = build_database_config()

    assert config["NAME"] == "from_os"
    assert config["USER"] == "from_os_user"
    assert config["PASSWORD"] == "from_os_pass"
    assert config["HOST"] == "from.os.host"
    assert config["PORT"] == "5555"
    assert config["CONN_MAX_AGE"] == 90


@pytest.mark.parametrize("raw", ["", "nope", None])
def test_invalid_conn_max_age_names_the_variable(raw):
    with pytest.raises(ValueError, match="DB_CONN_MAX_AGE"):
        build_database_config(_getenv({"DB_CONN_MAX_AGE": raw}))
