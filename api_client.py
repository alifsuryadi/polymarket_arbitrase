# api_client.py — Wrapper untuk Polymarket CLOB API & Gamma API

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
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

def _is_expired(market: dict) -> bool:
    """Return True jika market sudah melewati endDate-nya."""
    end_str = market.get("endDate", "")
    if not end_str:
        return False
    try:
        end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
        return end_dt < datetime.now(timezone.utc)
    except Exception:
        return False


def fetch_active_markets(query: str = "", limit: int = 200) -> list[dict]:
    """
    Ambil markets aktif dengan CLOB liquidity, diurutkan berdasarkan volume24hr.
    Filter client-side: buang yang expired atau tidak punya liquidity di CLOB.
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
        all_markets = _as_list(_get(f"{GAMMA_BASE_URL}/markets", params))
        # Filter: buang yang sudah expired saja — liquidityClob di Gamma sering stale/tidak akurat
        return [m for m in all_markets if not _is_expired(m)]
    except Exception as exc:
        logger.warning("Gagal ambil markets: %s", exc)
        return []


_SPORTS_KEYWORDS = {
    "sport", "esport", "esports", "e-sport", "football", "soccer", "basketball",
    "baseball", "hockey", "tennis", "cricket", "rugby", "golf", "boxing", "mma",
    "ufc", "wrestling", "racing", "nfl", "nba", "nhl", "mlb", "fifa", "dota",
    "league of legends", "cs:go", "csgo", "valorant", "overwatch",
    "counter-strike", "starcraft",
}

_SPORTS_TITLE_HINTS = [
    "vs team", "og vs", "team spirit", "team liquid", "team secret",
]


def _is_sports_event(ev: dict, market: dict, title: str) -> bool:
    """Return True jika event ini adalah Sports/Esports — harus di-skip."""
    def _contains_sport(text: str) -> bool:
        t = text.lower()
        return any(kw in t for kw in _SPORTS_KEYWORDS)

    # 1. Cek field 'category' (bisa string atau dict)
    for src in [ev, market]:
        cat = src.get("category")
        if isinstance(cat, str) and _contains_sport(cat):
            return True
        if isinstance(cat, dict):
            for v in cat.values():
                if isinstance(v, str) and _contains_sport(v):
                    return True
        # 2. Cek categorySlug
        slug = src.get("categorySlug") or ""
        if isinstance(slug, str) and _contains_sport(slug):
            return True

    # 3. Cek tags (list of str atau list of dict)
    for src in [ev, market]:
        tags = src.get("tags") or []
        if not isinstance(tags, list):
            continue
        for tag in tags:
            if isinstance(tag, str) and _contains_sport(tag):
                return True
            if isinstance(tag, dict):
                for v in tag.values():
                    if isinstance(v, str) and _contains_sport(v):
                        return True

    # 4. Fallback: cek judul event mengandung keyword sports/esports
    if _contains_sport(title):
        return True
    tl = title.lower()
    if any(hint in tl for hint in _SPORTS_TITLE_HINTS):
        return True

    return False


def group_markets_by_event(markets: list[dict], query: str = "") -> dict[str, dict]:
    """
    Kelompokkan markets berdasarkan parent event (dari field events[0].id).
    Hanya tampilkan event dengan 2+ binary market yang masih aktif.
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

        # Skip kategori Sports / Esports (cek category, categorySlug, tags, dan title)
        if _is_sports_event(events_field[0] if events_field else {}, m, ev_title):
            continue

        # Client-side filter teks
        if q:
            haystack = (ev_title + " " + m.get("question", "")).lower()
            if q not in haystack:
                continue

        if ev_id not in groups:
            groups[ev_id] = {
                "title":     ev_title,
                "slug":      ev_slug,
                "markets":   [],
                "volume24h": 0.0,
                "end_date":  m.get("endDate", ""),
            }
        groups[ev_id]["markets"].append(m)
        groups[ev_id]["volume24h"] = max(
            groups[ev_id]["volume24h"], m.get("volume24hr", 0)
        )
        if m.get("endDate", "") > groups[ev_id]["end_date"]:
            groups[ev_id]["end_date"] = m.get("endDate", "")

    # Hanya event multi-outcome (≥2 binary market)
    result = {k: v for k, v in groups.items() if len(v["markets"]) >= 2}

    # Hitung sum YES probability untuk deteksi mutually-exclusive vs independent
    for ev_data in result.values():
        sum_yes = 0.0
        counted = 0
        for m in ev_data["markets"]:
            prices = _parse_json_field(m.get("outcomePrices"), [])
            if prices:
                try:
                    sum_yes += float(prices[0])   # prices[0] = YES probability
                    counted += 1
                except (ValueError, TypeError):
                    pass
        ev_data["sum_yes_prob"]   = sum_yes
        # Mutually exclusive: sum YES ≈ 1.0 (threshold 1.3 memberi ruang spread)
        # Independent (Bitcoin above X): sum YES bisa 1.5–3.0+
        ev_data["is_categorical"] = (counted == 0) or (sum_yes <= 1.3)

    return result


