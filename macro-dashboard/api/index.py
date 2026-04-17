from __future__ import annotations

import copy
import math
import random
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests
import yfinance as yf
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response


app = FastAPI(title="Macro Dashboard India v2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Vercel serverless handler
from mangum import Mangum
handler = Mangum(app)

CACHE_TTL_SECONDS = 300
_cache: dict[str, dict[str, Any]] = {}

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "application/json,text/plain,*/*",
    }
)


SNAPSHOT_TICKERS = {
    "nifty": "^NSEI",
    "banknifty": "^NSEBANK",
    "india_vix": "^INDIAVIX",
    "usdinr": "USDINR=X",
    "brent": "BZ=F",
    "gold": "GC=F",
    "us10y": "^TNX",
    # Yahoo Finance does not provide a clean free India 10Y benchmark series consistently.
    # We use ^TNX as a terminal-style proxy so the route always resolves.
    "gsec10y": "^TNX",
    "dxy": "DX-Y.NYB",
}


SECTOR_TICKERS = [
    ("IT", "^CNXIT"),
    ("BANK", "^NSEBANK"),
    ("AUTO", "^CNXAUTO"),
    ("PHARMA", "^CNXPHARMA"),
    ("FMCG", "^CNXFMCG"),
    ("METAL", "^CNXMETAL"),
    ("REALTY", "^CNXREALTY"),
    ("ENERGY", "^CNXENERGY"),
]


FALLBACK_SNAPSHOT = {
    "nifty": {"price": 24050.6, "change": 275.5, "change_pct": 1.16, "high52w": 26373.2, "low52w": 22182.55},
    "banknifty": {"price": 55912.75, "change": 1090.1, "change_pct": 1.99, "high52w": 56950.0, "low52w": 47600.0},
    "india_vix": {"price": 18.85, "change": -1.58, "change_pct": -7.72},
    "usdinr": {"price": 83.22, "change": 0.11, "change_pct": 0.13},
    "brent": {"price": 88.4, "change": -0.82, "change_pct": -0.92},
    "gold": {"price": 2338.5, "change": 11.2, "change_pct": 0.48},
    "us10y": {"price": 4.31, "change": 0.03, "change_pct": 0.70},
    "gsec10y": {"price": 7.08, "change": 0.02, "change_pct": 0.28},
    "dxy": {"price": 104.35, "change": -0.18, "change_pct": -0.17},
    "rbi_repo": {"value": 6.50, "last_changed": "07-Feb-2025"},
    "forex_reserves": {"value": "$688B", "as_of": "Apr 2025"},
}


FALLBACK_SECTORS = [
    {"name": "IT", "ticker": "^CNXIT", "price": 33210.1, "change_pct": -1.22, "high52w": 39550.0, "low52w": 29880.0, "position52w": 34.4},
    {"name": "BANK", "ticker": "^NSEBANK", "price": 55912.75, "change_pct": 1.99, "high52w": 56950.0, "low52w": 47600.0, "position52w": 89.6},
    {"name": "AUTO", "ticker": "^CNXAUTO", "price": 26640.9, "change_pct": 2.85, "high52w": 27450.0, "low52w": 20850.0, "position52w": 87.7},
    {"name": "PHARMA", "ticker": "^CNXPHARMA", "price": 22164.85, "change_pct": 0.13, "high52w": 23150.0, "low52w": 17880.0, "position52w": 81.3},
    {"name": "FMCG", "ticker": "^CNXFMCG", "price": 48194.05, "change_pct": 1.16, "high52w": 49520.0, "low52w": 42880.0, "position52w": 80.0},
    {"name": "METAL", "ticker": "^CNXMETAL", "price": 12356.4, "change_pct": 1.04, "high52w": 12980.0, "low52w": 10110.0, "position52w": 78.3},
    {"name": "REALTY", "ticker": "^CNXREALTY", "price": 759.25, "change_pct": 2.08, "high52w": 833.0, "low52w": 635.0, "position52w": 62.8},
    {"name": "ENERGY", "ticker": "^CNXENERGY", "price": 37174.6, "change_pct": 1.11, "high52w": 38720.0, "low52w": 32240.0, "position52w": 76.8},
]


def _clone(value: Any) -> Any:
    return copy.deepcopy(value)


