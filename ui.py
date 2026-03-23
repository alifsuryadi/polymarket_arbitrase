#!/usr/bin/env python3
# ui.py — Streamlit Web UI (Polymarket-style)
# Jalankan: streamlit run ui.py

import time
import logging
import streamlit as st
import pandas as pd

from arbitrage import check_arbitrage
from api_client import fetch_active_markets, group_markets_by_event, build_market_info, MarketInfo
from paper_trade import PaperPortfolio, simulate_trade
from config import POLL_INTERVAL_SECONDS, PROFIT_THRESHOLD, BET_SIZE_SHARES

logging.basicConfig(level=logging.WARNING)

# ─── Page config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Polymarket Arb Bot",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Polymarket-style CSS ─────────────────────────────────────────────────────
st.markdown("""
<style>
html,body,[data-testid="stAppViewContainer"]{background:#0d0e1a !important;color:#e2e4f0 !important}
[data-testid="stSidebar"]{background:#11121f !important;border-right:1px solid #252640}
[data-testid="stSidebar"] *{color:#e2e4f0 !important}
.main-header{background:linear-gradient(90deg,#6d28d9,#4f46e5);padding:18px 24px;border-radius:12px;margin-bottom:20px}
.main-header h1{color:#fff !important;margin:0;font-size:1.6rem}
.main-header p{color:rgba(255,255,255,.75);margin:4px 0 0;font-size:.9rem}
.mcard{background:#161728;border:1px solid #252640;border-radius:12px;padding:16px 20px;margin-bottom:16px}
.mcard h3{margin:0 0 6px;color:#fff;font-size:1.05rem}
.mcard .meta{color:#6b7280;font-size:.8rem}
.mcard a{color:#818cf8;text-decoration:none}
.mcard a:hover{text-decoration:underline}
.opp{background:linear-gradient(90deg,rgba(109,40,217,.2),rgba(79,70,229,.15));border:1px solid #6d28d9;border-radius:10px;padding:14px 20px;margin-bottom:16px;color:#c4b5fd}
.opp b{color:#a78bfa}
.nopp{background:#161728;border:1px solid #252640;border-radius:10px;padding:12px 20px;margin-bottom:16px;color:#6b7280;font-size:.9rem}
.warn{background:rgba(239,68,68,.08);border:1px solid rgba(239,68,68,.3);border-radius:10px;padding:12px 20px;margin-bottom:16px;color:#fca5a5;font-size:.88rem}
.bg-green{background:rgba(34,197,94,.15);color:#4ade80;border:1px solid rgba(34,197,94,.3);border-radius:6px;padding:3px 10px;font-size:.8rem;font-weight:600}
.bg-gray{background:rgba(107,114,128,.15);color:#9ca3af;border:1px solid rgba(107,114,128,.2);border-radius:6px;padding:3px 10px;font-size:.8rem}
[data-testid="metric-container"]{background:#1a1b2e;border:1px solid #252640;border-radius:10px;padding:14px !important}
[data-testid="stMetricValue"]{color:#e2e4f0 !important}
[data-testid="stMetricLabel"]{color:#6b7280 !important}
[data-baseweb="tab-list"]{background:#161728 !important;border-radius:8px;padding:4px}
[data-baseweb="tab"]{color:#9ca3af !important}
[aria-selected="true"][data-baseweb="tab"]{background:#6d28d9 !important;border-radius:6px;color:#fff !important}
.stButton>button[kind="primary"]{background:linear-gradient(90deg,#6d28d9,#4f46e5) !important;border:none !important;color:#fff !important;border-radius:8px !important;font-weight:600}
.stButton>button:not([kind="primary"]){background:#1e2035 !important;border:1px solid #252640 !important;color:#e2e4f0 !important;border-radius:8px !important}
[data-testid="stExpander"]{background:#1a1b2e !important;border:1px solid #252640 !important;border-radius:8px !important}
::-webkit-scrollbar{width:6px;height:6px}
::-webkit-scrollbar-track{background:#0d0e1a}
::-webkit-scrollbar-thumb{background:#252640;border-radius:3px}
</style>
""", unsafe_allow_html=True)

