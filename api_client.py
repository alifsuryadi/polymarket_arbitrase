# api_client.py — Wrapper untuk Polymarket CLOB API & Gamma API

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import CLOB_BASE_URL, GAMMA_BASE_URL

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────

@dataclass
class PriceLevel:
    price: float
    size: float


@dataclass
class Orderbook:
    token_id: str
    bids: list[PriceLevel] = field(default_factory=list)
    asks: list[PriceLevel] = field(default_factory=list)

    @property
    def best_ask(self) -> Optional[float]:
        return self.asks[0].price if self.asks else None

    @property
    def best_bid(self) -> Optional[float]:
        return self.bids[0].price if self.bids else None


@dataclass
class OutcomeInfo:
    outcome_label: str    # misal "March 31", "0-50 tweets"
    yes_token_id: str
    no_token_id: str


@dataclass
class MarketInfo:
    condition_id: str
    question: str
    event_slug: str = ""
    outcomes: list[OutcomeInfo] = field(default_factory=list)


# ─────────────────────────────────────────────
# HTTP Session
# ─────────────────────────────────────────────

def _build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3, backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({"Accept": "application/json"})
    return session


_session = _build_session()


def _get(url: str, params: dict | None = None) -> list | dict:
    resp = _session.get(url, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _as_list(data) -> list:
    return data if isinstance(data, list) else ([data] if data else [])


def _parse_json_field(value, fallback):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return fallback
    return value if value is not None else fallback


# ─────────────────────────────────────────────
# Gamma API — Market discovery
# ─────────────────────────────────────────────

def fetch_active_markets(query: str = "", limit: int = 150) -> list[dict]:
    """
    Ambil markets aktif, diurutkan berdasarkan volume24hr.
    Gunakan `query` untuk filter API-side (q=...), lalu filter ulang client-side.
    """
    params: dict = {
        "active":    "true",
        "closed":    "false",
        "limit":     limit,
        "order":     "volume24hr",
        "ascending": "false",
    }
    if query.strip():
        params["q"] = query.strip()
    try:
        return _as_list(_get(f"{GAMMA_BASE_URL}/markets", params))
    except Exception as exc:
        logger.warning("Gagal ambil markets: %s", exc)
        return []


def group_markets_by_event(markets: list[dict], query: str = "") -> dict[str, dict]:
    """
    Kelompokkan markets berdasarkan parent event (dari field events[0].id).
    Hanya tampilkan event dengan 2+ binary market (multi-outcome).
    """
    q = query.strip().lower()

    groups: dict[str, dict] = {}
    for m in markets:
        events_field = m.get("events", [])
        if events_field:
            ev       = events_field[0]
            ev_id    = ev.get("id", "")
            ev_title = ev.get("title", m.get("question", "Unknown"))
            ev_slug  = ev.get("slug", "")
        else:
            ev_id    = m.get("conditionId", "")
            ev_title = m.get("question", "Unknown")
            ev_slug  = m.get("slug", "")

        if not ev_id:
            continue

        # Client-side filter: cari di judul event atau pertanyaan market
        if q:
            haystack = (ev_title + " " + m.get("question", "")).lower()
            if q not in haystack:
                continue

        if ev_id not in groups:
            groups[ev_id] = {
                "title":    ev_title,
                "slug":     ev_slug,
                "markets":  [],
                "volume24h": 0.0,
            }
        groups[ev_id]["markets"].append(m)
        groups[ev_id]["volume24h"] = max(
            groups[ev_id]["volume24h"], m.get("volume24hr", 0)
        )

    # Hanya event multi-outcome (≥2 binary market)
    return {k: v for k, v in groups.items() if len(v["markets"]) >= 2}


# ─────────────────────────────────────────────
# Gamma API — Market info
# ─────────────────────────────────────────────

def _get_event_markets(event_id: str) -> tuple[str, str, list[dict]]:
    """
    Ambil semua binary market dari GET /events/{id}.
    Return: (event_title, event_slug, list_of_markets)
    """
    try:
        event_data = _get(f"{GAMMA_BASE_URL}/events/{event_id}")
        title   = event_data.get("title", "")
        slug    = event_data.get("slug", "")
        markets = event_data.get("markets", [])
        return title, slug, markets
    except Exception as exc:
        logger.warning("Gagal ambil /events/%s: %s", event_id, exc)
        return "", "", []


def get_market_info(condition_id: str) -> MarketInfo:
    """
    Ambil semua outcome untuk satu event berdasarkan condition_id salah satu market-nya.
    Menggunakan GET /events/{id} untuk mendapatkan semua binary market dalam event.
    """
    # 1. Fetch market awal → cari parent event ID
    initial_data = _as_list(_get(
        f"{GAMMA_BASE_URL}/markets",
        {"conditionId": condition_id, "limit": 1}
    ))
    if not initial_data:
        raise ValueError(f"Market tidak ditemukan: {condition_id}")

    initial      = initial_data[0]
    events_field = initial.get("events", [])
    event_id     = events_field[0].get("id", "") if events_field else ""

    # 2. Ambil semua binary market via GET /events/{id}
    if event_id:
        event_title, event_slug, binary_markets = _get_event_markets(event_id)
        if not binary_markets:
            binary_markets = [initial]
    else:
        event_title  = ""
        event_slug   = ""
        binary_markets = [initial]

    question = event_title or initial.get("question", "Unknown Market")
    logger.info("Event '%s' — %d binary market ditemukan.", question, len(binary_markets))

    # 3. Build outcomes
    outcomes: list[OutcomeInfo] = []
    for m in binary_markets:
        if m.get("closed", False) or not m.get("active", True):
            continue
        if not m.get("enableOrderBook", True):
            continue

        tokens = _parse_json_field(m.get("clobTokenIds"), [])
        if len(tokens) < 2:
            continue

        # Label outcome yang bermakna:
        # Prioritas: groupItemTitle > pertanyaan market (diperpendek)
        group_title = m.get("groupItemTitle", "")
        mq          = m.get("question", "")
        outcome_label = group_title or mq[:60] or "Unknown"

        outcomes.append(OutcomeInfo(
            outcome_label=outcome_label,
            yes_token_id=tokens[0],
            no_token_id=tokens[1],
        ))

    logger.info("Total %d outcome valid.", len(outcomes))
    return MarketInfo(
        condition_id=condition_id,
        question=question,
        event_slug=event_slug,
        outcomes=outcomes,
    )


# ─────────────────────────────────────────────
# CLOB API — Orderbook real-time
# ─────────────────────────────────────────────

def get_orderbook(token_id: str) -> Orderbook:
    data = _get(f"{CLOB_BASE_URL}/book", params={"token_id": token_id})

    def parse_levels(raw: list[dict]) -> list[PriceLevel]:
        return [
            PriceLevel(float(x["price"]), float(x["size"]))
            for x in raw if float(x.get("size", 0)) > 0
        ]

    bids = sorted(parse_levels(data.get("bids", [])), key=lambda p: p.price, reverse=True)
    asks = sorted(parse_levels(data.get("asks", [])), key=lambda p: p.price)
    return Orderbook(token_id=token_id, bids=bids, asks=asks)
