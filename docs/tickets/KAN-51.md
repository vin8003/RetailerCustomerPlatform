---
id: KAN-51
title: Product-group search on add/update
knowledge_class: temporary
owning_repo: retailer_ordereasy_njs
durable_docs: []
jira: https://vin8003.atlassian.net/browse/KAN-51
confluence: https://vin8003.atlassian.net/wiki/spaces/OrderEasy/pages/29949953/KAN-51+Product-group+search+on+add+update
gitbook: https://app.gitbook.com/s/iu06pIi3CiBqpw30jhyU/open-jira-ticket-docs/kan-51-product-group-search
---

# KAN-51 Product-group search on add/update

**Temporary bugfix.** Search inside a product group when adding/updating a product does not work.

Verify whether the failure is API (`RetailerCustomerPlatform`, pagination / `no_page`) or UI filter — do not guess. Done when add and update search returns matches. QA on retailer.ordereasy.win after deploy. No extra scope.