# ─── Session state ────────────────────────────────────────────────────────────
for k, v in [
    ("portfolio",         PaperPortfolio()),
    ("scan_history",      []),
    ("last_condition_id", ""),
    ("current_result",    None),
    ("event_title",       ""),
    ("event_slug",        ""),
]:
    if k not in st.session_state:
        st.session_state[k] = v


# ─── Data fetch ───────────────────────────────────────────────────────────────
@st.cache_data(ttl=60, show_spinner=False)
def _cached_markets(limit: int) -> list[dict]:
    """Fetch market aktif terbaru — di-cache 60 detik."""
    return fetch_active_markets(query="", limit=limit)


@st.cache_data(ttl=60, show_spinner=False)
def _search_markets(query: str, limit: int) -> list[dict]:
    """Fetch dengan server-side search — di-cache per query."""
    return fetch_active_markets(query=query, limit=limit)


def get_grouped_markets(query: str) -> dict[str, dict]:
    """
    Grouping + search.
    Jika ada query: gabungkan hasil server-search (limit 500) + top-200 umum,
    lalu filter client-side. Ini memastikan market populer (trump, dll) tetap
    muncul meski server-search API tidak mengembalikan semua sub-market.
    """
    if query.strip():
        search_res = _search_markets(query.strip(), 500)
        general    = _cached_markets(200)
        # Merge — server search duluan, tambahkan dari general yang belum ada
        seen   = {m.get("conditionId") for m in search_res if m.get("conditionId")}
        merged = search_res + [m for m in general if m.get("conditionId") not in seen]
        return group_markets_by_event(merged, query=query)
    else:
        return group_markets_by_event(_cached_markets(200))


def polymarket_url(slug: str) -> str:
    return f"https://polymarket.com/event/{slug}" if slug else "https://polymarket.com"


# ─── Render helpers ───────────────────────────────────────────────────────────
def render_result_card(result) -> None:
    badge = (
        '<span class="bg-green">✅ OPPORTUNITY</span>'
        if result.is_opportunity else
        '<span class="bg-gray">Tidak ada peluang</span>'
    )
    st.markdown(
        f'<div style="display:flex;justify-content:space-between;align-items:center;'
        f'background:#161728;border:1px solid {"#6d28d9" if result.is_opportunity else "#252640"};'
        f'border-radius:10px;padding:14px 18px;margin-bottom:12px">'
        f'<b style="color:#e2e4f0">Buy All {result.strategy}</b>{badge}</div>',
        unsafe_allow_html=True,
    )

    valid = [op for op in result.outcome_prices
             if (op.no_ask if result.strategy == "NO" else op.yes_ask) is not None]

    if not valid:
        st.markdown("""
<div class="warn">
  ⚠️ <b>Tidak ada harga aktif untuk strategi ini.</b><br>
  Coba: pilih event lain yang <b>belum berakhir</b>, atau cari periode yang lebih baru
  (contoh: "elon musk march 31").
</div>
""", unsafe_allow_html=True)
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Modal",        f"${result.total_cost:.2f}")
    c2.metric("Guaranteed Payout",  f"${result.guaranteed_payout:.2f}")
    c3.metric("Net Profit",         f"${result.net_profit:.2f}",
              delta=f"{result.roi_pct:.2f}% ROI",
              delta_color="normal")   # normal: negatif = merah, positif = hijau
    c4.metric("Gas Fee",            f"${result.total_gas_fee:.2f}")

    # ── Tabel per outcome ──
    payout_per_share = BET_SIZE_SHARES  # $1.00 per share jika NO/YES menang
    rows = []
    for op in result.outcome_prices:
        ask   = op.no_ask if result.strategy == "NO" else op.yes_ask
        modal = ask * BET_SIZE_SHARES if ask else None
        laba  = (payout_per_share - modal) if modal is not None else None
        rows.append({
            "Kategori / Outcome": op.outcome.outcome_label,
            "Modal":              f"${modal:.2f}" if modal is not None else "—",
            "Terima (gross)":     f"${payout_per_share:.2f}" if modal is not None else "—",
            "Laba bersih leg":    (f"+${laba:.2f}" if laba >= 0 else f"-${abs(laba):.2f}") if laba is not None else "—",
            "Status":             "✅ Tersedia" if ask else "❌ Kosong",
        })
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    with st.expander("📐 Detail Formula"):
        if result.strategy == "NO":
            gp = result.total_gas_fee / result.n if result.n else 0
            st.markdown(f"""
`Profit = (n-1) - Σ No_ask`

| | |
|---|---|
| Jumlah outcome (n) | **{result.n}** |
| Payout `(n-1)×$1` | **${result.guaranteed_payout:.2f}** |
| Total Cost | **${result.total_cost:.2f}** |
| Gas Fee ({result.n}×${gp:.3f}) | **${result.total_gas_fee:.2f}** |
| **Net Profit** | **${result.net_profit:.2f}** |
""")
        else:
            st.markdown(f"""
`Profit = 1.00 - Σ Yes_ask`

| | |
|---|---|
| Jumlah outcome (n) | **{result.n}** |
| Payout | **$1.00** |
| Total Cost | **${result.total_cost:.2f}** |
| Gas Fee | **${result.total_gas_fee:.2f}** |
| **Net Profit** | **${result.net_profit:.2f}** |
""")


