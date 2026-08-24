---
id: KAN-73
title: Include online shoppers in POS customer typeahead
knowledge_class: durable
owning_repo: RetailerCustomerPlatform
durable_docs:
  - docs/requirements/pos-customer-typeahead.md
jira: https://vin8003.atlassian.net/browse/KAN-73
---

# KAN-73 Online shoppers in POS typeahead

Work snapshot. Durable: [pos-customer-typeahead.md](../requirements/pos-customer-typeahead.md).

POS typeahead stays scoped to **this retailer only** but now includes app shoppers who previously ordered here even when no `RetailerCustomerMapping` exists yet. `OrderCreateSerializer` creates an `online` mapping on first app order.
