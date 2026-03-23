# config.py — Konfigurasi global bot arbitrase Polymarket

import os
from dotenv import load_dotenv

# Muat variabel dari file .env secara otomatis
load_dotenv()

# ─────────────────────────────────────────────
# API Endpoints
# ─────────────────────────────────────────────
CLOB_BASE_URL  = "https://clob.polymarket.com"
GAMMA_BASE_URL = "https://gamma-api.polymarket.com"

# ─────────────────────────────────────────────
# Arbitrase — Threshold & Strategi
# ─────────────────────────────────────────────
PROFIT_THRESHOLD  = float(os.getenv("PROFIT_THRESHOLD", "0.01"))
BET_SIZE_SHARES   = float(os.getenv("BET_SIZE_SHARES", "1.0"))
GAS_FEE_PER_TX    = float(os.getenv("GAS_FEE_PER_TX", "0.002"))

# ─────────────────────────────────────────────
# Paper Trading
# ─────────────────────────────────────────────
PAPER_INITIAL_BALANCE = 1000.0

# ─────────────────────────────────────────────
# Wallet (hanya dipakai di mode live)
# ─────────────────────────────────────────────
PRIVATE_KEY    = os.getenv("POLY_PRIVATE_KEY", "")
WALLET_ADDRESS = os.getenv("POLY_WALLET_ADDRESS", "")
CHAIN_ID       = 137

# ─────────────────────────────────────────────
# Monitoring
# ─────────────────────────────────────────────
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "10"))
