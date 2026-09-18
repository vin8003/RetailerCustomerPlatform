# Scout docs

Scout output only. These files are **not** Jira status.

| File | What |
|------|------|
| [PR-149-OE-339-353-REMAP.md](PR-149-OE-339-353-REMAP.md) | **FREEZE** #149 draft labels `OE-339`–`OE-353` (they collide with live Jira). Remap remaining slice titles to unused keys `OE-367`+. |

## Builder lock

Do **not** launch builds against #149 draft collisions `OE-339`–`OE-353`. Those numbers are live Jira keys with **different** titles. Use remapped keys from the table **only after that remap doc lands**. Do not remint over `OE-339`–`OE-353`. Do not implement those draft slices in this folder.

Dummy / local only. Never `*.ordereasy.win`. No merge. No Jira Done flips.
