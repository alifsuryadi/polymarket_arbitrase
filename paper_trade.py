# paper_trade.py — Simulasi Paper Trading (tanpa uang nyata)

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from arbitrage import ArbitrageResult
from config import PAPER_INITIAL_BALANCE, BET_SIZE_SHARES

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────

@dataclass
class SimulatedOrder:
    timestamp: str
    strategy: str           # "NO" atau "YES"
    outcome_label: str
    token_type: str         # "NO" atau "YES"
    price: float
    shares: float
    cost: float


@dataclass
class TradeRecord:
    timestamp: str
    market_question: str
    strategy: str
    orders: list[SimulatedOrder]
    total_cost: float
    estimated_payout: float
    estimated_net_profit: float
    roi_pct: float


@dataclass
class PaperPortfolio:
    balance: float = PAPER_INITIAL_BALANCE
    trades: list[TradeRecord] = field(default_factory=list)
    total_profit: float = 0.0

    def summary(self) -> str:
        lines = [
            "\n" + "=" * 60,
            "  PAPER TRADING PORTFOLIO SUMMARY",
            "=" * 60,
            f"  Saldo Awal    : ${PAPER_INITIAL_BALANCE:.2f}",
            f"  Saldo Saat Ini: ${self.balance:.2f}",
            f"  Total Profit  : ${self.total_profit:.4f}",
            f"  Jumlah Trade  : {len(self.trades)}",
            "=" * 60,
        ]
        if self.trades:
            lines.append("  Riwayat Trade:")
            for i, t in enumerate(self.trades, 1):
                status = "PROFIT" if t.estimated_net_profit > 0 else "LOSS"
                lines.append(
                    f"  [{i}] [{t.timestamp}] {t.strategy} | "
                    f"Cost=${t.total_cost:.4f} | "
                    f"Pay=${t.estimated_payout:.4f} | "
                    f"Net=${t.estimated_net_profit:.4f} ({status})"
                )
            lines.append("=" * 60)
        return "\n".join(lines)


# ─────────────────────────────────────────────
# Fungsi simulasi
# ─────────────────────────────────────────────

def simulate_trade(result: ArbitrageResult, portfolio: PaperPortfolio) -> TradeRecord | None:
    """
    Simulasikan satu trade berdasarkan ArbitrageResult.
    Mengurangi saldo virtual dan mencatat trade ke portfolio.

    Returns:
        TradeRecord jika simulasi berhasil, None jika saldo tidak cukup.
    """
    if not result.is_opportunity:
        logger.info("[Paper] Tidak ada peluang untuk strategi %s, tidak ada trade.", result.strategy)
        return None

    if result.total_cost > portfolio.balance:
        logger.warning(
            "[Paper] Saldo tidak cukup! Dibutuhkan $%.4f, tersedia $%.4f",
            result.total_cost,
            portfolio.balance,
        )
        return None

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    orders: list[SimulatedOrder] = []

    for op in result.outcome_prices:
        if result.strategy == "NO":
            price = op.no_ask
            token_type = "NO"
        else:
            price = op.yes_ask
            token_type = "YES"

        if price is None:
            logger.warning("[Paper] Harga %s untuk '%s' tidak tersedia.", token_type, op.outcome.outcome_label)
            continue

        cost = price * BET_SIZE_SHARES
        orders.append(SimulatedOrder(
            timestamp=timestamp,
            strategy=result.strategy,
            outcome_label=op.outcome.outcome_label,
            token_type=token_type,
            price=price,
            shares=BET_SIZE_SHARES,
            cost=cost,
        ))

    if not orders:
        return None

    trade = TradeRecord(
        timestamp=timestamp,
        market_question=result.market.question,
        strategy=result.strategy,
        orders=orders,
        total_cost=result.total_cost,
        estimated_payout=result.guaranteed_payout,
        estimated_net_profit=result.net_profit,
        roi_pct=result.roi_pct,
    )

    # Update portfolio
    portfolio.balance -= result.total_cost
    portfolio.total_profit += result.net_profit
    portfolio.trades.append(trade)

    _print_trade_confirmation(trade)
    return trade


def _print_trade_confirmation(trade: TradeRecord) -> None:
    print(f"\n{'─'*60}")
    print(f"  [PAPER TRADE EXECUTED] {trade.timestamp}")
    print(f"  Market  : {trade.market_question}")
    print(f"  Strategi: Buy All {trade.strategy}")
    print(f"  Orders  : {len(trade.orders)} kontrak")
    print(f"  Cost    : ${trade.total_cost:.4f}")
    print(f"  Payout  : ${trade.estimated_payout:.4f}")
    print(f"  Net P&L : ${trade.estimated_net_profit:.4f} ({trade.roi_pct:.2f}% ROI)")
    print(f"{'─'*60}\n")
    for order in trade.orders:
        print(f"    BUY {order.shares} {order.token_type} @ ${order.price:.4f}  ({order.outcome_label})")
    print()
