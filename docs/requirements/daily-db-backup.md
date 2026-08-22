# Daily database backup

- **Ticket:** [KAN-46](https://vin8003.atlassian.net/browse/KAN-46) · [snapshot](../tickets/KAN-46.md)

Production Postgres (`buyez_db` on the Oracle API VM) must be dumpable from the API process and delivered to operations email.

**Prerequisites (Oracle API VM)**

- `postgresql-client` installed so `pg_dump` is on `PATH` (`sudo apt install postgresql-client`).
- Gmail SMTP env vars set (`EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`).

**Rules**

1. Run `python manage.py backup_database` **on the API server** (the default DB host is a private IP; laptops cannot reach it).
2. Dump with `pg_dump --format=custom --compress=9`. Restore with `pg_restore`.
3. Email the dump to `BACKUP_EMAIL_TO` (default `shopeasy.bte@gmail.com`) using the existing Gmail SMTP settings. The command checks **base64-encoded** attachment size against **20 MB** (raw dumps near ~15 MB can exceed this after MIME encoding). Use `--output PATH` to inspect size first.
4. Daily cadence is a **crontab on the Oracle VM**, not GitHub Actions (Actions cannot see the private DB host).

Example cron (02:00 UTC unless the VM crontab is IST):

```cron
0 2 * * * cd /home/ubuntu/app && /home/ubuntu/app/.venv/bin/python manage.py backup_database >> /var/log/ordereasy-backup.log 2>&1
```

Manual size check, no email:

```bash
python manage.py backup_database --output /tmp/ordereasy.dump
```

Do not log the database password. Do not commit `.env`.
