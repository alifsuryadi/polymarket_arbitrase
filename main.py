#!/usr/bin/env python3
# main.py — Entry point CLI untuk Polymarket Arbitrage Bot
#
# Cara pakai:
#   python main.py --condition_id 0x... --mode paper
#   python main.py --condition_id 0x... --mode live --confirm
#   python main.py --condition_id 0x... --mode scan   # scan sekali, tidak loop

import argparse
import logging
import sys
import time

from arbitrage import check_arbitrage
from paper_trade import PaperPortfolio, simulate_trade
from executor import execute_arbitrage
from config import POLL_INTERVAL_SECONDS, PROFIT_THRESHOLD

# ─────────────────────────────────────────────
# Logging setup
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


# ─────────────────────────────────────────────
# Banner
# ─────────────────────────────────────────────
BANNER = """
╔══════════════════════════════════════════════════╗
║     Polymarket Internal Arbitrage Bot v1.0       ║
║     Strategy: Buy All NO / Buy All YES           ║
╚══════════════════════════════════════════════════╝
"""


# ─────────────────────────────────────────────
# Core scan logic
# ─────────────────────────────────────────────

def run_scan(condition_id: str, mode: str, portfolio: PaperPortfolio | None) -> bool:
    """
    Jalankan satu siklus scan arbitrase.

    Args:
        condition_id : Market yang dipantau.
        mode         : "scan" | "paper" | "live"
        portfolio    : PaperPortfolio (dipakai jika mode=paper).

    Returns:
        True jika peluang ditemukan.
    """
    try:
        no_result, yes_result = check_arbitrage(condition_id)
    except Exception as exc:
        logger.error("Gagal mengambil data market: %s", exc)
        return False

    opportunity_found = False

    for result in (no_result, yes_result):
        print(result)  # Cetak analisis lengkap

        if result.is_opportunity:
            opportunity_found = True
            print(f"\n  >>> OPPORTUNITY FOUND! Strategi: Buy All {result.strategy}")
            print(f"  >>> Net Profit: ${result.net_profit:.4f}  ROI: {result.roi_pct:.2f}%\n")

            if mode == "paper" and portfolio is not None:
                simulate_trade(result, portfolio)

            elif mode == "live":
                # Eksekusi nyata — dry_run=False
                execute_arbitrage(result, dry_run=False)

            elif mode == "scan":
                # Hanya scan, tampilkan dry run preview
                execute_arbitrage(result, dry_run=True)

    return opportunity_found


# ─────────────────────────────────────────────
# Loop monitoring
# ─────────────────────────────────────────────

def run_monitor(condition_id: str, mode: str, interval: int) -> None:
    """Loop tak terbatas yang scan market setiap N detik."""
    portfolio = PaperPortfolio() if mode == "paper" else None
    scan_count = 0

    try:
        while True:
            scan_count += 1
            logger.info("Scan #%d | mode=%s | interval=%ds", scan_count, mode, interval)
            found = run_scan(condition_id, mode, portfolio)

            if not found:
                logger.info("Tidak ada peluang. Menunggu %d detik...", interval)

            if portfolio is not None and scan_count % 5 == 0:
                # Cetak summary portfolio setiap 5 scan
                print(portfolio.summary())

            time.sleep(interval)

    except KeyboardInterrupt:
        print("\n[Bot dihentikan oleh user]")
        if portfolio is not None:
            print(portfolio.summary())
        sys.exit(0)


# ─────────────────────────────────────────────
# CLI argument parser
# ─────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Polymarket Internal Arbitrage Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Contoh:
  # Scan sekali, lihat apakah ada peluang
  python main.py --condition_id 0xABC123 --mode scan

  # Jalankan paper trading (simulasi) secara terus-menerus
  python main.py --condition_id 0xABC123 --mode paper

  # Live trading (butuh env var POLY_PRIVATE_KEY)
  export POLY_PRIVATE_KEY="0x..."
  python main.py --condition_id 0xABC123 --mode live --confirm
        """,
    )
    parser.add_argument(
        "--condition_id",
        required=True,
        help="Polymarket condition ID (0x...)",
    )
    parser.add_argument(
        "--mode",
        choices=["scan", "paper", "live"],
        default="scan",
        help="scan=satu kali cek | paper=simulasi loop | live=eksekusi nyata (default: scan)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=POLL_INTERVAL_SECONDS,
        help=f"Interval polling dalam detik (default: {POLL_INTERVAL_SECONDS})",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Diperlukan untuk mode live sebagai konfirmasi eksplisit.",
    )
    return parser.parse_args()


# ─────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────

def main() -> None:
    print(BANNER)
    args = parse_args()

    # Validasi mode live
    if args.mode == "live":
        if not args.confirm:
            print("ERROR: Mode live membutuhkan flag --confirm untuk mencegah eksekusi tidak sengaja.")
            print("       Jalankan: python main.py --condition_id ... --mode live --confirm")
            sys.exit(1)
        print("=" * 60)
        print("  PERHATIAN: MODE LIVE AKTIF")
        print("  Bot akan mengeksekusi order nyata menggunakan private key Anda!")
        print(f"  Profit threshold: ${PROFIT_THRESHOLD}")
        print("  Tekan Ctrl+C dalam 5 detik untuk membatalkan...")
        print("=" * 60)
        time.sleep(5)

    logger.info("Memulai bot | condition_id=%s | mode=%s", args.condition_id, args.mode)

    if args.mode == "scan":
        # Satu kali scan saja
        portfolio = None
        run_scan(args.condition_id, args.mode, portfolio)
    else:
        # Loop monitoring (paper atau live)
        run_monitor(args.condition_id, args.mode, args.interval)


if __name__ == "__main__":
    main()
