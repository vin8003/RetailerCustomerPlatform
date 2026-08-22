---
id: KAN-18
title: Scanner app crash review and logging
knowledge_class: temporary
owning_repo: buyeasy_retailer_scanner
durable_docs: []
jira: https://vin8003.atlassian.net/browse/KAN-18
confluence: https://vin8003.atlassian.net/wiki/spaces/KAN/pages/491586/KAN-18+Scanner+App+Crash+Review+Logging
gitbook: https://app.gitbook.com/s/iu06pIi3CiBqpw30jhyU/kan-18-scanner-app-crash-review
---

# KAN-18 Scanner app crash review and logging

**Temporary work.** Do not promote this page into architecture. Scanner catalog flow (durable): [03-USER-JOURNEYS.md](../03-USER-JOURNEYS.md).

Cashiers report random crashes during continuous scanning. Suspected: camera stream leak, scan/API race, malformed barcode NPE.

Diagnostic plan from Confluence: Sentry or Crashlytics; try/catch on frame handler; RAM/CPU while scanning 100+ items.