def render_portfolio(portfolio: PaperPortfolio) -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Saldo Awal",     "$1000.00")
    c2.metric("Saldo Saat Ini", f"${portfolio.balance:.2f}")
    pct = portfolio.total_profit / 1000 * 100
    c3.metric("Total Profit", f"${portfolio.total_profit:.2f}",
              delta=f"{pct:.2f}%",
              delta_color="normal" if portfolio.total_profit >= 0 else "inverse")
    c4.metric("Jumlah Trade", str(len(portfolio.trades)))
    if portfolio.trades:
        rows = [{
            "Waktu":    t.timestamp,
            "Market":   t.market_question[:50] + "…" if len(t.market_question) > 50 else t.market_question,
            "Strategi": f"Buy All {t.strategy}",
            "Cost":     f"${t.total_cost:.2f}",
            "Payout":   f"${t.estimated_payout:.2f}",
            "Net P&L":  f"${t.estimated_net_profit:.2f}",
            "ROI":      f"{t.roi_pct:.2f}%",
            "Status":   "🟢 PROFIT" if t.estimated_net_profit > 0 else "🔴 LOSS",
        } for t in portfolio.trades]
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    else:
        st.caption("Belum ada trade tersimulasi.")


# ─── SIDEBAR ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ Pengaturan")
    st.divider()

    st.markdown("### 🎯 Target Market")
    input_mode = st.radio("Cara input:", ["Cari dari Polymarket", "Manual (Condition ID)"], index=0)

    condition_id = ""
    market_info_override: MarketInfo | None = None

    if input_mode == "Manual (Condition ID)":
        condition_id = st.text_input("Condition ID", placeholder="0x1234abcd...")

    else:
        # Search box — langsung filter client-side, tanpa loading ulang dari API
        search_query = st.text_input(
            "🔍 Cari event",
            placeholder="elon musk, bitcoin, trump...",
            key="search_input",
        )

        with st.spinner("Memuat data..."):
            grouped = get_grouped_markets(search_query)

        if grouped:
            # Sort berdasarkan volume24h tertinggi
            sorted_groups = sorted(grouped.items(), key=lambda x: x[1]["volume24h"], reverse=True)

            options_map = {}
            for ev_id, ev_data in sorted_groups:
                title  = ev_data["title"][:60]
                vol    = ev_data["volume24h"]
                n_out  = len(ev_data["markets"])
                vol_s  = f"${vol/1000:.0f}k" if vol >= 1000 else f"${vol:.0f}"
                # Tampilkan tanggal berakhir jika ada
                end_s  = ""
                end_raw = ev_data.get("end_date", "")
                if end_raw:
                    try:
                        from datetime import datetime, timezone
                        ed = datetime.fromisoformat(end_raw.replace("Z", "+00:00"))
                        end_s = f" · ends {ed.strftime('%b %d')}"
                    except Exception:
                        pass
                label  = f"{title}  [{n_out} outcomes · {vol_s}/24h{end_s}]"
                options_map[label] = ev_data

            selected_label = st.selectbox(
                f"Event ({len(options_map)} tersedia):",
                list(options_map.keys()),
                key="event_select",
            )
            selected_group = options_map[selected_label]

            # Condition ID = conditionId dari market pertama dalam grup ini
            first_market = selected_group["markets"][0]
            condition_id = first_market.get("conditionId", "")

            # Simpan info event untuk ditampilkan di main
            ev_title_local = selected_group["title"]
            ev_slug_local  = selected_group["slug"]

            if condition_id:
                n_out = len(selected_group["markets"])
                st.success(f"✅ {n_out} outcome ditemukan")
                st.code(condition_id[:42], language=None)
                # Build MarketInfo langsung dari data yang sudah kita punya
                # → hindari re-fetch sibling yang bisa salah market
                market_info_override = build_market_info(
                    markets=selected_group["markets"],
                    event_title=ev_title_local,
                    event_slug=ev_slug_local,
                    condition_id=condition_id,
                )
        else:
            if search_query:
                st.warning(f'Tidak ada hasil untuk "{search_query}"')
            else:
                st.info("Memuat daftar market...")
            ev_title_local = ""
            ev_slug_local  = ""

    # Saat market berubah → clear state lama
    if condition_id != st.session_state.last_condition_id:
        st.session_state.scan_history      = []
        st.session_state.current_result    = None
        st.session_state.last_condition_id = condition_id
        # Simpan event title & slug ke session state
        if input_mode != "Manual (Condition ID)":
            st.session_state.event_title = ev_title_local
            st.session_state.event_slug  = ev_slug_local
        else:
            st.session_state.event_title = ""
            st.session_state.event_slug  = ""

    st.divider()
    st.markdown("### 🔧 Mode")
    mode = st.selectbox("Mode operasi:", ["scan", "paper"],
                        format_func=lambda x: {"scan": "📡 Scan", "paper": "📝 Paper Trade"}[x])

    st.markdown("### 🔄 Auto Refresh")
    auto_refresh = st.toggle("Aktifkan", value=False)
    interval     = st.slider("Interval (detik)", 5, 60, POLL_INTERVAL_SECONDS, disabled=not auto_refresh)

    st.divider()
    scan_btn = st.button("🔍 Scan Sekarang", type="primary", use_container_width=True)
    if mode == "paper":
        if st.button("🗑️ Reset Portfolio", use_container_width=True):
            st.session_state.portfolio = PaperPortfolio()
            st.success("Portfolio direset!")

    st.divider()
    st.caption(f"Polymarket Arb Bot v1.0  |  threshold: ${PROFIT_THRESHOLD:.2f}")


