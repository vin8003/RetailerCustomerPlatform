# OrderEasy / BuyEasy Platform – Knowledge Base Index

This is the central knowledge base for the entire multi-repository project.

It is designed for both humans and AI agents. **Canonical copy is this Git tree** — see [DOCUMENTATION.md](DOCUMENTATION.md). GitBook is optional presentation.

## User wiki (start here for retailers & customers)

The **[`wiki/`](../wiki/README.md)** folder is the plain-language help centre — getting started, customer guide, retailer guide, scanner, FAQ, and end-to-end project map. Use [`wiki/SUMMARY.md`](../wiki/SUMMARY.md) as the table of contents.

| Wiki section | Audience |
|--------------|----------|
| [Welcome](../wiki/welcome/what-is-ordereasy.md) | Everyone |
| [Getting started](../wiki/getting-started/for-customers.md) | New users |
| [Customer guide](../wiki/customer-guide/README.md) | Shoppers |
| [Retailer guide](../wiki/retailer-guide/README.md) | Shop owners & staff |
| [Scanner guide](../wiki/scanner-guide/README.md) | Bulk catalog capture |
| [FAQ](../wiki/faq/common-questions.md) | Quick answers |
| [Full project](../wiki/project/all-apps.md) | All apps end to end |

## Technical docs (`docs/`)

| File / Folder | Description |
|---------------|-------------|
| [DOCUMENTATION.md](DOCUMENTATION.md) | Source-of-truth model: Jira, Git, GitBook, Confluence, agents |
| [01-OVERVIEW.md](01-OVERVIEW.md) | Project identity, purpose, value proposition, component map |
| [02-ARCHITECTURE.md](02-ARCHITECTURE.md) | High-level system architecture (Mermaid + illustration) |
| [03-USER-JOURNEYS.md](03-USER-JOURNEYS.md) | Customer, retailer POS, and scanner journeys |
| [07-KEY-FLOWS/](07-KEY-FLOWS/) | Detailed key business flows |
| [requirements/](requirements/) | Durable product/engineering requirements extracted from tickets |
| [decisions/](decisions/) | Architecture Decision Records (ADRs) |
| [tickets/](tickets/) | Jira work snapshots (not a substitute for Jira status) |
| [visuals/](visuals/) | Illustrative diagrams and screenshot rules |
| [gitbook-migration/](gitbook-migration/) | Migration history (preserve) |

### Covered in wiki (user-facing)

- Frontend apps and full project map — [wiki/project/all-apps.md](../wiki/project/all-apps.md), [how-it-works-together.md](../wiki/project/how-it-works-together.md)
- Setup / onboarding — [wiki/getting-started/](../wiki/getting-started/for-customers.md)

### Not written yet in `docs/` (do not invent technical content)

- Domain models (`04-DOMAIN-MODELS/`)
- API surface (`05-API-SURFACE.md`)
- Developer setup (`08-SETUP.md`)

## Canonical Diagrams

All image files live in [`visuals/`](visuals/) and are referenced with **repository-relative** paths.

- System Architecture — [02-ARCHITECTURE.md](02-ARCHITECTURE.md)
- Order Status Lifecycle — [07-KEY-FLOWS/order-lifecycle.md](07-KEY-FLOWS/order-lifecycle.md)
- Inventory & Batch Logic — [07-KEY-FLOWS/inventory-and-batches.md](07-KEY-FLOWS/inventory-and-batches.md)
- Offer Calculation Engine — [07-KEY-FLOWS/offer-calculation.md](07-KEY-FLOWS/offer-calculation.md)
- Credit / Khata System — [07-KEY-FLOWS/credit-khata.md](07-KEY-FLOWS/credit-khata.md)
- Customer / retailer / scanner journeys — [03-USER-JOURNEYS.md](03-USER-JOURNEYS.md)

## Design Principles

- Text is primary. Diagrams support the text.
- Prefer Mermaid for machine-readable diagrams.
- Small, focused documents.
- Three layers: Human-readable explanation → Mermaid → Visuals.
- Every important visual has a textual explanation.
- Durable knowledge does not live only inside a Jira ticket or a GitBook page.

---

**Repositories**

- Backend (this repo, docs SOT): `RetailerCustomerPlatform`
- Customer App: `customer_ordereasy_njs`
- Retailer App: `retailer_ordereasy_njs`
- Scanner: `buyeasy_retailer_scanner`
