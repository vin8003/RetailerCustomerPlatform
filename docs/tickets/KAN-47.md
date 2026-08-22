---
id: KAN-47
title: Google social login
knowledge_class: durable
owning_repo: customer_ordereasy_njs
durable_docs:
  - docs/07-KEY-FLOWS/google-social-login.md
jira: https://vin8003.atlassian.net/browse/KAN-47
confluence: https://vin8003.atlassian.net/wiki/spaces/KAN/pages/17432578/Release+Log+KAN-47+Google+Social+Login
gitbook: https://app.gitbook.com/s/iu06pIi3CiBqpw30jhyU/open-jira-ticket-docs/kan-47-google-social-login
---

# KAN-47 Google social login

Work snapshot (release log). Durable: [google-social-login.md](../07-KEY-FLOWS/google-social-login.md).

Hybrid OTP: Google first; phone verified at checkout for new users; collision on existing mobile requires SMS OTP before link. Capacitor Google Auth + GIS web. `postinstall` patches plugin Gradle (`jcenter` → `mavenCentral`, ProGuard filename). Backend tests in auth; `cap sync android`.
