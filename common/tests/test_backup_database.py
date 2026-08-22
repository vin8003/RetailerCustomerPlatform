import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from common.backup_constants import MAX_ATTACHMENT_BYTES
from common.management.commands.backup_database import _PG_DUMP_ERROR_DETAIL_LIMIT

COMMAND_MODULE = "common.management.commands.backup_database"


@pytest.fixture
def postgres_settings(settings):
    db = settings.DATABASES["default"]
    db["ENGINE"] = "django.db.backends.postgresql"
    db["NAME"] = "buyez_db"
    db["USER"] = "buyez_user"
    db["PASSWORD"] = "secret-password"
    db["HOST"] = "10.0.0.105"
    db["PORT"] = "5432"
    db["OPTIONS"] = {"sslmode": "require"}
    settings.BACKUP_EMAIL_TO = "shopeasy.bte@gmail.com"
    settings.DEFAULT_FROM_EMAIL = "ordereasy.win@gmail.com"
    settings.EMAIL_HOST_USER = "ordereasy.win@gmail.com"
    settings.EMAIL_HOST_PASSWORD = "app-password"
    return settings


def _fake_pg_dump(dump_bytes=b"pg-dump-bytes"):
    def _run(cmd, **kwargs):
        assert cmd[0] == "pg_dump"
        assert "--format=custom" in cmd
        assert "--no-password" in cmd
        assert "--compress=9" in cmd
        assert "secret-password" not in cmd
        env = kwargs.get("env") or {}
        assert env.get("PGPASSWORD") == "secret-password"
        assert env.get("PGSSLMODE") == "require"
        out_path = cmd[cmd.index("-f") + 1]
        Path(out_path).write_bytes(dump_bytes)
        return MagicMock(returncode=0, stdout="", stderr="")

    return _run


