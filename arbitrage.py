# arbitrage.py — Deteksi peluang arbitrase & kalkulasi ROI

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from api_client import (
    MarketInfo,
    OutcomeInfo,
    Orderbook,
    get_market_info,
    get_orderbook,
)
from config import PROFIT_THRESHOLD, BET_SIZE_SHARES, GAS_FEE_PER_TX

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Data classes hasil analisis
# ─────────────────────────────────────────────

@dataclass
class OutcomePrice:
    outcome: OutcomeInfo
    yes_ask: Optional[float]    # Best ask untuk YES token
    no_ask: Optional[float]     # Best ask untuk NO token
    yes_orderbook: Optional[Orderbook] = None
    no_orderbook: Optional[Orderbook] = None


@dataclass
class ArbitrageResult:
    strategy: str               # "NO" atau "YES"
    market: MarketInfo
    outcome_prices: list[OutcomePrice]
    n: int                      # Jumlah outcome
    total_cost: float           # Total biaya beli semua kontrak
    guaranteed_payout: float    # Payout pasti jika semua berhasil
    gross_profit: float         # Sebelum gas fee
    total_gas_fee: float        # Estimasi total gas fee
    net_profit: float           # Setelah gas fee
    roi_pct: float              # Return on Investment (%)
    is_opportunity: bool        # True jika profit > threshold

    def __str__(self) -> str:
        lines = [
            f"\n{'='*60}",
            f"  Strategi      : Buy All {self.strategy}",
            f"  Market        : {self.market.question}",
            f"  Jumlah Outcome: {self.n}",
            f"  Total Cost    : ${self.total_cost:.4f}",
            f"  Guaranteed Pay: ${self.guaranteed_payout:.4f}",
            f"  Gas Fee       : ${self.total_gas_fee:.4f}",
            f"  Gross Profit  : ${self.gross_profit:.4f}",
            f"  Net Profit    : ${self.net_profit:.4f}",
            f"  ROI           : {self.roi_pct:.2f}%",
            f"{'='*60}",
        ]
        if self.is_opportunity:
            lines.insert(1, "  *** OPPORTUNITY FOUND! ***")
        else:
            lines.insert(1, "  (Tidak ada peluang saat ini)")

        lines.append("  Rincian per Outcome:")
        for op in self.outcome_prices:
            ask_val = op.no_ask if self.strategy == "NO" else op.yes_ask
            ask_str = f"${ask_val:.4f}" if ask_val is not None else "N/A (kosong)"
            lines.append(f"    - {op.outcome.outcome_label:<30} ask={ask_str}")
        lines.append("=" * 60)
        return "\n".join(lines)


# ─────────────────────────────────────────────
# Fungsi utama
# ─────────────────────────────────────────────

def _fetch_all_prices(market: MarketInfo) -> list[OutcomePrice]:
    """Ambil orderbook YES + NO untuk setiap outcome secara paralel-semu."""
    result = []
    for outcome in market.outcomes:
        try:
            yes_ob = get_orderbook(outcome.yes_token_id)
            no_ob  = get_orderbook(outcome.no_token_id)
            result.append(OutcomePrice(
                outcome=outcome,
                yes_ask=yes_ob.best_ask,
                no_ask=no_ob.best_ask,
                yes_orderbook=yes_ob,
                no_orderbook=no_ob,
            ))
        except Exception as exc:
            logger.warning("Gagal ambil harga untuk '%s': %s", outcome.outcome_label, exc)
            result.append(OutcomePrice(
                outcome=outcome,
                yes_ask=None,
                no_ask=None,
            ))
    return result


