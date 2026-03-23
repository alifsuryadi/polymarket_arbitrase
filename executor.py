# executor.py — Eksekusi order nyata via py-clob-client (Polymarket SDK resmi)
#
# PERINGATAN:
#   - Modul ini menggunakan Private Key wallet Anda.
#   - SELALU uji dengan paper_trade.py terlebih dahulu.
#   - Pastikan POLY_PRIVATE_KEY & POLY_WALLET_ADDRESS sudah diset sebagai env var.
#   - Risiko: partial fill, slippage, dana hilang jika order tidak semua tereksekusi.

from __future__ import annotations

import logging
import time
from typing import Optional

from arbitrage import ArbitrageResult, OutcomePrice
from config import PRIVATE_KEY, CHAIN_ID, BET_SIZE_SHARES

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Coba impor py-clob-client (opsional)
# ─────────────────────────────────────────────
try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import OrderArgs, OrderType
    from py_clob_client.constants import BUY
    _CLOB_AVAILABLE = True
except ImportError:
    _CLOB_AVAILABLE = False
    logger.warning(
        "py-clob-client tidak terinstal. "
        "Jalankan: pip install py-clob-client  untuk mengaktifkan live trading."
    )


# ─────────────────────────────────────────────
# Inisialisasi client
# ─────────────────────────────────────────────

def _get_client() -> "ClobClient":
    if not _CLOB_AVAILABLE:
        raise RuntimeError("py-clob-client tidak terinstal. Jalankan: pip install py-clob-client")
    if not PRIVATE_KEY:
        raise RuntimeError(
            "POLY_PRIVATE_KEY belum diset. "
            "Jalankan: export POLY_PRIVATE_KEY='0x...' di terminal."
        )
    client = ClobClient(
        host="https://clob.polymarket.com",
        key=PRIVATE_KEY,
        chain_id=CHAIN_ID,
    )
    return client


# ─────────────────────────────────────────────
# Fungsi eksekusi
# ─────────────────────────────────────────────

def execute_arbitrage(result: ArbitrageResult, dry_run: bool = True) -> list[dict]:
    """
    Eksekusi semua order untuk strategi arbitrase yang ditemukan.

    Args:
        result   : ArbitrageResult yang sudah terdeteksi sebagai peluang.
        dry_run  : Jika True, cetak order tapi TIDAK eksekusi (default: True).

    Returns:
        List of order responses (kosong jika dry_run=True).

    PERINGATAN:
        Set dry_run=False HANYA jika Anda yakin dan sudah test dengan paper trading.
        Jika salah satu order gagal (partial fill), strategi bisa RUGI.
    """
    if not result.is_opportunity:
        logger.info("Tidak ada peluang — tidak ada yang dieksekusi.")
        return []

    if dry_run:
        _print_dry_run(result)
        return []

    client = _get_client()
    responses = []
    failed_orders = []

    orders_to_place = _build_orders(result)
    logger.info("Memulai eksekusi %d order untuk strategi %s...", len(orders_to_place), result.strategy)

    for i, (token_id, price, label) in enumerate(orders_to_place):
        try:
            order_args = OrderArgs(
                token_id=token_id,
                price=round(price, 4),
                size=BET_SIZE_SHARES,
                side=BUY,
                order_type=OrderType.GTC,   # Good Till Cancelled
            )
            signed_order = client.create_order(order_args)
            resp = client.post_order(signed_order)
            responses.append(resp)
            logger.info("[%d/%d] Order OK: %s @ $%.4f", i+1, len(orders_to_place), label, price)

            # Jeda kecil antar order untuk menghindari rate-limit
            time.sleep(0.3)

        except Exception as exc:
            logger.error("[%d/%d] Order GAGAL untuk '%s': %s", i+1, len(orders_to_place), label, exc)
            failed_orders.append(label)

    if failed_orders:
        logger.critical(
            "PERINGATAN KRITIS: %d order gagal dieksekusi: %s\n"
            "Strategi arbitrase mungkin TIDAK SEMPURNA. Periksa posisi Anda segera!",
            len(failed_orders),
            failed_orders,
        )
    else:
        logger.info("Semua %d order berhasil dieksekusi!", len(orders_to_place))

    return responses


def _build_orders(result: ArbitrageResult) -> list[tuple[str, float, str]]:
    """Bangun list (token_id, price, label) berdasarkan strategi."""
    orders = []
    for op in result.outcome_prices:
        if result.strategy == "NO":
            token_id = op.outcome.no_token_id
            price    = op.no_ask
        else:
            token_id = op.outcome.yes_token_id
            price    = op.yes_ask

        if price is None:
            logger.warning("Harga kosong untuk '%s', dilewati.", op.outcome.outcome_label)
            continue

        orders.append((token_id, price, op.outcome.outcome_label))
    return orders


def _print_dry_run(result: ArbitrageResult) -> None:
    print(f"\n{'='*60}")
    print(f"  [DRY RUN] Preview Order — Strategi Buy All {result.strategy}")
    print(f"  Market: {result.market.question}")
    print(f"  Total Cost    : ${result.total_cost:.4f}")
    print(f"  Est. Net Profit: ${result.net_profit:.4f} ({result.roi_pct:.2f}% ROI)")
    print(f"{'─'*60}")
    for token_id, price, label in _build_orders(result):
        print(f"  BUY {BET_SIZE_SHARES} share(s) @ ${price:.4f}  |  {label}")
        print(f"       token_id: {token_id[:20]}...")
    print(f"{'='*60}")
    print("  [DRY RUN] Tidak ada order nyata yang dikirim.")
    print(f"  Untuk eksekusi nyata: execute_arbitrage(result, dry_run=False)")
    print(f"{'='*60}\n")
