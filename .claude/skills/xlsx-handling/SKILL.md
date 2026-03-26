---
name: xlsx-handling
description: Handle large Excel files by caching sheets as CSVs first, never repeatedly parsing raw xlsx
---

# Excel File Handling

Large xlsx files (6MB+) take 30-60 seconds to parse with openpyxl. Never repeatedly open them.

## Rules

1. **Always cache first.** Before reading any xlsx data, run:
   ```
   python src/cache_xlsx.py <path_to_xlsx>
   ```
   This creates `cache/` with one CSV per sheet plus `_metadata.json`.

2. **Check if cache exists.** Before caching, check `cache/_metadata.json` — the script auto-skips if the file hash matches. If you need to force re-cache, delete `_metadata.json`.

3. **Read from cached CSVs.** Use the Read tool on `cache/<SheetName>.csv` instead of parsing the xlsx. Sheet names are sanitized (spaces → underscores, special chars removed).

4. **Find the right CSV.** Read `cache/_metadata.json` to see all sheet names and their CSV filenames, row counts, and column counts.

5. **Never use openpyxl in inline scripts.** If you need xlsx data, use the cached CSVs. If cache doesn't exist, run cache_xlsx.py first.

## Quick Reference

```bash
# Cache the NAV workbook
python src/cache_xlsx.py docs/reference/VerisCapitalAMC_NAV_20260316_working.xlsx

# Check what's cached
cat cache/VerisCapitalAMC_NAV_20260316_working/_metadata.json

# Read a specific sheet
# (use Read tool on cache/VerisCapitalAMC_NAV_20260316_working/Contract_Address_Book.csv)
```

## Cache Location

- Default: `cache/<xlsx_filename_without_extension>/` in project root
- Each xlsx gets its own subfolder named after the source file
- Custom root: `python src/cache_xlsx.py file.xlsx --output-dir /path/to/cache`
- The `cache/` folder is gitignored