# ─────────────────────────────────────────────
# Gamma API — Market info
# ─────────────────────────────────────────────

def _fetch_event_meta(event_id: str) -> tuple[str, str]:
    """Ambil title & slug event dari GET /events/{id}."""
    try:
        data = _get(f"{GAMMA_BASE_URL}/events/{event_id}")
        return data.get("title", ""), data.get("slug", "")
    except Exception as exc:
        logger.warning("Gagal ambil /events/%s: %s", event_id, exc)
        return "", ""


def get_market_info(condition_id: str) -> MarketInfo:
    """
    Ambil semua outcome untuk satu event berdasarkan condition_id salah satu market-nya.

    Strategi pencarian sibling markets (berurutan hingga berhasil):
    A) GET /markets?eventId={id}  → full market objects lengkap dengan clobTokenIds
    B) Validasi: hanya market yang benar-benar ada di event ini (cek events[0].id)
    C) Fallback: gunakan initial market saja jika semua gagal
    """
    # 1. Fetch market awal untuk mendapatkan event ID
    initial_data = _as_list(_get(
        f"{GAMMA_BASE_URL}/markets",
        {"conditionId": condition_id, "limit": 1}
    ))
    if not initial_data:
        raise ValueError(f"Market tidak ditemukan: {condition_id}")

    initial      = initial_data[0]
    events_field = initial.get("events", [])
    event_id     = str(events_field[0].get("id", "")) if events_field else ""

    # 2. Ambil title & slug event
    if event_id:
        event_title, event_slug = _fetch_event_meta(event_id)
    else:
        event_title = ""
        event_slug  = ""

    question = event_title or initial.get("question", "Unknown Market")

    # 3. Ambil semua sibling markets via /markets?eventId=... (format lengkap + clobTokenIds)
    siblings: list[dict] = []
    if event_id:
        try:
            candidates = _as_list(_get(
                f"{GAMMA_BASE_URL}/markets",
                {"eventId": event_id, "active": "true", "closed": "false", "limit": 100}
            ))
            # Validasi: hanya market yang events[0].id cocok dengan event ini
            siblings = [
                m for m in candidates
                if any(str(e.get("id")) == event_id for e in m.get("events", []))
            ]
            logger.info("eventId=%s → %d/%d sibling valid.", event_id, len(siblings), len(candidates))
        except Exception as exc:
            logger.warning("Gagal ambil sibling markets: %s", exc)

    # Fallback ke initial market jika tidak ada siblings valid
    if not siblings:
        siblings = [initial]

    # 4. Build outcomes
    outcomes: list[OutcomeInfo] = []
    for m in siblings:
        tokens = _parse_json_field(m.get("clobTokenIds"), [])
        if len(tokens) < 2:
            logger.debug("Market %s tidak punya clobTokenIds, dilewati.", m.get("id"))
            continue

        # Label: groupItemTitle (misal "March 31", "0-50") > question market
        outcome_label = (
            m.get("groupItemTitle")
            or m.get("question", "Unknown")[:60]
        )
        outcomes.append(OutcomeInfo(
            outcome_label=outcome_label,
            yes_token_id=tokens[0],
            no_token_id=tokens[1],
        ))

    logger.info("Total %d outcome valid untuk '%s'.", len(outcomes), question)
    return MarketInfo(
        condition_id=condition_id,
        question=question,
        event_slug=event_slug,
        outcomes=outcomes,
    )


def build_market_info(
    markets: list[dict],
    event_title: str,
    event_slug: str,
    condition_id: str,
) -> MarketInfo:
    """
    Build MarketInfo langsung dari list market yang sudah di-fetch UI.
    Digunakan untuk menghindari re-fetch sibling via eventId yang tidak reliable.
    """
    outcomes: list[OutcomeInfo] = []
    for m in markets:
        tokens = _parse_json_field(m.get("clobTokenIds"), [])
        if len(tokens) < 2:
            logger.debug("Market %s tidak punya clobTokenIds, dilewati.", m.get("id"))
            continue
        outcome_label = (
            m.get("groupItemTitle")
            or m.get("question", "Unknown")[:60]
        )
        outcomes.append(OutcomeInfo(
            outcome_label=outcome_label,
            yes_token_id=tokens[0],
            no_token_id=tokens[1],
        ))
    logger.info("build_market_info: %d outcome dari %d market.", len(outcomes), len(markets))
    return MarketInfo(
        condition_id=condition_id,
        question=event_title,
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
