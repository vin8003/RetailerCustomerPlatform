---
id: KAN-46
title: Daily database backup
knowledge_class: durable
owning_repo: RetailerCustomerPlatform
durable_docs:
  - docs/requirements/daily-db-backup.md
jira: https://vin8003.atlassian.net/browse/KAN-46
---

# KAN-46 Daily database backup

Work snapshot. Durable: [daily-db-backup.md](../requirements/daily-db-backup.md).

Jira title is *need data backup on daily basis*. The ticket body is a POS BXGY paste (same as KAN-48/KAN-49) and is **not** the requirement.

**Recut:** dump Postgres from the API server with `manage.py backup_database` and email the file to `shopeasy.bte@gmail.com`. Daily schedule is crontab on the Oracle VM after deploy, not part of this command itself.
