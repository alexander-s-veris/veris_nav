"""Issuer NAV pricing adapter.

Queries issuer-published NAV as a pricing source (tier 2 in A2 hierarchy).
Dispatches to the appropriate issuer source based on feed config.

These same sources also serve as verification (Section 7.3), but here
they're used as pricing fallbacks when oracle feeds (Chainlink/Pyth/Redstone)
are stale or unavailable.

Supported issuer types:
- superstate_api: Superstate REST API for USCC
- onre_onchain: OnRe Offer PDA on Solana for ONyc
- midas_pdf: Google Drive PDF reports for mF-ONE, msyrupUSDp
- midas_attestation: LlamaRisk API for mHYPER
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal

from evm import TS_FMT

logger = logging.getLogger(__name__)


def issuer_nav_price(feed_cfg: dict, expected_freq_hours: float = None) -> dict:
    """Query issuer-published NAV as a pricing source.

    Args:
        feed_cfg: Feed config from price_feeds.json with:
            - issuer_type: dispatch key (superstate_api, onre_onchain, etc.)
            - Additional fields per issuer type.
        expected_freq_hours: For staleness checking.

    Returns:
        Standard pricing result dict.
    """
    issuer_type = feed_cfg.get("issuer_type")
    if not issuer_type:
        raise ValueError("issuer_nav feed missing 'issuer_type'")

    if issuer_type == "superstate_api":
        return _superstate_nav(feed_cfg, expected_freq_hours)
    elif issuer_type == "onre_onchain":
        return _onre_nav(feed_cfg, expected_freq_hours)
    elif issuer_type == "midas_pdf":
        return _midas_pdf_nav(feed_cfg, expected_freq_hours)
    elif issuer_type == "midas_attestation":
        return _midas_attestation_nav(feed_cfg, expected_freq_hours)
    else:
        raise ValueError(f"Unknown issuer_type: {issuer_type}")


def _superstate_nav(feed_cfg: dict, expected_freq_hours: float = None) -> dict:
    """Superstate REST API NAV for USCC."""
    import requests
    from datetime import date

    api_base = feed_cfg["api_base"]
    fund_id = feed_cfg["fund_id"]

    today = date.today()
    start = today.replace(day=max(1, today.day - 7))
    url = f"{api_base}/v1/funds/{fund_id}/nav-daily"
    params = {"start_date": start.isoformat(), "end_date": today.isoformat()}

    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if not data:
        raise ValueError(f"No NAV data from Superstate for fund {fund_id}")

    latest = data[0]
    price = Decimal(latest["net_asset_value"])
    nav_date = latest["net_asset_value_date"]

    logger.info("issuer_nav.superstate: fund=%d nav=$%s date=%s", fund_id, price, nav_date)

    return _make_result(price, f"issuer_nav_superstate (fund={fund_id})",
                        notes=f"Superstate NAV {nav_date}")


def _onre_nav(feed_cfg: dict, expected_freq_hours: float = None) -> dict:
    """OnRe on-chain NAV for ONyc."""
    from solana_client import get_onre_nav

    nav = get_onre_nav()
    price = nav["price"]

    logger.info("issuer_nav.onre: price=$%s offer=%s", price, nav["offer_pda"][:12])

    return _make_result(price, f"issuer_nav_onre (offer={nav['offer_pda'][:8]}...)",
                        notes=f"OnRe step={nav['step']}")


def _midas_pdf_nav(feed_cfg: dict, expected_freq_hours: float = None) -> dict:
    """Midas PDF report NAV for mF-ONE, msyrupUSDp."""
    import os
    import re
    import fitz
    import pytesseract
    from PIL import Image
    from google.auth.transport.requests import Request as AuthRequest
    from google.oauth2 import service_account
    import requests
    from datetime import date, timedelta

    from evm import CONFIG_DIR
    import json

    # Load verification config for tools and Drive credentials
    with open(os.path.join(CONFIG_DIR, "verification.json")) as f:
        ver_cfg = json.load(f)

    tesseract_cmd = ver_cfg.get("_tools", {}).get("tesseract_cmd", "")
    if not tesseract_cmd or not os.path.exists(tesseract_cmd):
        tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    sa_key_path = ver_cfg.get("_api_endpoints", {}).get("gdrive", "")
    if not os.path.isabs(sa_key_path):
        sa_key_path = os.path.join(os.path.dirname(__file__), "..", "..", sa_key_path)

    creds = service_account.Credentials.from_service_account_file(
        sa_key_path, scopes=["https://www.googleapis.com/auth/drive.readonly"])
    creds.refresh(AuthRequest())
    headers = {"Authorization": f"Bearer {creds.token}"}

    folder_id = feed_cfg["gdrive_folder_id"]
    filename_pattern = feed_cfg["filename_pattern"]
    local_path = feed_cfg.get("local_report_path", "docs/reference/midas")

    # Navigate to current or previous month folder
    today = date.today()
    base_url = "https://www.googleapis.com/drive/v3/files"
    common = {"supportsAllDrives": "true", "includeItemsFromAllDrives": "true"}

    month_folder_id = None
    for month_offset in (0, 1):
        target = today.replace(day=1)
        if month_offset:
            target = (target - timedelta(days=1)).replace(day=1)
        year_str = str(target.year)
        month_prefix = target.strftime(f"{year_str}_%m")
        try:
            r = requests.get(base_url, params={**common, "q": f"'{folder_id}' in parents and name='{year_str}'",
                             "fields": "files(id)"}, headers=headers, timeout=15)
            yf = r.json().get("files", [])
            if not yf:
                continue
            r = requests.get(base_url, params={**common, "q": f"'{yf[0]['id']}' in parents and name contains '{month_prefix}'",
                             "fields": "files(id)"}, headers=headers, timeout=15)
            mf = r.json().get("files", [])
            if mf:
                month_folder_id = mf[0]["id"]
                break
        except Exception:
            continue

    if not month_folder_id:
        raise ValueError("Cannot find month folder in Drive")

    # Find latest PDF
    r = requests.get(base_url, params={**common, "q": f"'{month_folder_id}' in parents and mimeType='application/pdf'",
                     "fields": "files(id,name)", "orderBy": "name desc", "pageSize": "1"}, headers=headers, timeout=15)
    files = r.json().get("files", [])
    if not files:
        raise ValueError("No PDFs in month folder")

    latest = files[0]
    pdf_bytes = requests.get(f"{base_url}/{latest['id']}?alt=media", headers=headers, timeout=30).content

    # Save for audit trail
    if not os.path.isabs(local_path):
        local_path = os.path.join(os.path.dirname(__file__), "..", "..", local_path)
    os.makedirs(local_path, exist_ok=True)
    filepath = os.path.join(local_path, latest["name"])
    if not os.path.exists(filepath):
        with open(filepath, "wb") as f:
            f.write(pdf_bytes)

    # OCR
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    text = ""
    for page in doc:
        pix = page.get_pixmap(dpi=200)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        text += pytesseract.image_to_string(img)
    doc.close()

    # Parse
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    dollar_amounts = []
    bare_numbers = []
    for line in lines:
        if re.search(r"-\s*\$", line):
            continue
        for m in re.finditer(r"\$([\d,]+\.\d+)", line):
            dollar_amounts.append(Decimal(m.group(1).replace(",", "")))
        if not line.startswith("$") and re.match(r"^[\d,]+\.\d+$", line):
            bare_numbers.append(Decimal(line.replace(",", "")))

    if len(dollar_amounts) < 2 or not bare_numbers:
        raise ValueError(f"Cannot parse Midas PDF: {len(dollar_amounts)} dollar amounts, {len(bare_numbers)} bare numbers")

    total_assets = dollar_amounts[-2]
    issued_tokens = bare_numbers[-1]
    price = total_assets / issued_tokens

    logger.info("issuer_nav.midas_pdf: %s price=$%s assets=$%s issued=%s",
                latest["name"], price, total_assets, issued_tokens)

    return _make_result(price, f"issuer_nav_midas_pdf ({latest['name']})",
                        notes=f"Total assets=${total_assets}, issued={issued_tokens}")


def _midas_attestation_nav(feed_cfg: dict, expected_freq_hours: float = None) -> dict:
    """Midas attestation NAV via LlamaRisk API for mHYPER."""
    import requests
    import json
    import re
    import os
    from web3 import Web3

    from evm import CONFIG_DIR, get_web3
    from handlers import _get_abi

    # Load verification config for API base
    with open(os.path.join(CONFIG_DIR, "verification.json")) as f:
        ver_cfg = json.load(f)
    api_base = ver_cfg.get("_api_endpoints", {}).get("llamarisk", "")

    proof_id = feed_cfg["proof_id"]
    token_addresses = feed_cfg["token_addresses"]
    token_decimals = feed_cfg.get("token_decimals", 18)

    # Fetch attestation
    url = f"{api_base}/proof/midas/{proof_id}"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    last_att = data.get("last_attestation", {})
    att_json = last_att.get("attestation_json", {})
    total_nav = None
    for claim in att_json.get("claims", []):
        if claim.get("claimType") != "inline":
            continue
        body_str = claim.get("data", {}).get("response", {}).get("body", "")
        try:
            email_data = json.loads(body_str) if isinstance(body_str, str) else body_str
            snippet = email_data.get("snippet", "")
            m = re.search(r"Total\s+NAV:\s*([\d,.]+)", snippet)
            if m:
                total_nav = Decimal(m.group(1).replace(",", ""))
                break
        except Exception:
            continue

    if total_nav is None:
        raise ValueError(f"Cannot extract NAV from attestation {proof_id}")

    # Query totalSupply across chains
    erc20_abi = _get_abi("erc20")
    total_supply = Decimal(0)
    for chain, addr in token_addresses.items():
        try:
            w3 = get_web3(chain)
            contract = w3.eth.contract(address=Web3.to_checksum_address(addr), abi=erc20_abi)
            raw = contract.functions.totalSupply().call()
            total_supply += Decimal(str(raw)) / Decimal(10 ** token_decimals)
        except Exception:
            continue

    if total_supply <= 0:
        raise ValueError("Aggregate totalSupply is zero")

    price = total_nav / total_supply

    logger.info("issuer_nav.midas_attestation: nav=$%s supply=%s price=$%s", total_nav, total_supply, price)

    return _make_result(price, f"issuer_nav_midas_attestation",
                        notes=f"NAV=${total_nav}, supply={total_supply}")


def _make_result(price: Decimal, source: str, notes: str = "") -> dict:
    return {
        "price_usd": price,
        "price_source": source,
        "oracle_updated_at": None,
        "staleness_hours": None,
        "stale_flag": "",
        "depeg_flag": "none",
        "depeg_deviation_pct": None,
        "notes": notes,
    }
