# OrderEasy / BuyEasy Platform – Knowledge Base Index

This is the central knowledge base for the entire multi-repository project.

It is designed for both humans and AI agents.

## Structure

| File / Folder | Description |
|---------------|-------------|
| [01-OVERVIEW.md](01-OVERVIEW.md) | Project identity, purpose, value proposition, component map |
| [02-ARCHITECTURE.md](02-ARCHITECTURE.md) | High-level system architecture (Mermaid + explanation) |
| [03-USER-JOURNEYS.md](03-USER-JOURNEYS.md) | Customer and Retailer journeys (text + Mermaid) |
| [04-DOMAIN-MODELS/](04-DOMAIN-MODELS/) | Core domain models (Products, Orders, Offers, Credit, etc.) |
| [05-API-SURFACE.md](05-API-SURFACE.md) | High-level API overview |
| [06-FRONTEND-APPS/](06-FRONTEND-APPS/) | Customer App, Retailer App, Scanner App |
| [07-KEY-FLOWS/](07-KEY-FLOWS/) | Detailed key business flows |
| [08-SETUP.md](08-SETUP.md) | Setup and development notes |
| [visuals/](visuals/) | Illustrative diagrams and placeholders for screenshots |

## Canonical Diagrams

- System Architecture
- Order Status Lifecycle
- Inventory & Batch Logic
- Offer Calculation Engine
- Credit / Khata System
- Scanner Upload Flow
- Customer Journey

## Design Principles

- Text is primary. Diagrams support the text.
- Prefer Mermaid for machine-readable diagrams.
- Small, focused documents.
- Three layers: Human-readable explanation → Mermaid → Visuals.
- Every important visual has a textual explanation.

---

**Repositories**

- Backend: `RetailerCustomerPlatform`
- Customer App: `customer_ordereasy_njs`
- Retailer App: `retailer_ordereasy_njs`
- Scanner: `buyeasy_retailer_scanner`