# ─── MAIN CONTENT ─────────────────────────────────────────────────────────────
st.markdown("""
<div class="main-header">
  <h1>📊 Polymarket Internal Arbitrage Bot</h1>
  <p>Deteksi peluang arbitrase otomatis — strategi Buy All NO &amp; Buy All YES</p>
</div>
""", unsafe_allow_html=True)

if not condition_id:
    st.markdown("""
<div class="nopp" style="text-align:center;padding:30px">
  <div style="font-size:2rem">🎯</div>
  <div style="color:#e2e4f0;margin-top:8px">Cari &amp; pilih event di sidebar untuk mulai</div>
  <div style="color:#6b7280;font-size:.85rem;margin-top:4px">
    Contoh: <code>elon musk</code>, <code>bitcoin</code>, <code>trump</code>, <code>election</code>
  </div>
</div>
""", unsafe_allow_html=True)
    st.stop()


# ─── Scan ─────────────────────────────────────────────────────────────────────
def do_scan():
    with st.spinner("Mengambil data orderbook real-time..."):
        try:
            no_result, yes_result = check_arbitrage(condition_id, market_info=market_info_override)
            st.session_state.current_result = (no_result, yes_result)
            st.session_state.scan_history.insert(0, {
                "time":       time.strftime("%H:%M:%S"),
                "no_profit":  no_result.net_profit,
                "yes_profit": yes_result.net_profit,
                "no_opp":     no_result.is_opportunity,
                "yes_opp":    yes_result.is_opportunity,
            })
            st.session_state.scan_history = st.session_state.scan_history[:30]
            if mode == "paper":
                for r in (no_result, yes_result):
                    if r.is_opportunity:
                        simulate_trade(r, st.session_state.portfolio)
            return no_result, yes_result
        except Exception as e:
            st.error(f"❌ Error: {e}")
            return None