class TestBackupDatabaseCommand:
    def test_refuses_non_postgres_engine(self):
        with pytest.raises(CommandError, match="PostgreSQL"):
            call_command("backup_database")

    def test_emails_dump_to_default_recipient(self, postgres_settings):
        with (
            patch(f"{COMMAND_MODULE}.subprocess.run", side_effect=_fake_pg_dump()) as mock_run,
            patch(f"{COMMAND_MODULE}.EmailMessage") as mock_email_cls,
        ):
            mock_message = MagicMock()
            mock_email_cls.return_value = mock_message
            call_command("backup_database")

        mock_run.assert_called_once()
        mock_email_cls.assert_called_once()
        _, kwargs = mock_email_cls.call_args
        to_list = kwargs.get("to") or mock_email_cls.call_args[0][3]
        assert "shopeasy.bte@gmail.com" in to_list
        subject = kwargs.get("subject") or mock_email_cls.call_args[0][0]
        assert subject.startswith("OrderEasy DB backup ")
        mock_message.attach.assert_called_once()
        filename = mock_message.attach.call_args[0][0]
        assert filename.startswith("ordereasy-db-")
        assert filename.endswith(".dump")
        mock_message.send.assert_called_once()

    def test_emails_dump_to_custom_recipient_with_to_flag(self, postgres_settings):
        with (
            patch(f"{COMMAND_MODULE}.subprocess.run", side_effect=_fake_pg_dump()),
            patch(f"{COMMAND_MODULE}.EmailMessage") as mock_email_cls,
        ):
            mock_message = MagicMock()
            mock_email_cls.return_value = mock_message
            call_command("backup_database", to="ops@example.com")

        _, kwargs = mock_email_cls.call_args
        to_list = kwargs.get("to") or mock_email_cls.call_args[0][3]
        assert to_list == ["ops@example.com"]

    def test_pg_dump_missing_does_not_email(self, postgres_settings):
        with (
            patch(
                f"{COMMAND_MODULE}.subprocess.run",
                side_effect=FileNotFoundError("pg_dump"),
            ),
            patch(f"{COMMAND_MODULE}.EmailMessage") as mock_email_cls,
            pytest.raises(CommandError, match="pg_dump"),
        ):
            call_command("backup_database")
        mock_email_cls.return_value.send.assert_not_called()

    def test_pg_dump_nonzero_does_not_email(self, postgres_settings):
        error = subprocess.CalledProcessError(
            1, ["pg_dump"], stderr="dump failed"
        )
        with (
            patch(f"{COMMAND_MODULE}.subprocess.run", side_effect=error),
            patch(f"{COMMAND_MODULE}.EmailMessage") as mock_email_cls,
            pytest.raises(CommandError),
        ):
            call_command("backup_database")
        mock_email_cls.return_value.send.assert_not_called()

    def test_pg_dump_error_detail_is_truncated(self, postgres_settings):
        long_stderr = "x" * (_PG_DUMP_ERROR_DETAIL_LIMIT + 50)
        error = subprocess.CalledProcessError(1, ["pg_dump"], stderr=long_stderr)
        with (
            patch(f"{COMMAND_MODULE}.subprocess.run", side_effect=error),
            pytest.raises(CommandError, match="…"),
        ):
            call_command("backup_database")

    def test_rejects_attachment_over_20mb_encoded(self, postgres_settings):
        too_big = b"x" * (MAX_ATTACHMENT_BYTES + 1)
        with (
            patch(
                f"{COMMAND_MODULE}.subprocess.run",
                side_effect=_fake_pg_dump(too_big),
            ),
            patch(f"{COMMAND_MODULE}.EmailMessage") as mock_email_cls,
            pytest.raises(CommandError, match="20 MB"),
        ):
            call_command("backup_database")
        mock_email_cls.return_value.send.assert_not_called()

    def test_rejects_empty_dump(self, postgres_settings):
        with (
            patch(
                f"{COMMAND_MODULE}.subprocess.run",
                side_effect=_fake_pg_dump(b""),
            ),
            patch(f"{COMMAND_MODULE}.EmailMessage") as mock_email_cls,
            pytest.raises(CommandError, match="empty"),
        ):
            call_command("backup_database")
        mock_email_cls.return_value.send.assert_not_called()

    def test_smtp_not_configured(self, postgres_settings):
        postgres_settings.EMAIL_HOST_PASSWORD = ""
        with (
            patch(f"{COMMAND_MODULE}.subprocess.run", side_effect=_fake_pg_dump()),
            patch(f"{COMMAND_MODULE}.EmailMessage") as mock_email_cls,
            pytest.raises(CommandError, match="EMAIL_HOST"),
        ):
            call_command("backup_database")
        mock_email_cls.return_value.send.assert_not_called()

    def test_send_failure_raises_command_error(self, postgres_settings):
        with (
            patch(f"{COMMAND_MODULE}.subprocess.run", side_effect=_fake_pg_dump()),
            patch(f"{COMMAND_MODULE}.EmailMessage") as mock_email_cls,
            pytest.raises(CommandError, match="Failed to send"),
        ):
            mock_message = MagicMock()
            mock_message.send.side_effect = OSError("smtp down")
            mock_email_cls.return_value = mock_message
            call_command("backup_database")

    def test_output_writes_file_and_skips_email(self, postgres_settings, tmp_path):
        dest = tmp_path / "backup.dump"
        with (
            patch(f"{COMMAND_MODULE}.subprocess.run", side_effect=_fake_pg_dump()),
            patch(f"{COMMAND_MODULE}.EmailMessage") as mock_email_cls,
        ):
            call_command("backup_database", output=str(dest))

        assert dest.read_bytes() == b"pg-dump-bytes"
        mock_email_cls.return_value.send.assert_not_called()
        mock_email_cls.return_value.attach.assert_not_called()

    def test_output_missing_parent_dir(self, postgres_settings):
        with (
            patch(f"{COMMAND_MODULE}.subprocess.run", side_effect=_fake_pg_dump()),
            pytest.raises(CommandError, match="Output directory does not exist"),
        ):
            call_command("backup_database", output="/no/such/dir/backup.dump")
