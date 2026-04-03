"""
Midas PDF Report verifier.

Cross-checks Midas token oracle prices against issuer-published PDF
reports hosted on Google Drive. Used for tokens where the attestation
engine (LlamaRisk) is not available.

Flow:
  1. Authenticate with Google Drive via service account
  2. List PDFs in the configured folder, find the latest by filename date
  3. Download PDF, save locally for audit trail
  4. Render PDF to image via pymupdf, OCR via Tesseract
  5. Parse: Total assets, Issued tokens, Price as of report Date
  6. Compute: verified_price = total_assets / issued_tokens
  7. Compare against primary oracle price -> divergence %
  8. Flag if report is stale (report date vs NAV date)

Per Valuation Policy Section 7.3 (Asset-level verification).
"""

import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import fitz  # pymupdf
import requests
from PIL import Image
import pytesseract

from evm import CONFIG_DIR, TS_FMT

logger = logging.getLogger(__name__)


def _get_tesseract_cmd(tools_cfg: dict) -> str:
    """Get Tesseract binary path from verification.json _tools config."""
    cmd = tools_cfg.get("tesseract_cmd", "")
    if cmd and os.path.exists(cmd):
        return cmd
    # Platform default fallback
    default = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if os.path.exists(default):
        return default
    raise FileNotFoundError(
        "Tesseract OCR not found. Install it and set _tools.tesseract_cmd "
        "in verification.json"
    )


def _get_drive_credentials(sa_key_path: str):
    """Load Google Drive service account credentials.

    Args:
        sa_key_path: Path to service account JSON key file
                     (relative to project root or absolute).
    """
    from google.auth.transport.requests import Request as AuthRequest
    from google.oauth2 import service_account

    # Resolve relative path from project root
    if not os.path.isabs(sa_key_path):
        project_root = os.path.join(os.path.dirname(__file__), "..", "..")
        sa_key_path = os.path.join(project_root, sa_key_path)

    creds = service_account.Credentials.from_service_account_file(
        sa_key_path,
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
    )
    creds.refresh(AuthRequest())
    return creds


