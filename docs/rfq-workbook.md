# The RFQ workbook

## Sheets (in this order; the file opens on RFQ)
| Sheet | Content |
|---|---|
| **RFQ** | The Ferguson template's 23 columns, one row per requested product, in request order. Not-found products stay on the sheet with blank specs. |
| **Supplier** | Supplier, brand, manufacturer and Ferguson part numbers, UPC, price, availability, product page and spec sheet links, and how each product was found. |
| **Summary** | Fill rates (overall, per product, per column), what was not found and why, missing fields per product, every flag with its cell and reason, AI-check status, colour legend. |
| **Sources** | One row per filled value (RFQ and supplier): `product_id, column, value, source_type, confidence, source, link`. The link is clickable; rule-based values have none. |
| **Notes** | Duplicates, live-vs-catalog differences, fallbacks, removed rows, pictures that couldn't be embedded, warnings. |
| How to fill | The template's instructions. |
| `_rfq_meta` (hidden) | Job ID and version, so an edited copy can be uploaded and compared with what was downloaded. |

## Colours (same as the web app)
| Colour | Meaning |
|---|---|
| Grey | Missing: no source had a value |
| Orange | Check this value. The cell comment says why (rule or AI). |
| Blue | Edited by hand (in the app or via upload) |
| Tinted row | Product not found |
| Green / blue / red status | Lookup Status: Found / filled by hand / Not found |
| Green / amber / red | Sources confidence: high / medium / low |

## Image and Picture
The template has both columns. **Image** holds the embedded product picture (visible in Excel, Numbers,
LibreOffice and Google Sheets), with an `=IMAGE()` formula underneath for Excel 365. **Picture** holds the
address as a clickable link. In the web app they are one column; Image always follows Picture. Some catalog rows
hold two addresses (`a|b`): the `_primary` picture is shown, and the full value is kept.

## Download formats
| Format | Keeps | Loses |
|---|---|---|
| `.xlsx` | Everything: all sheets, colours, pictures, links, comments | — |
| `.xls` (Excel 97–2003) | All sheets, values, colours, version stamp | Pictures (the Image cell has the address), links, comments |
| `.csv` | The RFQ (or Summary) values, plus a **Review notes** column with each row's flags | Colours, other sheets, version stamp |

CSV files are UTF-8 with a BOM. Cells starting with `=` `+` `@` are prefixed with `'` so spreadsheet apps don't
run them as formulas.

## Uploading an edited copy
Accepted: `.xlsx`, `.xlsm`, `.xls`, `.csv` (comma, semicolon or tab; UTF-8 or Windows-1252), max 10 MB.
- **Checks:** the file must have the RFQ columns and belong to this request.
- **Compare:** the upload is compared with the version you downloaded (three-way), so edits made in the app since
  then show as conflicts. CSV has no version stamp, so it's compared with the current version.
- **Validation:** every changed cell is checked as if typed in the app (units, Yes/No, URLs, no formulas).
- **Preview first:** nothing is written until you tick changes and click Apply. Applied values are sourced as
  "Uploaded file '<name>'" plus your note.
