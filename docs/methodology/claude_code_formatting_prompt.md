# PDF Formatting Instructions

Apply all of the following formatting fixes to the NAV Data Sourcing Methodology PDF:

## 1. Remove grey background artifacts
Remove all highlight annotations and grey background rectangles from the PDF. Strip any grey shading behind text passages while preserving all text and formatting. If the grey backgrounds are in the content stream (not annotations), parse each page's content stream and remove rectangle fill operations that use grey colors.

## 2. Table column auto-sizing and styling
Distribute table column widths based on content length — don't use equal-width columns. Give more width to columns with longer content and less to columns with short content, so short text like "HyperEVM", "PYUSD", "Solana", or "13-May-2026" doesn't wrap unnecessarily. Auto-size columns to fit their longest content where possible. Style table header rows with dark navy blue background (#2c3e6b) and white bold text. Table body rows use white background with black text.

## 3. Wrap long hex addresses
Wrap long hex addresses and feed IDs in table cells so they break across lines cleanly within the column boundaries, instead of overflowing. Use word-break or insert line breaks at a reasonable character count (e.g., every 40-50 characters).

## 4. Keep tables together across pages
Keep tables together — never split a table header row onto a different page from its data rows. If a table doesn't fit at the bottom of a page, move the entire table (header + rows) to the next page. No orphaned headers. Use CSS `break-inside: avoid` on table elements.

## 5. Keep headings with following content
Keep section headings together with the paragraph or content that follows them. If a heading would land at the bottom of a page with no body text below it, move the heading to the next page. No orphaned headings. Use CSS `break-after: avoid` on heading elements.

## 6. Keep list items together
Keep numbered/lettered list items together with their sub-items — don't split a sub-list like "(a) Chainlink, (b) Pyth Network, (c) Redstone" across a page break. Wrap the parent list item and all its children in a `break-inside: avoid` block.

## 7. Format numbered/lettered items as proper lists
When content has numbered or lettered items (like "1. ... 2. ... 3. ..." or "(a) ... (b) ... (c) ..."), format them as actual multi-line lists with line breaks, not as inline run-on text. Each numbered or lettered item should start on its own line.

## 8. Restore bullet markers on sub-items
Sub-items nested under numbered list items must have bullet markers (•). For example, under "General Principles" item 4, the fields (contract address, function called, etc.) need bullets. Same for Section 5 Verification item 1 (DeBank, Octav) and Section 6 Output Format item 1.

## 9. Format long field lists in code blocks
When a list item includes a long comma-separated field list (like CSV column names), put those fields on an indented line or in a monospace code block below the item, rather than running them inline in the paragraph. Applies specifically to the CSV fields in Section 6.

## 10. Replace em dashes
Replace all em dashes (—) with regular hyphens (-) or en dashes (–) throughout the document.

## 11. Consistent monospace formatting
Use monospace formatting consistently for all code-like terms: function names, contract calls, field names, file names, and variable names throughout the document. Style inline code with: monospace font at 9pt (body text is 10pt), light grey background (#f0f0f0), rounded corners (border-radius: 3px), and slight padding (2px 5px). GitHub-style rendering.

## 12. Page numbers and running header — no duplicates
Add page numbers ("Page X of Y") in the footer. Add a running header with the document title and ISIN (LI1536896288). Ensure the header/footer appears only ONCE per page — not duplicated at both top and bottom of the same page.

## 13. Add Table of Contents
Add a Table of Contents on page 1 after the preamble, listing all sections and subsections.
