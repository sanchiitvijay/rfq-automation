# Backup product catalog

This folder is the backup for the ferguson.com lookup in the Day 4 build.

Your flow should first try to read each product live from ferguson.com. ferguson.com blocks many automated visits, so if a lookup is blocked or times out, read the same product from this catalog instead and carry on. Mark every value you take from here with its source, the same as any other value.

The data was collected from ferguson.com on 24 September 2026. Prices and stock may have changed since.

## Files

| File | What it is |
|---|---|
| `product_catalog.csv` | One row per product, 56 products, 32 columns. Open in any tool. |
| `product_catalog.json` | The same data as JSON, keyed by `product_id`. Easiest to load in Python. |
| `product_catalog_sources.csv` | Where every value came from: one row per filled value, with its source type, confidence and source. |
| `spec_sheet_links.csv` | The manufacturer spec sheet PDF for 39 of the products. These download live (they are not blocked), so use them to practise reading values out of a document. |
| `product_catalog.xlsx` | All of the above in one workbook, plus a sheet of products that are not in the catalog. For reading, not for your code. |

## Columns

| Group | Columns |
|---|---|
| Identity | `product_id`, `Description`, `Brand`, `Manufacturer Part #`, `Ferguson Part #`, `UPC`, `Category`, `Product Family`, `Tool Type` |
| Physical specification | `Length`, `Width`, `Thickness`, `Weight`, `Material`, `Material Type`, `Color Finish`, `Lettering`, `No of Tools`, `Application`, `Temperature Range`, `Product details`, `Waterworks Application` |
| Compliance | `ANSI`, `ASTM`, `OSHA`, `UL Listed` |
| Commercial | `Price (USD)`, `Availability`, `Status` |
| Evidence and media | `Picture URL`, `Ferguson URL`, `Spec Sheet URL` |

Lists inside one cell are separated by `|` (for example several ASTM standards).

## Things to know about the data

- **Units are not consistent, on purpose: this is what real data looks like.** Most lengths are written `1000 ft`, but some are just `1000`. Widths are `3 in` or just `3`. Lengths are in feet, widths in inches, thickness in mil, weight in pounds.
- **Empty means unknown.** A blank cell means no trusted value was found. Do not fill it with a guess.
- **Confidence** in the sources file: `high` means the value is stated for this exact product or its family by Ferguson or the manufacturer; `medium` means it comes from sibling products or a family match; `low` means a pattern.
- **Source types** in the sources file: `ferguson_rfq_sample` (Ferguson's own sample RFQ), `ferguson_page` (the Ferguson product page), `spec_sheet` (the manufacturer spec sheet), `validated_rule`, `sibling_products`, `same_product_description`.

## Products that are not in the catalog

These seven IDs were not on ferguson.com when the catalog was collected (24 September 2026), so they are not in it. Check live before assuming: as of 14 October 2026, 225123 is back on ferguson.com, so a live lookup finds it. If ferguson.com does not list one of them either, show it as **not found**: never drop it silently or make up values.

| product_id | Old description |
|---|---|
| 225123 | 6 in. x 1000 ft. Water Detectable Tape |
| 225124 | 6 in. x 1000 ft. Sewer Detectable Tape |
| 502172 | 1000 ft. Detectable Tape |
| 5106892 | Marking and Underground Green 1000 ft. Adhesive Tape |
| 9677513 | 3 in. x 1000 ft. Purple Non-Detectable Underground Warning Tape |
| 9677533 | 4 in. x 1000 ft. Marking Tape in Red |
| 9677551 | 4 in. x 1000 ft. Marking Tape in Green |
