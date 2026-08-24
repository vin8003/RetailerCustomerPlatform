---
id: KAN-79
title: Bug — Supplier Search Error in retailer app
knowledge_class: temporary
owning_repo: RetailerCustomerPlatform
durable_docs: []
jira: https://vin8003.atlassian.net/browse/KAN-79
confluence:
gitbook:
---

# KAN-79 Supplier search error

**Temporary bugfix.** Khata & Suppliers search (`GET /api/products/erp/suppliers/?search=`) 500'd because `SupplierViewSet.search_fields` included `email`, which is not a `Supplier` field.

Fix: search `company_name`, `contact_person`, `phone_number` only, and set `filter_backends = [SearchFilter]` so pytest actually exercises search (test settings omit global filter backends). Retailer empty-state copy distinguishes a search miss from an empty address book.

Done when Khata search by company or phone returns 200 (matches or empty), with no error toast. QA on retailer.ordereasy.win after deploy. No extra scope (no email column, no `+91` normalization).