if scan_btn:
    result_pair = do_scan()
elif st.session_state.current_result:
    result_pair = st.session_state.current_result
else:
    result_pair = None


# ─── Tampilkan hasil ──────────────────────────────────────────────────────────
if result_pair:
    no_result, yes_result = result_pair
    last_t  = st.session_state.scan_history[0]["time"] if st.session_state.scan_history else "—"
    n_valid = sum(1 for op in no_result.outcome_prices if op.no_ask is not None)

    # Judul: gunakan event title yang tersimpan, atau dari hasil scan
    display_title = (
        st.session_state.event_title
        or no_result.market.question
    )
    display_slug = st.session_state.event_slug or no_result.market.event_slug
    link = polymarket_url(display_slug)

    st.markdown(f"""
<div class="mcard">
  <h3>{display_title}</h3>
  <div class="meta">
    <code style="color:#818cf8">{condition_id[:20]}…</code>
    &nbsp;|&nbsp; {no_result.n} outcomes ({n_valid} aktif)
    &nbsp;|&nbsp; Scan: {last_t}
    &nbsp;|&nbsp; <a href="{link}" target="_blank">🔗 Buka di Polymarket ↗</a>
  </div>
</div>
""", unsafe_allow_html=True)

    opps = [r for r in (no_result, yes_result) if r.is_opportunity]
    if opps:
        best = max(opps, key=lambda r: r.net_profit)
        st.markdown(f'<div class="opp">🚨 <b>OPPORTUNITY FOUND!</b> &nbsp; Buy All <b>{best.strategy}</b> &nbsp;|&nbsp; Net: <b>${best.net_profit:.2f}</b> &nbsp;|&nbsp; ROI: <b>{best.roi_pct:.2f}%</b></div>',
                    unsafe_allow_html=True)
    elif n_valid == 0:
        st.markdown(f"""
<div class="warn">
  ⚠️ <b>Semua token 404 — orderbook tidak aktif.</b><br>
  Market ini kemungkinan <b>sudah expired atau belum ada liquidity</b>.
  Cari event yang lebih baru di sidebar (contoh: tambahkan tanggal lebih jauh seperti
  <code>elon musk march 31</code> atau <code>elon musk april</code>).
</div>
""", unsafe_allow_html=True)
    else:
        st.markdown('<div class="nopp">⏳ Tidak ada peluang arbitrase saat ini.</div>', unsafe_allow_html=True)

    tab_no, tab_yes, tab_port, tab_hist = st.tabs([
        "📉 Buy All NO", "📈 Buy All YES", "💼 Portfolio", "📋 Riwayat"
    ])
    with tab_no:
        render_result_card(no_result)
    with tab_yes:
        render_result_card(yes_result)
    with tab_port:
        render_portfolio(st.session_state.portfolio)
    with tab_hist:
        if st.session_state.scan_history:
            rows = [{
                "#":       len(st.session_state.scan_history) - i,
                "Waktu":   h["time"],
                "NO":      f"${h['no_profit']:.2f} {'✅' if h['no_opp'] else '—'}",
                "YES":     f"${h['yes_profit']:.2f} {'✅' if h['yes_opp'] else '—'}",
                "Peluang": "✅ YA" if (h["no_opp"] or h["yes_opp"]) else "—",
            } for i, h in enumerate(st.session_state.scan_history)]
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        else:
            st.caption("Belum ada riwayat.")
else:
    st.markdown('<div class="nopp" style="text-align:center;padding:24px">Tekan <b>🔍 Scan Sekarang</b> di sidebar untuk memulai.</div>',
                unsafe_allow_html=True)

# ─── Auto-refresh ─────────────────────────────────────────────────────────────
if auto_refresh and condition_id:
    time.sleep(interval)
    do_scan()
    st.rerun()
