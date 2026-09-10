---
id: KAN-78
title: Supplier/Distributor Management: Edit & Safe Deactivation
knowledge_class: durable
owning_repo: retailer_ordereasy_njs
durable_docs:
  - docs/requirements/supplier-edit-and-deactivate.md
jira: https://vin8003.atlassian.net/browse/KAN-78
---

# KAN-78 Supplier edit and safe deactivation

Work snapshot. Durable: [supplier-edit-and-deactivate.md](../requirements/supplier-edit-and-deactivate.md).

Edit supplier details. Soft-deactivate with `is_active` even when history exists. Keep khata and old bills. Hide inactive from new-transaction pickers. Block hard delete when purchases, ledger, or returns exist.
