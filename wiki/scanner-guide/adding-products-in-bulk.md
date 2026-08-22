# Adding products in bulk

After staff capture products in the **scanner app**, the shop manager **reviews and commits** them in the retailer web app.

## Open bulk add

1. Log into [retailer.ordereasy.win](https://retailer.ordereasy.win)
2. Go to **Products** → **Bulk add**
3. You see **upload sessions** from scanner (and Excel uploads if used)

## Review a session

Tap a session to open **session detail**:

- List of captured items
- Barcode, name, prices, photos
- Flags for duplicates or missing fields

## Edit before commit

Fix common issues:

| Issue | Fix |
|-------|-----|
| Wrong name from OCR | Edit text |
| Duplicate barcode | Merge or skip |
| Missing category | Assign category |
| Wrong unit | Set kg/piece/pack |
| Bad photo | Re-capture in scanner or upload on web |

**Do not commit** until prices and names look right — customers will see these immediately.

## Commit to catalog

When satisfied:

1. Select items to import (or all)
2. Tap **Commit** (or equivalent confirm action)
3. Products appear in main **Products** list
4. Stock and POS search work immediately

## After commit

- Test one product at **POS** barcode scan
- Check one product on **customer app**
- Deactivate any mistakes rather than deleting if already sold

## Excel bulk upload (alternative)

If you have a spreadsheet instead of scanner:

1. Download template from Bulk add
2. Fill rows offline
3. Upload file
4. Fix validation errors
5. Confirm import

Use scanner for shelf walk; use Excel if you already maintain master data in sheets.

## When to use which method

| Method | Best for |
|--------|----------|
| Scanner + review | Physical store, no existing spreadsheet |
| Excel | Migrating from another system |
| Manual add | Few new SKUs per week |

→ [Products and stock](../retailer-guide/products-and-stock.md)