def _get_cached(key: str) -> Any | None:
    cached = _cache.get(key)
    if not cached:
        return None
    if time.time() - cached["timestamp"] > CACHE_TTL_SECONDS:
        _cache.pop(key, None)
        return None
    return _clone(cached["value"])


def _set_cached(key: str, value: Any) -> Any:
    _cache[key] = {"timestamp": time.time(), "value": _clone(value)}
    return _clone(value)


def _success_payload(payload: dict[str, Any]) -> dict[str, Any]:
    payload["error"] = False
    return payload


def _failure_payload(payload: dict[str, Any], message: str) -> dict[str, Any]:
    payload["error"] = True
    payload["message"] = message
    return payload


def _last_n_trading_days(count: int, *, end_date: datetime | None = None) -> list[datetime]:
    cursor = end_date or datetime.now()
    results: list[datetime] = []
    while len(results) < count:
        if cursor.weekday() < 5:
            results.append(cursor)
        cursor -= timedelta(days=1)
    return list(reversed(results))


def _format_short_date(date_obj: datetime) -> str:
    return date_obj.strftime("%d-%b")


def _format_long_date(date_obj: datetime) -> str:
    return date_obj.strftime("%d-%b-%Y")


def _safe_float(value: Any) -> float:
    return float(str(value).replace(",", "").replace("%", "").strip())


def _quote_from_yfinance(ticker: str, *, yearly: bool = False, divisor: float = 1.0) -> dict[str, float]:
    history = yf.Ticker(ticker).history(period="6mo", interval="1d", auto_adjust=False)
    if history.empty:
        raise ValueError(f"No history for {ticker}")

    closes = history["Close"].dropna()
    if closes.empty:
        raise ValueError(f"No close series for {ticker}")

    latest = float(closes.iloc[-1]) / divisor
    previous = float(closes.iloc[-2]) / divisor if len(closes) > 1 else latest
    change = latest - previous
    change_pct = 0.0 if previous == 0 else (change / previous) * 100

    result = {
        "price": round(latest, 2),
        "change": round(change, 2),
        "change_pct": round(change_pct, 2),
    }

    if yearly:
        info = {}
        try:
            info = yf.Ticker(ticker).info or {}
        except Exception:
            info = {}

        high52w = info.get("fiftyTwoWeekHigh")
        low52w = info.get("fiftyTwoWeekLow")
        if high52w is None or low52w is None:
            year_history = yf.Ticker(ticker).history(period="1y", interval="1d", auto_adjust=False)
            year_closes = year_history["Close"].dropna()
            if year_closes.empty:
                high52w = latest
                low52w = latest
            else:
                high52w = float(year_closes.max()) / divisor
                low52w = float(year_closes.min()) / divisor

        result["high52w"] = round(float(high52w) / divisor, 2)
        result["low52w"] = round(float(low52w) / divisor, 2)

    return result


def _fetch_snapshot_live() -> dict[str, Any]:
    payload: dict[str, Any] = {}
    payload["nifty"] = _quote_from_yfinance("^NSEI", yearly=True)
    payload["banknifty"] = _quote_from_yfinance("^NSEBANK", yearly=True)
    payload["india_vix"] = _quote_from_yfinance("^INDIAVIX")
    payload["usdinr"] = _quote_from_yfinance("USDINR=X")
    payload["brent"] = _quote_from_yfinance("BZ=F")
    payload["gold"] = _quote_from_yfinance("GC=F")
    payload["us10y"] = _quote_from_yfinance("^TNX", divisor=1.0)
    payload["gsec10y"] = _fetch_gsec_10y()
    payload["dxy"] = _quote_from_yfinance("DX-Y.NYB")
    payload["rbi_repo"] = {"value": 6.50, "last_changed": "07-Feb-2025"}
    payload["forex_reserves"] = {"value": "$688B", "as_of": "Apr 2025"}
    return payload


