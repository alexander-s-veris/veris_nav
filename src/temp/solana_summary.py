"""One-off: Print full Solana wallet position table across all protocols."""
import time, math, os, requests
from decimal import Decimal
from datetime import date
from dotenv import load_dotenv
from web3 import Web3

load_dotenv()
import sys; sys.path.insert(0, os.path.dirname(__file__) + "/..")

from solana_client import (
    get_kamino_obligation, get_eusx_exchange_rate,
    get_exponent_lp_positions, get_exponent_yt_positions,
    get_exponent_market, decompose_exponent_lp, solana_rpc,
)
from pt_valuation import value_pt_from_config
from pricing import get_price

wallet = "ASQ4kYjSYGUYbbYtsaLhUeJS6RtrN4Uwp4XbF4gDifvr"
vdate = date(2026, 3, 27)
w3 = Web3(Web3.HTTPProvider(
    "https://eth-mainnet.g.alchemy.com/v2/" + os.getenv("ALCHEMY_API_KEY")
))

# --- Prices ---
uscc_p = get_price({"symbol": "USCC", "pricing": {"method": "pyth", "pyth_feed_id": "0x5d73a5953dc86c4773adc778c30e8a6dfc94c5c3a74d7ebb56dd5e70350f044a"}}, w3)["price_usd"]
onyc_p = get_price({"symbol": "ONyc", "pricing": {"method": "pyth", "pyth_feed_id": "0xbabbfcc7f46b6e7df73adcccece8b6782408ed27c4e77f35ba39a449440170ab"}}, w3)["price_usd"]

r = requests.get("https://hermes.pyth.network/v2/updates/price/latest",
    params={"ids[]": "0x85d11b381ccc3e3021b7f84fa757cc01b9b5b5b1b899192b28bae7429e92926b"}, timeout=10)
pd = r.json()["parsed"][0]["price"]
usx_p = Decimal(pd["price"]) / Decimal(10 ** abs(int(pd["expo"])))

eusx_rate = get_eusx_exchange_rate()
eusx_p = eusx_rate * usx_p

sol_p = get_price({"symbol": "SOL", "pricing": {"method": "kraken", "kraken_pair": "SOLUSD"}}, w3)["price_usd"]

