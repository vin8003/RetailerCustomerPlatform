---
id: KAN-58
title: Delivery app — do not build yet
knowledge_class: durable
owning_repo: RetailerCustomerPlatform
durable_docs:
  - docs/decisions/ADR-001-no-delivery-app.md
jira: https://vin8003.atlassian.net/browse/KAN-58
confluence: https://vin8003.atlassian.net/wiki/spaces/OrderEasy/pages/29425665/KAN-58+Delivery+app+do+not+build+yet
gitbook: https://app.gitbook.com/s/iu06pIi3CiBqpw30jhyU/open-jira-ticket-docs/kan-58-delivery-app-do-not-build
---

# KAN-58 Delivery app — do not build yet

Work snapshot. **Durable decision:** [ADR-001](../decisions/ADR-001-no-delivery-app.md).

Do not start a delivery app or new repo. Backend already has `delivery_mode`, `out_for_delivery`, and `OrderDelivery` (name/phone strings, unused in views). No rider role. Next step if ever needed: fill `OrderDelivery` from retailer app and show on customer order — same API, no third client.
