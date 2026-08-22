# Visuals

This folder holds illustrative diagrams and screenshots for the knowledge base. **Files are in Git.** Markdown must use repository-relative paths (for example `visuals/architecture-overview.jpg` from `docs/02-ARCHITECTURE.md`, or `../visuals/…` from `docs/07-KEY-FLOWS/`).

Do not make important information exist only inside an image. Every important visual has a textual explanation (and Mermaid where it helps).

## Guidelines

- Prefer Mermaid when the diagram can live as code.
- Screenshots and wireframes must never contain secrets, real customer data, tokens, or private business information.
- GitBook must not be the only way to see these files.

## Phase 1 illustrative diagrams

Committed in `429dbfc`. No real data.

| Filename | Description | Related doc |
|----------|-------------|-------------|
| `architecture-overview.jpg` | Customer App, Retailer Dashboard+POS, Flutter Scanner → Django REST API | `02-ARCHITECTURE.md` |
| `order-status-lifecycle.jpg` | Order status progression + cancelled / waiting-for-approval | `07-KEY-FLOWS/order-lifecycle.md` |
| `inventory-and-batches.jpg` | Batches, FIFO, parent bulk + fractional child | `07-KEY-FLOWS/inventory-and-batches.md` |
| `offer-calculation-engine.jpg` | Offer engine inputs → discounts / points | `07-KEY-FLOWS/offer-calculation.md` |
| `credit-khata-system.jpg` | Customer credit + supplier khata | `07-KEY-FLOWS/credit-khata.md` |
| `customer-journey.jpg` | Discover → browse → cart → checkout → track → rewards | `03-USER-JOURNEYS.md` |
| `retailer-pos-order-handling.jpg` | POS + online order workflow | `03-USER-JOURNEYS.md` |
| `scanner-to-catalog-flow.jpg` | Scanner → session → OCR → review → catalog | `03-USER-JOURNEYS.md` |

## Naming for future screenshots

Use names such as `customer-home.png`, `retailer-pos.png`, `scanner-gateway.png`. Blur or remove sensitive data before committing.
