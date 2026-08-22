from ordering_platform.database import build_database_config


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
    assert config["HOST"] == "10.0.0.105"
    assert config["PORT"] == "5432"
    assert config["CONN_MAX_AGE"] == 600