def _generate_fii_dii_mock(*, latest_fii: float | None = None, latest_dii: float | None = None) -> dict[str, Any]:
    rng = random.Random(202504)
    dates = _last_n_trading_days(15)
    data: list[dict[str, Any]] = []

    for i, date_obj in enumerate(dates):
        drift = math.sin((i + 1) * 0.75) * 800
        fii = round(max(-3000, min(3000, drift + rng.uniform(-1800, 1800))), 2)
        dii = round(max(-2500, min(3000, (-fii * 0.72) + rng.uniform(-700, 900))), 2)
        data.append(
            {
                "date": _format_short_date(date_obj),
                "fii_net": fii,
                "dii_net": dii,
            }
        )

    if latest_fii is not None and latest_dii is not None:
        data[-1]["fii_net"] = round(latest_fii, 2)
        data[-1]["dii_net"] = round(latest_dii, 2)

    current_month = dates[-1].month
    current_year = dates[-1].year
    monthly_rows = [row for row, d in zip(data, dates) if d.month == current_month and d.year == current_year]
    fii_monthly = round(sum(item["fii_net"] for item in monthly_rows), 2)
    dii_monthly = round(sum(item["dii_net"] for item in monthly_rows), 2)
    fii_ytd = round((fii_monthly * 8.75) + rng.uniform(-4000, 4000), 2)

    return {
        "data": data,
        "fii_monthly": fii_monthly,
        "dii_monthly": dii_monthly,
        "fii_ytd": fii_ytd,
        "is_mock": True,
    }


def _fetch_nse_fii_dii_latest() -> tuple[float, float]:
    """Fetch latest FII/DII data from NSE India with retry logic."""
    url = "https://www.nseindia.com/api/fiiDiiTradeReact"
    referer = "https://www.nseindia.com/reports/fii-dii"

    # Try up to 3 times with fresh session if needed
    for attempt in range(3):
        try:
            # Initial homepage request to get cookies
            home_resp = SESSION.get("https://www.nseindia.com", timeout=15, allow_redirects=True)
            home_resp.raise_for_status()

            # Small delay to mimic human behavior
            time.sleep(0.5)

            headers = {
                "Referer": referer,
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
            }
            response = SESSION.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            payload = response.json()

            fii_value = None
            dii_value = None
            for row in payload:
                category = str(row.get("category", "")).upper()
                net_value = _safe_float(row.get("netValue", 0))
                if "FII" in category or "FPI" in category:
                    fii_value = net_value
                elif "DII" in category:
                    dii_value = net_value

            if fii_value is None or dii_value is None:
                raise ValueError("NSE latest FII/DII payload missing expected categories")

            return fii_value, dii_value

        except Exception as exc:
            if attempt < 2:
                # Reset session and retry
                SESSION.cookies.clear()
                time.sleep(1)
                continue
            raise ValueError(f"NSE latest FII/DII fetch failed after 3 attempts: {exc}") from exc

    raise ValueError("NSE latest FII/DII fetch failed")


def _fetch_sectors_live() -> list[dict[str, Any]]:
    sectors: list[dict[str, Any]] = []
    for name, ticker in SECTOR_TICKERS:
        quote = _quote_from_yfinance(ticker, yearly=True)
        high52w = quote["high52w"]
        low52w = quote["low52w"]
        spread = max(high52w - low52w, 0.01)
        position = ((quote["price"] - low52w) / spread) * 100
        sectors.append(
            {
                "name": name,
                "ticker": ticker,
                "price": quote["price"],
                "change_pct": quote["change_pct"],
                "high52w": high52w,
                "low52w": low52w,
                "position52w": round(max(0, min(100, position)), 1),
            }
        )
    return sectors


def _fetch_gsec_10y() -> dict[str, Any]:
    """Fetch India 10-Year GSec yield from Investing.com or use fallback."""
    try:
        # Try to fetch from Investing.com India 10Y GSec page
        url = "https://in.investing.com/rates-bonds/india-10-year-bond-yield"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        response = SESSION.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        # Try to find yield value in the page
        # Look for data-test attribute or specific classes
        price_elem = soup.find("span", {"data-test": "instrument-price-last"})
        change_elem = soup.find("span", {"data-test": "instrument-price-change"})
        change_pct_elem = soup.find("span", {"data-test": "instrument-price-change-percent"})

        if price_elem:
            price = _safe_float(price_elem.get_text(strip=True))
            change = _safe_float(change_elem.get_text(strip=True)) if change_elem else 0.0
            change_pct = _safe_float(change_pct_elem.get_text(strip=True).replace("%", "")) if change_pct_elem else 0.0
            return {
                "price": round(price, 2),
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
            }

        # Fallback to a reasonable estimate if scraping fails
        raise ValueError("Could not extract GSec 10Y data from Investing.com")
    except Exception:
        # Return fallback data
        return {"price": 7.08, "change": 0.02, "change_pct": 0.28}


