import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.mail import EmailMessage
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from common.backup_constants import MAX_ATTACHMENT_BYTES, attachment_exceeds_email_limit

_PG_DUMP_ERROR_DETAIL_LIMIT = 200


class Command(BaseCommand):
    help = "Dump the PostgreSQL database and email the compressed custom-format file."

    def add_arguments(self, parser):
        parser.add_argument(
            "--to",
            dest="to",
            default=None,
            help="Recipient email address (default: BACKUP_EMAIL_TO).",
        )
        parser.add_argument(
            "--output",
            dest="output",
            default=None,
            help="Write the dump to this path instead of emailing it.",
        )

    def handle(self, *args, **options):
        db = settings.DATABASES["default"]
        engine = db.get("ENGINE", "")
        if "postgresql" not in engine:
            raise CommandError(
                "backup_database requires a PostgreSQL database; "
                f"got {engine or 'an empty ENGINE'}."
            )

        stamp = timezone.now()
        filename = f"ordereasy-db-{stamp.strftime('%Y%m%d-%H%M%S')}.dump"
        output_path = options.get("output")
        tmp_path = None
        try:
            tmp_path = self._dump_to_tempfile(db)
            if output_path:
                self._write_output(tmp_path, output_path)
                self.stdout.write(self.style.SUCCESS(f"Wrote dump to {output_path}"))
                return

            content = Path(tmp_path).read_bytes()
            if not content:
                raise CommandError("pg_dump produced an empty file; refusing to send.")

            if attachment_exceeds_email_limit(content):
                encoded_mb = len(content) / (1024 * 1024)
                raise CommandError(
                    f"Dump encodes to more than {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB "
                    f"as an email attachment (~{encoded_mb:.1f} MB raw). "
                    "Use --output PATH to inspect size."
                )

            recipient = options.get("to") or settings.BACKUP_EMAIL_TO
            self._email_dump(content, filename, recipient, stamp)
            self.stdout.write(self.style.SUCCESS(f"Sent {filename} to {recipient}"))
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def _write_output(self, tmp_path, output_path):
        dest = Path(output_path)
        parent = dest.parent
        if str(parent) not in ("", ".") and not parent.exists():
            raise CommandError(f"Output directory does not exist: {parent}")
        try:
            shutil.copyfile(tmp_path, dest)
        except OSError as exc:
            raise CommandError(f"Could not write dump to {output_path}: {exc}") from exc

    def _dump_to_tempfile(self, db):
        fd, tmp_path = tempfile.mkstemp(suffix=".dump")
        os.close(fd)
        cmd = [
            "pg_dump",
            "--format=custom",
            "--no-password",
            "--compress=9",
            "-h",
            str(db.get("HOST") or "localhost"),
            "-p",
            str(db.get("PORT") or "5432"),
            "-U",
            str(db.get("USER") or ""),
            "-d",
            str(db.get("NAME") or ""),
            "-f",
            tmp_path,
        ]
        env = os.environ.copy()
        env["PGPASSWORD"] = db.get("PASSWORD") or ""
        sslmode = (db.get("OPTIONS") or {}).get("sslmode")
        if sslmode:
            env["PGSSLMODE"] = sslmode

        try:
            subprocess.run(
                cmd,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            os.unlink(tmp_path)
            raise CommandError("pg_dump was not found on PATH") from exc
        except subprocess.CalledProcessError as exc:
            os.unlink(tmp_path)
            detail = (exc.stderr or exc.stdout or "").strip()
            if len(detail) > _PG_DUMP_ERROR_DETAIL_LIMIT:
                detail = detail[:_PG_DUMP_ERROR_DETAIL_LIMIT] + "…"
            raise CommandError(
                f"pg_dump failed with exit code {exc.returncode}"
                + (f": {detail}" if detail else "")
            ) from exc
        return tmp_path

    def _email_dump(self, content, filename, recipient, stamp):
        if not settings.EMAIL_HOST_USER or not settings.EMAIL_HOST_PASSWORD:
            raise CommandError(
                "EMAIL_HOST_USER and EMAIL_HOST_PASSWORD must be set to send backup email."
            )

        subject = f"OrderEasy DB backup {stamp.strftime('%Y-%m-%d')}"
        body = (
            f"Attached is the OrderEasy PostgreSQL dump ({filename}).\n"
            "Restore with pg_restore."
        )
        message = EmailMessage(
            subject=subject,
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL or settings.EMAIL_HOST_USER,
            to=[recipient],
        )
        message.attach(filename, content, "application/octet-stream")
        try:
            message.send()
        except Exception as exc:
            raise CommandError(f"Failed to send backup email: {exc}") from exc
