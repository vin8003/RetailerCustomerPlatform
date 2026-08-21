# 02 – System Architecture

## Overview

The platform follows a classic **API-first** architecture. All client applications (Customer App, Retailer Dashboard/POS, and Scanner) communicate exclusively with the central Django backend via HTTPS + JWT authentication.

## High-Level Architecture

![System Architecture Overview](../visuals/architecture-overview.jpg)

*Illustrative diagram: Customer App, Retailer Dashboard + POS, and Flutter Scanner App all talk to the central Django REST API at `api.ordereasy.win` using JWT authentication.*

```mermaid
flowchart TB
    subgraph Clients
        CA[Customer App<br/>Next.js + Capacitor]
        RA[Retailer Dashboard + POS<br/>Next.js]
        SA[Flutter Scanner App]
    end

    subgraph Backend
        API[Django REST API<br/>api.ordereasy.win]
        DB[(PostgreSQL)]
        FCM[Firebase FCM]
    end

    CA -->|JWT + HTTPS| API
    RA -->|JWT + HTTPS| API
    SA -->|JWT + Upload Sessions| API

    API --> DB
    API --> FCM
```

### Key points

- **API Gateway / Backend**: Single Django + DRF application that owns all business logic, data models, and rules.
- **Database**: PostgreSQL (with trigram extensions for search).
- **Notifications**: Firebase Cloud Messaging (FCM) for push notifications.
- **Authentication**: JWT (access + refresh tokens) + OTP flows.
- **Clients** are thin: they handle UI/UX and call the API. No business logic is duplicated in the frontends.

## Component Responsibilities

| Component | Responsibility |
|-----------|----------------|
| Backend (`RetailerCustomerPlatform`) | Auth, Products, Batches, Inventory, Cart, Orders, Offers engine, Loyalty, Credit/Khata, Purchases, Returns, Scanner upload sessions |
| Customer App | Discovery, catalog browsing, cart, checkout, order tracking, rewards, chat |
| Retailer Dashboard + POS | Order management, POS billing, product & batch management, purchases, offers, customer CRM, reports |
| Scanner App | Barcode scanning, image capture + OCR, upload sessions for bulk product creation |

## Data Flow Principle

All state changes go through the backend. The frontends never write directly to the database. This ensures a single source of truth for inventory, pricing, offers, and order status.
