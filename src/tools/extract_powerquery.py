"""
Extract Power Query / M code definitions from an Excel workbook.

The M code is stored inside the xlsx zip archive as a DataMashup blob:
  customXml/item2.xml  →  base64-decoded  →  inner zip  →  Formulas/Section1.m

This script extracts all shared definitions and saves each as a separate .m file,
plus a combined Section1.m with the full source.

Usage:
    python src/extract_powerquery.py <path_to_xlsx> [--output-dir <dir>]

Output:
    cache/<workbook_name>/powerquery/Section1.m          (full combined M code)
    cache/<workbook_name>/powerquery/<query_name>.m      (one per shared definition)
    cache/<workbook_name>/powerquery/_index.txt           (list of all definitions)
"""
import argparse
import base64
import os
import re
import struct
import sys
import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO
from pathlib import Path


def find_datamashup_item(zf: zipfile.ZipFile) -> str | None:
    """Find the customXml item that contains the DataMashup."""
    for name in zf.namelist():
        if not name.startswith("customXml/itemProps"):
            continue
        raw = zf.read(name)
        # Check raw bytes for DataMashup — avoids encoding issues
        if b"DataMashup" in raw:
            item_num = re.search(r"itemProps(\d+)", name)
            if item_num:
                return f"customXml/item{item_num.group(1)}.xml"
    return None


def extract_m_code(xlsx_path: str) -> str:
    """Extract the full M code string from an xlsx file."""
    with zipfile.ZipFile(xlsx_path, "r") as zf:
        item_path = find_datamashup_item(zf)
        if not item_path:
            raise ValueError("No DataMashup found in this workbook")

        raw = zf.read(item_path)
        try:
            text = raw.decode("utf-16")
        except (UnicodeDecodeError, UnicodeError):
            text = raw.decode("utf-8")

        root = ET.fromstring(text)
        b64_data = root.text
        if not b64_data or not b64_data.strip():
            raise ValueError("DataMashup element has no content")

        decoded = base64.b64decode(b64_data.strip())

        # Binary format: 4-byte version + 4-byte package length + package (zip)
        pkg_len = struct.unpack("<I", decoded[4:8])[0]
        pkg_data = decoded[8 : 8 + pkg_len]

        inner = zipfile.ZipFile(BytesIO(pkg_data))
        # M code is in Formulas/Section1.m (all queries concatenated)
        for name in inner.namelist():
            if name.endswith(".m"):
                return inner.read(name).decode("utf-8")

        raise ValueError("No .m file found in DataMashup package")


def split_definitions(m_code: str) -> list[tuple[str, str]]:
    """Split M code into individual shared definitions.

    Returns list of (name, full_definition_text) tuples.
    """
    # Pattern: "shared <name> = ... ;" where the semicolon at the end of the
    # definition is followed by either another "shared" or end of string.
    # We split on the "shared" keyword boundaries.
    parts = re.split(r"(?=\bshared\s+)", m_code)
    definitions = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        match = re.match(r"shared\s+(\w+)\s*=", part)
        if match:
            name = match.group(1)
            # Remove trailing semicolon if present
            body = part.rstrip().rstrip(";").strip()
            definitions.append((name, body + ";"))
    return definitions


def main():
    parser = argparse.ArgumentParser(description="Extract Power Query M code from xlsx")
    parser.add_argument("xlsx_path", help="Path to the xlsx file")
    parser.add_argument("--output-dir", help="Output directory (default: cache/<workbook>/powerquery/)")
    args = parser.parse_args()

    xlsx_path = args.xlsx_path
    if not os.path.exists(xlsx_path):
        print(f"Error: {xlsx_path} not found")
        sys.exit(1)

    # Determine output directory
    if args.output_dir:
        out_dir = args.output_dir
    else:
        workbook_name = Path(xlsx_path).stem
        out_dir = os.path.join("cache", workbook_name, "powerquery")

    os.makedirs(out_dir, exist_ok=True)

    print(f"Extracting Power Query from: {xlsx_path}")
    m_code = extract_m_code(xlsx_path)
    print(f"  Total M code: {len(m_code):,} characters")

    # Save full combined file
    full_path = os.path.join(out_dir, "Section1.m")
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(m_code)
    print(f"  Saved: {full_path}")

    # Split and save individual definitions
    definitions = split_definitions(m_code)
    print(f"  Found {len(definitions)} shared definitions")

    index_lines = []
    for name, body in definitions:
        file_path = os.path.join(out_dir, f"{name}.m")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(body + "\n")
        # Classify: p_ = parameter, fn_ = function, q_ = query, cg_ = coingecko
        if name.startswith("p_"):
            kind = "parameter"
        elif name.startswith("fn_"):
            kind = "function"
        elif name.startswith("q_"):
            kind = "query"
        elif name.startswith("cg_"):
            kind = "coingecko"
        else:
            kind = "other"
        index_lines.append(f"{name:45s} {kind}")

    # Save index
    index_path = os.path.join(out_dir, "_index.txt")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(f"Power Query definitions from {Path(xlsx_path).name}\n")
        f.write(f"{'=' * 60}\n\n")
        for line in index_lines:
            f.write(line + "\n")

    print(f"  Saved: {index_path}")
    print(f"  Output directory: {out_dir}")


if __name__ == "__main__":
    main()
