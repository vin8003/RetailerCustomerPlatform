---
id: KAN-74
title: Dashboard Total Customers uses API count
knowledge_class: temporary
owning_repo: retailer_ordereasy_njs
jira: https://vin8003.atlassian.net/browse/KAN-74
---

# KAN-74 Total Customers stat

Work snapshot (temporary — small FE fix).

**Total Customers** on the retailer dashboard must use the paginated `count` from `GET customer/retailer/list/`, not `customers.length` from the infinite-scroll page buffer.
