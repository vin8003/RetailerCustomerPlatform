# OrderEasy thin-ticket backlog (scout)

Mint-ready **thin** ticket specs so CA slots are not blocked by in-flight search-Meta / cart / returns / FE list-detail locks.

This folder is **scout output only**. Do **not** treat these files as Jira status. Do **not** mark anything Done. Dummy / local only — never `*.ordereasy.win`. Never merge.

| File | What |
|------|------|
| [BACKLOG.md](BACKLOG.md) | Round-2 pack: isolation map, minted 301–338, draft **OE-339–353** |
| [MINTED-REMAP.md](MINTED-REMAP.md) | Round-1 draft labels → actual minted keys (do not re-mint) |
| [OE-339-DRAFT.md](OE-339-DRAFT.md) | Top-1 stub — PurchaseReturnModal `unit` |
| [OE-340-DRAFT.md](OE-340-DRAFT.md) | Top-2 stub — ProductForm `saleable_quantity` hint |
| [OE-341-DRAFT.md](OE-341-DRAFT.md) | Top-3 stub — customer shop `delivery_charge` |
| [OE-342-DRAFT.md](OE-342-DRAFT.md) | Top-4 stub — POSReturnModal `unit` |
| [OE-343-DRAFT.md](OE-343-DRAFT.md) | Top-5 stub — wishlist `brand_name` BE (after OE-305) |

Round-1 stubs `OE-313-DRAFT.md`…`OE-317-DRAFT.md` are **superseded** (those keys were minted, some titles remapped). See [MINTED-REMAP.md](MINTED-REMAP.md).

Scout bases: docs PR **#143** tip `cd43729`; BE PR **#130** tip `d022f37`; Jira highest minted at scout: **OE-338**. If those draft keys are taken before mint, keep the file slices and use the next free OE keys.