# --- Wallet SPL balances ---
resp = solana_rpc("getTokenAccountsByOwner", [
    wallet,
    {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
    {"encoding": "jsonParsed"},
])
bals = {}
for a in resp["result"]["value"]:
    i = a["account"]["data"]["parsed"]["info"]
    if int(i["tokenAmount"]["amount"]) > 0:
        bals[i["mint"]] = Decimal(i["tokenAmount"].get("uiAmountString", "0"))

time.sleep(0.3)
sol_bal = Decimal(solana_rpc("getBalance", [wallet])["result"]["value"]) / Decimal(10**9)

# --- Kamino ---
ob1 = get_kamino_obligation("D2rcayJTqmZvqaoViEyamQh2vw9T1KYwjbySQZSz6fsS")
uscc_amt = Decimal(ob1["deposits"][0]["deposited_amount"]) / Decimal(10**6)
usdc_debt = ob1["borrows"][0]["borrowed_amount"] / Decimal(10**6)

ob2 = get_kamino_obligation("HMMc5d9sMrGrAY18wE5yYTPpJNk72nrBrgqz5mtE3yrq")
usx_debt = ob2["borrows"][0]["borrowed_amount"] / Decimal(10**6)

vpu = value_pt_from_config("PT-USX-01JUN26", vdate, usx_p)
vpe = value_pt_from_config("PT-eUSX-01JUN26", vdate, eusx_p)

# --- Exponent ---
time.sleep(1)
lps = get_exponent_lp_positions(wallet)
time.sleep(1)
yts = get_exponent_yt_positions(wallet)

time.sleep(0.5)
mk1 = get_exponent_market("8QJRc12BDXHRLghZXFyPtYtAQeRwnZGKMJQa3G2NVQoC")
time.sleep(0.3)
ls1 = int(solana_rpc("getTokenSupply", [mk1["lp_mint"]])["result"]["value"]["amount"])
lb1 = next(l["lp_balance"] for l in lps if l["market"] == "8QJRc12BDXHRLghZXFyPtYtAQeRwnZGKMJQa3G2NVQoC")
d1 = decompose_exponent_lp(mk1, lb1, ls1)

time.sleep(0.5)
mk2 = get_exponent_market("rBbzpGk3PTX8mvQg95VWJ24EDgvxyDJYrEo9jtauvjP")
time.sleep(0.3)
ls2 = int(solana_rpc("getTokenSupply", [mk2["lp_mint"]])["result"]["value"]["amount"])
lb2 = next(l["lp_balance"] for l in lps if l["market"] == "rBbzpGk3PTX8mvQg95VWJ24EDgvxyDJYrEo9jtauvjP")
d2 = decompose_exponent_lp(mk2, lb2, ls2)

sy1 = Decimal(d1["user_sy"]) / Decimal(10**9)
pt1 = Decimal(d1["user_pt"]) / Decimal(10**9)
ptr1 = Decimal(str(d1["pt_price_ratio"]))

sy2 = Decimal(d2["user_sy"]) / Decimal(10**6)
pt2 = Decimal(d2["user_pt"]) / Decimal(10**6)
ptr2 = Decimal(str(d2["pt_price_ratio"]))

ytO = Decimal(next(y["yt_balance"] for y in yts if y["vault"] == "J2apQJvzq1yuhBoa1mVwAXr3P5oEzFaCVohq1GQMcW2c")) / Decimal(10**9)
ytE = Decimal(next(y["yt_balance"] for y in yts if y["vault"] == "7NviQEEiA5RSY4aL1wpqGE8CYAx2Lx7THHinsW1CWDXu")) / Decimal(10**6)
ytr1 = Decimal(1) - ptr1
ytr2 = Decimal(1) - ptr2

# --- Build table ---
rows = []

def add(proto, pos, tok, cat, amt, price, val, notes=""):
    rows.append((proto, pos, tok, cat, amt, price, val, notes))

# Kamino Superstate
add("Kamino", "Superstate (D)", "USCC", "A2", uscc_amt, uscc_p, uscc_amt * uscc_p, "collateral")
add("Kamino", "Superstate (D)", "USDC", "E", -usdc_debt, Decimal(1), -usdc_debt, "debt")

# Kamino Solstice
pt_usx_price = vpu["total_usd_value"] / vpu["total_pt_quantity"]
pt_eusx_price = vpe["total_usd_value"] / vpe["total_pt_quantity"]
add("Kamino", "Solstice (D)", "PT-USX (7 lots)", "B", vpu["total_pt_quantity"], pt_usx_price, vpu["total_usd_value"],
    "collat, APY %.1f%%" % (float(vpu["weighted_avg_apy"]) * 100))
add("Kamino", "Solstice (D)", "PT-eUSX (1 lot)", "B", vpe["total_pt_quantity"], pt_eusx_price, vpe["total_usd_value"],
    "collat, APY %.1f%%" % (float(vpe["weighted_avg_apy"]) * 100))
add("Kamino", "Solstice (D)", "USX", "E", -usx_debt, usx_p, -usx_debt * usx_p, "debt")

# Kamino farming
add("Kamino", "Farming (F)", "USDG", "E", Decimal(6035), Decimal(1), Decimal(6035), "unclaimed")

# Exponent ONyc LP
add("Exponent", "ONyc LP (C)", "ONyc (SY)", "A2", sy1, onyc_p, sy1 * onyc_p, "")
add("Exponent", "ONyc LP (C)", "PT-ONyc", "C", pt1, ptr1 * onyc_p, pt1 * ptr1 * onyc_p, "PT ratio=%.4f" % ptr1)

# Exponent eUSX LP
add("Exponent", "eUSX LP (C)", "eUSX (SY)", "A1", sy2, eusx_p, sy2 * eusx_p, "")
add("Exponent", "eUSX LP (C)", "PT-eUSX", "C", pt2, ptr2 * eusx_p, pt2 * ptr2 * eusx_p, "PT ratio=%.4f" % ptr2)

# Exponent YTs
add("Exponent", "YT (F)", "YT-ONyc", "F", ytO, ytr1 * onyc_p, ytO * ytr1 * onyc_p, "")
add("Exponent", "YT (F)", "YT-eUSX", "F", ytE, ytr2 * eusx_p, ytE * ytr2 * eusx_p, "")

# Wallet tokens
token_map = {
    "5Y8NV33Vv7WbnLfq3zBcKSdYPrk7g2KoiQoe7M2tcxp5": ("ONyc", "A2", onyc_p),
    "6FrrzDk5mQARGc1TDYoyVnSyRdds1t4PbtohCD6p3tgG": ("USX", "E", usx_p),
    "3ThdFZQKM6kRyVGLG48kaPg5TRMhYMKY1iCRa9xop1WC": ("eUSX", "A1", eusx_p),
}
for mint, bal in bals.items():
    if mint in token_map:
        sym, cat, price = token_map[mint]
        add("Wallet", "Token", sym, cat, bal, price, bal * price, "")

if sol_bal > 0:
    add("Wallet", "Token", "SOL", "F", sol_bal, sol_p, sol_bal * sol_p, "native")

# --- Print ---
SEP = "=" * 145
DASH = "-" * 145
print(SEP)
print(f"SOLANA WALLET POSITIONS: {wallet}")
print(f"Valuation: {vdate}")
print(SEP)
hdr = f"{'Protocol':<11} {'Position':<22} {'Token':<18} {'Cat':<4} {'Amount':>16} {'Price':>12} {'USD Value':>16} Notes"
print(hdr)
print(DASH)

gp = Decimal(0)
gn = Decimal(0)
for proto, pos, tok, cat, amt, price, val, notes in rows:
    print(f"{proto:<11} {pos:<22} {tok:<18} {cat:<4} {amt:>16,.2f} {price:>12.4f} {val:>16,.2f} {notes}")
    if val >= 0:
        gp += val
    else:
        gn += val

print(DASH)
print(f"{'':>90} {'Gross assets:':>16} {gp:>16,.2f}")
print(f"{'':>90} {'Gross debt:':>16} {gn:>16,.2f}")
print(f"{'':>90} {'NET TOTAL:':>16} {gp + gn:>16,.2f}")