def _analyze_no_strategy(
    market: MarketInfo,
    outcome_prices: list[OutcomePrice],
) -> ArbitrageResult:
    """
    Strategi 'Buy All No':
      - Beli NO token di semua n outcome.
      - Payout = (n - 1) × BET_SIZE karena tepat satu outcome menang,
        sehingga (n-1) NO token berhasil (resolve = $1 masing-masing).
      - Profit = (n-1) - total_cost_no
    """
    n = len(outcome_prices)
    valid = [op for op in outcome_prices if op.no_ask is not None]
    n_covered = len(valid)

    if n_covered < n:
        logger.warning(
            "%d/%d outcome tidak punya harga NO — payout dihitung dari %d yang bisa dibeli.",
            n - n_covered, n, n_covered,
        )

    # Payout dihitung dari outcome yang BENAR-BENAR bisa dibeli.
    # Worst case: 1 dari n_covered menang → (n_covered - 1) NO token bayar $1.
    # (Jika outcome yang tidak tercover menang, payout justru lebih tinggi = n_covered × $1)
    total_cost = sum(op.no_ask * BET_SIZE_SHARES for op in valid)  # type: ignore[operator]
    guaranteed_payout = (n_covered - 1) * BET_SIZE_SHARES
    gross_profit = guaranteed_payout - total_cost
    total_gas = GAS_FEE_PER_TX * n_covered
    net_profit = gross_profit - total_gas
    roi = (net_profit / total_cost * 100) if total_cost > 0 else 0.0

    return ArbitrageResult(
        strategy="NO",
        market=market,
        outcome_prices=outcome_prices,
        n=n,
        total_cost=total_cost,
        guaranteed_payout=guaranteed_payout,
        gross_profit=gross_profit,
        total_gas_fee=total_gas,
        net_profit=net_profit,
        roi_pct=roi,
        is_opportunity=(net_profit > PROFIT_THRESHOLD),
    )


def _analyze_yes_strategy(
    market: MarketInfo,
    outcome_prices: list[OutcomePrice],
) -> ArbitrageResult:
    """
    Strategi 'Buy All Yes':
      - Beli YES token di semua n outcome yang mutually exclusive.
      - Tepat satu outcome menang → payout = $1 × BET_SIZE.
      - Profit = 1 - total_cost_yes
    """
    n = len(outcome_prices)
    valid = [op for op in outcome_prices if op.yes_ask is not None]
    n_covered = len(valid)

    # YES strategy: tepat 1 menang → payout $1 HANYA jika kamu hold YES token yang menang.
    # Jika ada outcome tanpa harga (tidak dibeli), dan outcome itu menang → payout $0.
    # Jadi guaranteed_payout = $1 hanya jika SEMUA outcome tercover.
    if n_covered < n:
        logger.warning(
            "%d/%d outcome tidak punya harga YES — strategi YES tidak lengkap.",
            n - n_covered, n,
        )
        guaranteed_payout = 0.0  # tidak bisa guarantee profit jika ada yang missing
    else:
        guaranteed_payout = 1.0 * BET_SIZE_SHARES

    total_cost = sum(op.yes_ask * BET_SIZE_SHARES for op in valid)  # type: ignore[operator]
    gross_profit = guaranteed_payout - total_cost
    total_gas = GAS_FEE_PER_TX * n_covered
    net_profit = gross_profit - total_gas
    roi = (net_profit / total_cost * 100) if total_cost > 0 else 0.0

    return ArbitrageResult(
        strategy="YES",
        market=market,
        outcome_prices=outcome_prices,
        n=n,
        total_cost=total_cost,
        guaranteed_payout=guaranteed_payout,
        gross_profit=gross_profit,
        total_gas_fee=total_gas,
        net_profit=net_profit,
        roi_pct=roi,
        is_opportunity=(net_profit > PROFIT_THRESHOLD),
    )


def check_arbitrage(
    condition_id: str,
    market_info: Optional[MarketInfo] = None,
) -> tuple[ArbitrageResult, ArbitrageResult]:
    """
    Fungsi utama: periksa peluang arbitrase (NO & YES) untuk satu market.

    Args:
        condition_id:  Polymarket condition ID (0x...).
        market_info:   Jika sudah tersedia (dari UI), langsung dipakai — skip re-fetch.

    Returns:
        Tuple (no_result, yes_result) — dua objek ArbitrageResult.
    """
    if market_info is not None:
        market = market_info
    else:
        logger.info("Mengambil data market: %s", condition_id)
        market = get_market_info(condition_id)

    if not market.outcomes:
        raise ValueError("Market tidak memiliki outcome yang valid.")

    logger.info("Mengambil harga orderbook untuk %d outcome...", len(market.outcomes))
    outcome_prices = _fetch_all_prices(market)

    no_result  = _analyze_no_strategy(market, outcome_prices)
    yes_result = _analyze_yes_strategy(market, outcome_prices)

    return no_result, yes_result
