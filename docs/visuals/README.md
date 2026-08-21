# Visuals

This folder holds illustrative diagrams and future screenshots for the knowledge base.

## Guidelines (from Documentation Visuals Guidelines)

- Prefer Mermaid diagrams (they are machine-readable).
- Real screenshots and wireframes are welcome but must never contain secrets, real customer data, tokens, or private business information.
- Every important visual must be accompanied by textual explanation in the corresponding Markdown file.

## Generated Illustrative Diagrams (Phase 1)

The following clean, illustrative diagrams were generated for the knowledge base. They contain **no real data, secrets, or private information**.

| Filename (recommended) | Description | Related Doc |
|------------------------|-------------|-------------|
| `architecture-overview.jpg` | High-level system architecture: Customer App, Retailer Dashboard+POS, Flutter Scanner → Central Django REST API | `02-ARCHITECTURE.md` |
| `order-status-lifecycle.jpg` | Order status progression (Pending → Confirmed → Processing → Packed → Out for Delivery / Ready for Pickup → Delivered) + Cancelled & Waiting for Customer Approval | `07-KEY-FLOWS/order-lifecycle.md` |
| `inventory-and-batches.jpg` | Product batches, FIFO stock deduction, Parent Bulk + Fractional Child products with conversion factor | `07-KEY-FLOWS/inventory-and-batches.md` |
| `offer-calculation-engine.jpg` | Offer engine inputs (BXGY, %, Flat, Cart Value) → evaluation → outputs (discount + loyalty points) | `07-KEY-FLOWS/offer-calculation.md` |
| `credit-khata-system.jpg` | Customer Credit flow (Retailer–Customer mapping, ledger entries) + Supplier Khata flow | `07-KEY-FLOWS/credit-khata.md` |
| `customer-journey.jpg` | End-to-end customer journey: Discover → Browse → Cart → Checkout → Track → Rewards | Future journey doc |
| `retailer-pos-order-handling.jpg` | Retailer POS terminal mock + Online Order Management status workflow | Future retailer journey doc |
| `scanner-to-catalog-flow.jpg` | Flutter Scanner → Upload Session → Scan/OCR → Review → Edit → Commit to Catalog | Future scanner doc |

> **Note**: The actual image files will be uploaded into this folder in a follow-up. Mermaid versions of the core flows already exist inside the Markdown files (machine-readable).

## Naming Convention for Future Screenshots

When adding real screenshots later, use clear names such as:

- `customer-home.png`
- `customer-product-detail.png`
- `customer-cart-checkout.png`
- `retailer-pos.png`
- `retailer-product-form.png`
- `retailer-order-detail.png`
- `scanner-gateway.png`
- `scanner-review-session.png`

Always blur or remove any sensitive data before committing.
