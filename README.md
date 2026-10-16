# Day 4 starter kit: the Ferguson RFQ challenge

Follow the Day 4 guide shared by your instructor. It walks you through Part A (build the base), Part B (your agentic arm), deploying on Azure, and how you are judged.

## What is in this kit

| Folder | What it is |
|---|---|
| `emails/` | Four sample request emails as `.eml` files. Python reads them with the built-in `email` package. `rfq_items.xlsx` is the attachment inside email 2, also saved on its own. |
| `data/` | The backup product catalog, where every value came from, and the spec sheet PDF links. See `data/README.md`. |
| `templates/rfq_template.xlsx` | The RFQ template your flow fills: RFQ sheet, Sources sheet, and a "How to fill" sheet. |
| `reference/email-1 reference output.xlsx` | The correct output for email 1. Test your Part A against it. |

## The emails

| File | What makes it different |
|---|---|
| `email-1-ids-in-body.eml` | Product IDs in the email body, one per line |
| `email-2-ids-in-attachment.eml` | Product IDs in an Excel attachment |
| `email-3-mixed-ferguson-and-competitor.eml` | Ferguson IDs and competitor part numbers in one list |
| `email-4-messy-forward.eml` | A forwarded thread: IDs inside sentences, with `#` in front, one ID listed twice |

## Ground rules

- Blank means unknown. Never guess a value.
- Every value you fill needs a source on the Sources sheet.
- A product you cannot find stays on the RFQ sheet as `Not found`.
- No solution code is included. You build it.
- Keep your API keys in a `.env` file. It is already ignored by git, so it is never uploaded.
