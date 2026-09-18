---
id: pos-nopage-size
title: F follow-on — optional size on POS no_page
knowledge_class: durable
owning_repo: RetailerCustomerPlatform
durable_docs:
  - docs/requirements/pos-nopage-size.md
jira: null
---

# Optional `size` on POS no_page

Work snapshot. Durable: [pos-nopage-size.md](../requirements/pos-nopage-size.md).

List/detail/search do not expose a top-level `size`. `Product` has no `size` column. CTO overnight lock is this EXTEND only: POS `GET /api/products/?no_page=true` may echo `size` **if that column already exists on Product**. Do not invent a field, default, or value.

Atlassian MCP was rate-limited when this slice was implemented; no Jira key was invented.

## Gap list (scout)

| AC | Before this slice | After |
|----|-------------------|--------|
| POS `no_page` row includes `size` when Product already has the column | Not attached | **EXTEND** — concrete-field echo only |
| No `Product.size` column | Missing | still missing — key omitted (do not invent) |
| POS `no_page` query flags | Existing filters | unchanged |
| Auth/tenancy / public catalog | Shop-scoped retailer GET | unchanged |
| Size/color matrix / write APIs | Missing | still out of scope |

## Done in this change (EXTEND, one slice)

- `attach_optional_product_size` on the POS `no_page` hand-built dict
- Copies `size` only when `_meta.concrete_fields` already includes `size`
- Tests: helper dummy-with-column (mutates input), omit when missing, POS calls helper once per row, specifications/master attributes not promoted, search unchanged, existing row keys, query-flag true/false non-regression, auth, tenancy, public unchanged

Out of scope: `Product.size` migration, specifications/master-attribute invent, search Meta, pack write, inventory.adjust, timeline/OFD/khata/UPI/slots, FE, merge, Jira Done, live `*.ordereasy.win`.
