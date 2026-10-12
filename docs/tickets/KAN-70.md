---
id: KAN-70
title: Show retailer-wise credit balance in customer profile
knowledge_class: durable
owning_repo: customer_ordereasy_njs
durable_docs:
  - docs/requirements/customer-profile-credit.md
  - docs/07-KEY-FLOWS/credit-khata.md
jira: https://vin8003.atlassian.net/browse/KAN-70
---

# KAN-70 Retailer-wise credit in customer profile

Work snapshot. Durable: [customer-profile-credit.md](../requirements/customer-profile-credit.md).

Show each retailer’s credit balance on the customer profile, including when the credit limit is 0. Remove the Credit / Khata block from customer order detail (KAN-61 only showed it when limit > 0).

Backend: `GET /api/customer/credit/all/`. Customer app: profile section + drop order-detail credit UI.