def _list_pdfs(creds, folder_id: str) -> list[dict]:
    """List PDF files in a Google Drive folder via REST API.

    Returns list of {id, name, createdTime} dicts sorted by createdTime descending.
    """
    url = "https://www.googleapis.com/drive/v3/files"
    params = {
        "q": f"'{folder_id}' in parents and mimeType='application/pdf'",
        "fields": "files(id,name,createdTime)",
        "orderBy": "createdTime desc",
        "pageSize": 50,
        "supportsAllDrives": "true",
        "includeItemsFromAllDrives": "true",
    }
    headers = {"Authorization": f"Bearer {creds.token}"}

    resp = requests.get(url, params=params, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.json().get("files", [])


def _extract_date_from_filename(filename: str) -> date | None:
    """Try to extract a YYYYMMDD date from a filename."""
    m = re.search(r"(\d{8})", filename)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y%m%d").date()
        except ValueError:
            pass
    return None


def _find_latest_pdf(files: list[dict]) -> tuple[dict, date]:
    """Find the latest PDF from a list of Drive files.

    Name-agnostic: picks the most recent file by embedded YYYYMMDD date
    in the filename, or by createdTime if no date is found.
    Returns (file_dict, report_date).
    """
    if not files:
        raise ValueError("No PDF files in folder")

    # Try to extract dates from filenames first
    best_file = None
    best_date = None
    for f in files:
        file_date = _extract_date_from_filename(f["name"])
        if file_date and (best_date is None or file_date > best_date):
            best_file = f
            best_date = file_date

    if best_file:
        return best_file, best_date

    # Fallback: use createdTime (files are already sorted desc)
    f = files[0]
    created = f.get("createdTime", "")
    if created:
        report_date = datetime.fromisoformat(created.replace("Z", "+00:00")).date()
    else:
        report_date = date.today()
    return f, report_date


def _find_month_folder(creds, parent_folder_id: str, target_date: date) -> str:
    """Navigate the year/month folder hierarchy to find the right subfolder.

    Structure: root -> YYYY -> YYYY_MM_Mon (e.g. 2026 -> 2026_03_Mar)
    Returns the folder ID containing PDFs for the target month.
    """
    headers = {"Authorization": f"Bearer {creds.token}"}
    base_url = "https://www.googleapis.com/drive/v3/files"
    common_params = {
        "supportsAllDrives": "true",
        "includeItemsFromAllDrives": "true",
    }

    # Find year folder
    year_str = str(target_date.year)
    params = {
        **common_params,
        "q": f"'{parent_folder_id}' in parents and name='{year_str}' and mimeType='application/vnd.google-apps.folder'",
        "fields": "files(id,name)",
    }
    resp = requests.get(base_url, params=params, headers=headers, timeout=15)
    resp.raise_for_status()
    year_folders = resp.json().get("files", [])
    if not year_folders:
        raise ValueError(f"No '{year_str}' folder found in Drive folder {parent_folder_id}")
    year_folder_id = year_folders[0]["id"]

    # Find month folder (pattern: YYYY_MM_Mon)
    month_prefix = target_date.strftime(f"{year_str}_%m")
    params = {
        **common_params,
        "q": f"'{year_folder_id}' in parents and name contains '{month_prefix}' and mimeType='application/vnd.google-apps.folder'",
        "fields": "files(id,name)",
    }
    resp = requests.get(base_url, params=params, headers=headers, timeout=15)
    resp.raise_for_status()
    month_folders = resp.json().get("files", [])
    if not month_folders:
        raise ValueError(f"No '{month_prefix}*' folder found in year folder {year_folder_id}")

    logger.info("Drive folder: %s -> %s", year_str, month_folders[0]["name"])
    return month_folders[0]["id"]


def _download_pdf(creds, file_id: str) -> bytes:
    """Download a file from Google Drive by ID."""
    url = f"https://www.googleapis.com/drive/v3/files/{file_id}"
    params = {"alt": "media"}
    headers = {"Authorization": f"Bearer {creds.token}"}

    resp = requests.get(url, params=params, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.content


def _save_report(content: bytes, local_path: str, filename: str,
                  report_date: date) -> str:
    """Save PDF to local path in a month subfolder for audit trail.

    Mirrors the Google Drive folder structure: local_path/YYYY_MM_Mon/filename.
    Returns full file path.
    """
    # Resolve relative path from project root
    if not os.path.isabs(local_path):
        project_root = os.path.join(os.path.dirname(__file__), "..", "..")
        local_path = os.path.join(project_root, local_path)

    # Organize into month subfolder: YYYY_MM_Mon (e.g. 2026_04_Apr)
    month_folder = report_date.strftime("%Y_%m_%b")
    save_dir = os.path.join(local_path, month_folder)
    os.makedirs(save_dir, exist_ok=True)

    filepath = os.path.join(save_dir, filename)
    if not os.path.exists(filepath):
        with open(filepath, "wb") as f:
            f.write(content)
        logger.info("Saved report: %s", filepath)
    return filepath


def _ocr_pdf(pdf_bytes: bytes, tesseract_cmd: str) -> str:
    """Render PDF to image and extract text via Tesseract OCR.

    Args:
        pdf_bytes: Raw PDF file content.
        tesseract_cmd: Path to Tesseract binary.

    Returns:
        Extracted text from the PDF.
    """
    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    text = ""
    for page in doc:
        pix = page.get_pixmap(dpi=200)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        text += pytesseract.image_to_string(img)
    doc.close()

    return text


def _parse_report(text: str) -> dict:
    """Parse OCR text from a Midas PDF report.

    Extracts: total_assets, issued_tokens, report_price.
    Returns dict with Decimal values.
    """
    # OCR reads the PDF table in two passes: left column labels first, then
    # right column values. So labels and values are on separate lines.
    # Strategy: extract all dollar amounts and bare numbers, then match by
    # position relative to known labels.
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

    # Collect all positive dollar amounts and bare numbers in order.
    # Negative amounts (e.g. "-$ 26,907,322.65" for redemptions) are
    # excluded — they're intermediate line items, not totals.
    dollar_amounts = []
    bare_numbers = []
    for line in lines:
        # Skip lines with negative dollar amounts (redemption/burn entries)
        if re.search(r"-\s*\$", line):
            continue
        for m in re.finditer(r"\$([\d,]+\.\d+)", line):
            dollar_amounts.append(Decimal(m.group(1).replace(",", "")))
        # Bare numbers (no dollar sign) — for issued token totals
        # Strip spaces first: OCR sometimes inserts spaces inside numbers
        clean = line.replace(" ", "")
        if not clean.startswith("$") and re.match(r"^[\d,]+\.\d+$", clean):
            bare_numbers.append(Decimal(clean.replace(",", "")))

    # The Midas report structure (consistent across all reports):
    #   Collateral section dollar amounts: [strategy, reserve, funds_in_process, total_assets]
    #   Then: report_price
    # Total assets is the last dollar amount before Price
    # Report price is the last dollar amount overall
    if len(dollar_amounts) < 2:
        raise ValueError(
            f"Expected at least 2 dollar amounts, found {len(dollar_amounts)}")

    total_assets = dollar_amounts[-2]  # second to last
    report_price = dollar_amounts[-1]  # last

    # Issued tokens: the bare number that appears after "Total" label
    # (the aggregate of issued mToken tokens across chains)
    # There may be per-chain amounts too; the total is the last bare number
    # before the dollar amounts section starts
    issued_tokens = bare_numbers[-1] if bare_numbers else None

    if total_assets is None:
        raise ValueError(f"Cannot parse 'Total assets' from report text")
    if issued_tokens is None:
        raise ValueError(f"Cannot parse issued token total from report text")

    return {
        "total_assets": total_assets,
        "issued_tokens": issued_tokens,
        "report_price": report_price,
    }


def verify(config: dict, primary_price: Decimal, api_base: str) -> dict:
    """Verify a Midas token price against its issuer PDF report.

    Args:
        config: Verification entry from verification.json with:
            - gdrive_folder_id: Google Drive root folder ID
            - local_report_path: local directory for audit trail
            - expected_report_freq_days: for staleness flagging
            - max_report_age_days: max acceptable age of report vs today
        primary_price: The primary oracle price to verify against.
        api_base: Path to service account JSON key file (from _api_endpoints.gdrive).

    Returns:
        Verification result dict.
    """
    from verifiers import _load_verification_cfg

    ver_cfg = _load_verification_cfg()
    tools_cfg = ver_cfg.get("_tools", {})
    tesseract_cmd = _get_tesseract_cmd(tools_cfg)

    folder_id = config["gdrive_folder_id"]
    local_path = config.get("local_report_path", "docs/reference/midas")
    max_age_days = config.get("max_report_age_days", 10)
    expected_freq = config.get("expected_report_freq_days", 2)

    # Resolve local path
    if not os.path.isabs(local_path):
        local_path = os.path.join(os.path.dirname(__file__), "..", "..", local_path)

    # Fast path: use cached result only if the report is recent enough
    import glob as _glob
    import json as _json
    local_pdfs = sorted(
        _glob.glob(os.path.join(local_path, "**", "*.pdf"), recursive=True),
        reverse=True)
    cached_result = None

    if local_pdfs:
        latest_local = local_pdfs[0]
        cache_path = latest_local + ".cache.json"
        if os.path.exists(cache_path):
            file_date = _extract_date_from_filename(os.path.basename(latest_local))
            report_date = file_date or date.today()
            report_age = (date.today() - report_date).days

            if report_age <= expected_freq:
                with open(cache_path) as f:
                    cached_result = _json.load(f)
                logger.info("Using cached PDF result: %s (age: %d days)",
                             os.path.basename(latest_local), report_age)
            else:
                logger.info("Cached report %s is %d days old (threshold: %d), checking Drive for newer",
                             os.path.basename(latest_local), report_age, expected_freq)

    if cached_result:
        total_assets = Decimal(cached_result["total_assets"])
        issued_tokens = Decimal(cached_result["issued_tokens"])
        report_filename = cached_result.get("filename", os.path.basename(latest_local))
    else:
        # Full path: Drive download + OCR
        # 1. Authenticate with Google Drive
        creds = _get_drive_credentials(api_base)

        # 2. Navigate to current month folder, grab latest PDF.
        #    Try current month first, then previous.
        today = date.today()
        latest_file = None
        report_date = None
        for month_offset in (0, 1):
            try:
                target = today.replace(day=1)
                if month_offset:
                    target = (target - timedelta(days=1)).replace(day=1)
                month_folder_id = _find_month_folder(creds, folder_id, target)
                files = _list_pdfs(creds, month_folder_id)
                if files:
                    latest_file, report_date = _find_latest_pdf(files)
                    break
            except ValueError:
                continue

        if latest_file is None:
            raise ValueError(
                f"No PDFs found in Drive for {today.strftime('%Y-%m')} or previous month")
        logger.info("Latest report: %s (date: %s)", latest_file["name"], report_date)

        # 3. Download and save in month subfolder for audit trail
        pdf_bytes = _download_pdf(creds, latest_file["id"])
        filepath = _save_report(pdf_bytes, local_path, latest_file["name"], report_date)

        # 4. OCR and parse
        text = _ocr_pdf(pdf_bytes, tesseract_cmd)
        parsed = _parse_report(text)

        total_assets = parsed["total_assets"]
        issued_tokens = parsed["issued_tokens"]
        report_filename = latest_file["name"]

        # Cache parsed result alongside the PDF
        cache_path = filepath + ".cache.json"
        with open(cache_path, "w") as f:
            _json.dump({"price": str(total_assets / issued_tokens),
                         "total_assets": str(total_assets),
                         "issued_tokens": str(issued_tokens),
                         "filename": report_filename}, f)

    # 5. Compute verified price
    verified_price = total_assets / issued_tokens

    # 6. Divergence vs primary oracle price
    if primary_price > 0:
        divergence_pct = ((verified_price - primary_price) / primary_price) * Decimal(100)
    else:
        divergence_pct = Decimal(0)

    # 7. Staleness check
    today = date.today()
    report_age_days = (today - report_date).days
    stale_flag = ""
    if report_age_days > max_age_days:
        stale_flag = (
            f"STALE_REPORT: report date {report_date} is {report_age_days} days old "
            f"(max {max_age_days} days)"
        )

    now_utc = datetime.now(timezone.utc).strftime(TS_FMT)

    return {
        "source": "midas_pdf_report",
        "verified_price_usd": verified_price,
        "divergence_pct": divergence_pct,
        "divergence_flag": "",  # set by dispatcher based on category threshold
        "verification_timestamp": now_utc,
        "stale_flag": stale_flag,
        "details": {
            "total_nav_usd": str(total_assets),
            "total_supply": str(issued_tokens),
            "report_price": str(verified_price),
            "report_date": str(report_date),
            "report_filename": report_filename,
            "report_age_days": report_age_days,
            "computed_price": str(verified_price),
        },
    }