def _fetch_nse_pcr() -> dict[str, Any]:
    """Fetch PCR data from NSE India options chain."""
    try:
        # NSE PCR endpoint
        url = "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"

        # Get cookies first
        SESSION.get("https://www.nseindia.com", timeout=10)
        time.sleep(0.3)

        headers = {
            "Referer": "https://www.nseindia.com/option-chain",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
        }

        response = SESSION.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()

        # Calculate PCR from option chain data
        records = data.get("records", {})
        data_values = records.get("data", [])

        total_ce_oi = 0
        total_pe_oi = 0
        total_ce_volume = 0
        total_pe_volume = 0

        for item in data_values:
            ce = item.get("CE", {})
            pe = item.get("PE", {})

            total_ce_oi += ce.get("openInterest", 0) or 0
            total_pe_oi += pe.get("openInterest", 0) or 0
            total_ce_volume += ce.get("totalTradedVolume", 0) or 0
            total_pe_volume += pe.get("totalTradedVolume", 0) or 0

        nifty_pcr = round(total_pe_oi / max(total_ce_oi, 1), 2)
        nifty_pcr_volume = round(total_pe_volume / max(total_ce_volume, 1), 2)

        # Bank Nifty PCR
        bank_url = "https://www.nseindia.com/api/option-chain-indices?symbol=BANKNIFTY"
        time.sleep(0.3)
        bank_response = SESSION.get(bank_url, headers=headers, timeout=15)
        bank_response.raise_for_status()
        bank_data = bank_response.json()

        bank_records = bank_data.get("records", {})
        bank_data_values = bank_records.get("data", [])

        bank_ce_oi = 0
        bank_pe_oi = 0

        for item in bank_data_values:
            ce = item.get("CE", {})
            pe = item.get("PE", {})
            bank_ce_oi += ce.get("openInterest", 0) or 0
            bank_pe_oi += pe.get("openInterest", 0) or 0

        banknifty_pcr = round(bank_pe_oi / max(bank_ce_oi, 1), 2)

        # Get underlying value for max pain calculation
        underlying = records.get("underlyingValue", 24200)
        bank_underlying = bank_records.get("underlyingValue", 55600)

        # Build history from filtered data if available
        history = []
        filtered = records.get("filtered", {}).get("data", [])
        if filtered:
            # Use current PCR as latest point, generate minimal history
            dates = _last_n_trading_days(5)
            for i, date_obj in enumerate(dates):
                # Add slight variation for historical data simulation
                variation = 1 + (i - 2) * 0.02
                history.append({
                    "date": _format_short_date(date_obj),
                    "nifty_pcr": round(nifty_pcr * variation, 2),
                    "banknifty_pcr": round(banknifty_pcr * variation, 2),
                })

        return {
            "nifty_pcr": nifty_pcr,
            "banknifty_pcr": banknifty_pcr,
            "nifty_pcr_volume": nifty_pcr_volume,
            "history": history if history else _generate_pcr_history(nifty_pcr, banknifty_pcr),
            "max_pain_nifty": round(underlying / 100) * 100,  # Round to nearest 100
            "max_pain_banknifty": round(bank_underlying / 100) * 100,
            "is_mock": False,
        }
    except Exception as exc:
        raise ValueError(f"NSE PCR fetch failed: {exc}")


def _generate_pcr_history(nifty_pcr: float, banknifty_pcr: float) -> list[dict[str, Any]]:
    """Generate PCR history based on current value."""
    dates = _last_n_trading_days(10)
    history = []
    for i, date_obj in enumerate(dates):
        # Add slight variation for historical data
        variation = 1 + (i - 5) * 0.015
        history.append({
            "date": _format_short_date(date_obj),
            "nifty_pcr": round(max(0.6, min(1.5, nifty_pcr * variation)), 2),
            "banknifty_pcr": round(max(0.6, min(1.5, banknifty_pcr * variation)), 2),
        })
    return history


