# Using the scanner app

Step-by-step guide for capturing products on your Android phone.

## Install and login

1. Install the **BuyEasy Scanner** app on your Android phone
2. Open app → **Login**
3. Use the **same username and password** as retailer.ordereasy.win
4. If your shop uses a custom server (staging), configure API URL in settings — production shops use default

## Home screen

After login you see options to **manage upload sessions**. Sessions are named batches of products you are capturing — e.g. "Aisle 1 March" or "New stock 22 Aug".

## Create or resume a session

| Action | When |
|--------|------|
| **New session** | Starting a fresh batch of products |
| **Resume session** | Continue yesterday’s work |

Give sessions clear names so manager knows what to review.

## Capture a product

Inside a session:

### Scan barcode

1. Point camera at barcode
2. App reads barcode automatically (ML Kit)
3. Barcode field fills in

### Photograph label

1. Tap camera to capture product front
2. **OCR** may read name, MRP, price from packaging
3. Review extracted text — OCR is not perfect

### Enter or edit details

| Field | Notes |
|-------|-------|
| Barcode | From scan or manual |
| Name | Product title customers will see |
| MRP | Printed maximum retail price |
| Selling price | Your shop price |
| Quantity | How many on shelf (optional at capture) |
| Product group | Link bulk/parent items if applicable |

### Save to session

Tap save — item joins the session queue. Repeat for next product.

## Sync

Sessions sync to the cloud when online. Manager can review on retailer web app even while you keep scanning.

## Tips for fast capture

| Tip | Why |
|-----|-----|
| Good lighting | Better OCR and barcode read |
| Hold steady on barcode | Fewer failed scans |
| One aisle per session | Easier review |
| Fix obvious OCR errors now | Less work at review |

## Troubleshooting

| Problem | Try |
|---------|-----|
| Barcode not scanning | Clean lens; enter manually |
| OCR wrong price | Edit before save |
| Cannot login | Check credentials; check internet |
| Session not visible on web | Wait for sync; pull to refresh on web |

→ Next: [Adding products in bulk](adding-products-in-bulk.md)