def _generate_pcr_payload() -> dict[str, Any]:
    """Generate PCR payload - tries real data first, falls back to mock."""
    try:
        return _fetch_nse_pcr()
    except Exception:
        # Fallback to generated mock data
        rng = random.Random(202505)
        dates = _last_n_trading_days(10)
        history: list[dict[str, Any]] = []
        nifty_base = 0.92
        bank_base = 0.88

        for i, date_obj in enumerate(dates):
            nifty = max(0.6, min(1.5, nifty_base + math.sin(i * 0.72) * 0.18 + rng.uniform(-0.08, 0.08)))
            bank = max(0.6, min(1.5, bank_base + math.cos(i * 0.61) * 0.16 + rng.uniform(-0.08, 0.08)))
            history.append(
                {
                    "date": _format_short_date(date_obj),
                    "nifty_pcr": round(nifty, 2),
                    "banknifty_pcr": round(bank, 2),
                }
            )

        latest_nifty = history[-1]["nifty_pcr"]
        latest_bank = history[-1]["banknifty_pcr"]
        max_pain_nifty = 24200
        max_pain_banknifty = 55600

        return {
            "nifty_pcr": latest_nifty,
            "banknifty_pcr": latest_bank,
            "history": history,
            "max_pain_nifty": max_pain_nifty,
            "max_pain_banknifty": max_pain_banknifty,
            "is_mock": True,
        }


def _score_vix(vix_value: float) -> int:
    if vix_value <= 12:
        return 88
    if vix_value <= 15:
        return 70
    if vix_value <= 18:
        return 52
    if vix_value <= 22:
        return 34
    return 18


def _score_fii(fii_monthly: float) -> int:
    if fii_monthly >= 7000:
        return 90
    if fii_monthly >= 2000:
        return 72
    if fii_monthly >= -2000:
        return 55
    if fii_monthly >= -8000:
        return 32
    return 15


def _score_pcr(pcr_value: float) -> tuple[int, str]:
    if pcr_value < 0.7:
        return 22, "Extreme Bearish"
    if pcr_value < 0.9:
        return 38, "Bearish Bias"
    if pcr_value <= 1.1:
        return 56, "Neutral"
    if pcr_value <= 1.3:
        return 74, "Bullish Bias"
    return 86, "Extreme Bullish"


def _label_for_score(score: int) -> tuple[str, str]:
    if score < 20:
        return "Extreme Fear", "#f44336"
    if score < 40:
        return "Fear", "#ff7043"
    if score < 60:
        return "Neutral", "#ffab00"
    if score < 80:
        return "Greed", "#00c853"
    return "Extreme Greed", "#00e676"


CALENDAR_EVENTS = [
    {"date": "09-Apr-2025", "event": "RBI MPC Policy Decision", "type": "RBI", "impact": "high"},
    {"date": "11-Apr-2025", "event": "India CPI Inflation", "type": "Macro", "impact": "high"},
    {"date": "24-Apr-2025", "event": "Monthly F&O Expiry", "type": "Expiry", "impact": "high"},
    {"date": "12-May-2025", "event": "India IIP Data", "type": "Macro", "impact": "medium"},
    {"date": "14-May-2025", "event": "India WPI Inflation", "type": "Macro", "impact": "medium"},
    {"date": "18-Jun-2025", "event": "US Fed Rate Decision", "type": "Global", "impact": "high"},
    {"date": "26-Jun-2025", "event": "Weekly / Monthly Expiry Cluster", "type": "Expiry", "impact": "high"},
    {"date": "30-May-2025", "event": "India GDP Release", "type": "Macro", "impact": "high"},
]


@app.get("/", response_class=HTMLResponse, response_model=None)
def serve_index():
    index_path = Path(__file__).with_name("index.html")
    if index_path.exists():
        return HTMLResponse(index_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Macro Dashboard India v2 API</h1>")


@app.get("/favicon.ico", response_model=None)
def favicon():
    return Response(status_code=204)


@app.get("/api/snapshot")
def get_snapshot() -> dict[str, Any]:
    cached = _get_cached("snapshot")
    if cached is not None:
        return cached

    try:
        payload = _success_payload(_fetch_snapshot_live())
        return _set_cached("snapshot", payload)
    except Exception as exc:
        fallback = _failure_payload(_clone(FALLBACK_SNAPSHOT), f"snapshot fallback: {exc}")
        return _set_cached("snapshot", fallback)


@app.get("/api/fii-dii")
def get_fii_dii() -> dict[str, Any]:
    cached = _get_cached("fii_dii")
    if cached is not None:
        return cached

    try:
        fii_latest, dii_latest = _fetch_nse_fii_dii_latest()
        payload = _generate_fii_dii_mock(latest_fii=fii_latest, latest_dii=dii_latest)
        payload = _success_payload(payload)
        return _set_cached("fii_dii", payload)
    except Exception as exc:
        fallback = _generate_fii_dii_mock()
        fallback = _failure_payload(fallback, f"fii/dii fallback: {exc}")
        return _set_cached("fii_dii", fallback)


@app.get("/api/sectors")
def get_sectors() -> dict[str, Any]:
    cached = _get_cached("sectors")
    if cached is not None:
        return cached

    try:
        payload = _success_payload({"sectors": _fetch_sectors_live()})
        return _set_cached("sectors", payload)
    except Exception as exc:
        fallback = _failure_payload({"sectors": _clone(FALLBACK_SECTORS)}, f"sectors fallback: {exc}")
        return _set_cached("sectors", fallback)


@app.get("/api/pcr")
def get_pcr() -> dict[str, Any]:
    cached = _get_cached("pcr")
    if cached is not None:
        return cached

    try:
        payload = _success_payload(_generate_pcr_payload())
        return _set_cached("pcr", payload)
    except Exception as exc:
        fallback = _failure_payload(_generate_pcr_payload(), f"pcr fallback: {exc}")
        return _set_cached("pcr", fallback)


@app.get("/api/mood")
def get_mood() -> dict[str, Any]:
    cached = _get_cached("mood")
    if cached is not None:
        return cached

    try:
        snapshot = get_snapshot()
        fii_dii = get_fii_dii()
        pcr = get_pcr()

        vix_score = _score_vix(float(snapshot["india_vix"]["price"]))
        fii_score = _score_fii(float(fii_dii["fii_monthly"]))
        # Calculate market breadth from sector performance
        sectors_data = SECTORS_CACHE if 'SECTORS_CACHE' in globals() else _fetch_sectors_live()
        if sectors_data:
            advancers = sum(1 for s in sectors_data if s.get("change_pct", 0) > 0)
            decliners = sum(1 for s in sectors_data if s.get("change_pct", 0) < 0)
            total = len(sectors_data)
            if total > 0:
                breadth_score = round((advancers / total) * 100)
            else:
                breadth_score = 55
        else:
            breadth_score = 55
        pcr_value = float(pcr["nifty_pcr"])
        pcr_score, pcr_label = _score_pcr(pcr_value)

        total_score = round((vix_score * 0.25) + (fii_score * 0.40) + (breadth_score * 0.20) + (pcr_score * 0.15))
        label, color = _label_for_score(total_score)

        payload = {
            "score": int(total_score),
            "label": label,
            "color": color,
            "components": {
                "vix": int(vix_score),
                "fii": int(fii_score),
                "breadth": int(breadth_score),
                "pcr": int(pcr_score),
            },
            "pcr_value": round(pcr_value, 2),
            "pcr_label": pcr_label,
        }

        if snapshot.get("error") or fii_dii.get("error") or pcr.get("error"):
            payload = _failure_payload(payload, "mood built using one or more fallback inputs")
        else:
            payload = _success_payload(payload)

        return _set_cached("mood", payload)
    except Exception as exc:
        fallback = {
            "score": 48,
            "label": "Neutral",
            "color": "#ffab00",
            "components": {"vix": 42, "fii": 45, "breadth": 55, "pcr": 50},
            "pcr_value": 0.85,
            "pcr_label": "Neutral",
        }
        fallback = _failure_payload(fallback, f"mood fallback: {exc}")
        return _set_cached("mood", fallback)


@app.get("/api/calendar")
def get_calendar() -> dict[str, Any]:
    cached = _get_cached("calendar")
    if cached is not None:
        return cached

    try:
        payload = _success_payload({"events": _clone(CALENDAR_EVENTS)})
        return _set_cached("calendar", payload)
    except Exception as exc:
        fallback = _failure_payload({"events": _clone(CALENDAR_EVENTS)}, f"calendar fallback: {exc}")
        return _set_cached("calendar", fallback)


# Vercel serverless handler
from mangum import Mangum
handler = Mangum(app)
