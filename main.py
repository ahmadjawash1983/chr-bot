
import os
import time
import json
import math
import asyncio
import logging
import sqlite3
import threading
from datetime import datetime, timezone

import ccxt
import requests
from flask import Flask
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

# ============================================================
# DIAMOND BOT V9
# Analysis + historical backtest only. No live orders.
# ============================================================

TOKEN = os.getenv("BOT_TOKEN")
TIMEFRAME = "30m"

CAPITAL = 400.0
RISK_PERCENT = 1.5
MAX_POSITION_PCT = 0.95
FEE_PCT = 0.001
SLIPPAGE_PCT = 0.001

MAX_OPEN_TRADES = 3
DAILY_MAX_LOSS_PCT = 5.0
MIN_VOL_USD_AVG = 500_000
MAX_SPREAD_PCT = 0.003
MIN_BOOK_DEPTH_USD = 10_000

USE_COMPOUND = False
WARMUP_BARS = 250
MIN_BARS = 300
DB_PATH = "diamond_v9.db"

TOP_COINS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT",
    "XRP/USDT", "ADA/USDT", "AVAX/USDT",
    "DOT/USDT", "LINK/USDT", "NEAR/USDT",
    "TIA/USDT", "APT/USDT", "ARB/USDT",
    "OP/USDT",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("diamond")

app_flask = Flask(__name__)

state_lock = threading.RLock()
db_lock = threading.RLock()
exchange_lock = threading.RLock()

exchange = ccxt.kucoin({
    "enableRateLimit": True,
    "timeout": 15000,
})

VALID_COINS = None
FNG_CACHE = {"value": 50, "text": "Unavailable", "time": 0}
PAPER_DAILY_PNL = 0.0
PAPER_DAY = datetime.now(timezone.utc).date().isoformat()


# ============================================================
# DATABASE
# ============================================================

def db_connect():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.execute("PRAGMA busy_timeout=20000")
    return conn


def init_db():
    with db_lock:
        conn = db_connect()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS backtest_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    period TEXT NOT NULL,
                    trades INTEGER NOT NULL,
                    net_pnl REAL NOT NULL,
                    max_drawdown_pct REAL NOT NULL
                )
            """)
            conn.commit()
        finally:
            conn.close()


def save_state(key, value):
    with db_lock:
        conn = db_connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO state(key,value) VALUES(?,?)",
                (key, json.dumps(value)),
            )
            conn.commit()
        finally:
            conn.close()


def load_state(key, default):
    with db_lock:
        conn = db_connect()
        try:
            row = conn.execute(
                "SELECT value FROM state WHERE key=?",
                (key,),
            ).fetchone()
            return json.loads(row[0]) if row else default
        except (sqlite3.Error, ValueError, TypeError):
            log.exception("Failed to load state key=%s", key)
            return default
        finally:
            conn.close()


init_db()


# ============================================================
# EXCHANGE / MARKET VALIDATION
# ============================================================

def validate_markets(retries=3):
    for attempt in range(1, retries + 1):
        try:
            with exchange_lock:
                markets = exchange.load_markets()

            valid = []
            for symbol in TOP_COINS:
                market = markets.get(symbol)
                if not market:
                    continue
                if market.get("active") is False:
                    continue
                if market.get("spot") is False:
                    continue
                if market.get("quote") != "USDT":
                    continue
                valid.append(symbol)

            if valid:
                log.info("Validated markets: %s", valid)
                return valid

            raise RuntimeError("No configured spot markets validated")

        except Exception:
            log.exception("Market validation attempt %s failed", attempt)
            if attempt < retries:
                time.sleep(2 * attempt)

    return None


def fetch_ohlcv(symbol, limit):
    with exchange_lock:
        rows = exchange.fetch_ohlcv(
            symbol,
            timeframe=TIMEFRAME,
            limit=limit,
        )

    ok, reason = validate_bars(rows)
    if not ok:
        raise ValueError("Invalid OHLCV: " + reason)

    return rows


# ============================================================
# DATA VALIDATION
# CCXT candle: [timestamp, open, high, low, close, volume]
# ============================================================

def validate_bars(bars):
    if not isinstance(bars, list) or len(bars) < 2:
        return False, "Too few candles"

    previous_ts = None

    for bar in bars:
        if not isinstance(bar, (list, tuple)) or len(bar) < 6:
            return False, "Malformed candle"

        ts, op, hi, lo, cl, vol = bar[:6]

        values = (op, hi, lo, cl, vol)
        if not all(
            isinstance(x, (int, float)) and math.isfinite(x)
            for x in values
        ):
            return False, "Non-finite OHLCV"

        if not isinstance(ts, (int, float)) or not math.isfinite(ts):
            return False, "Invalid timestamp"

        if ts < 0:
            return False, "Negative timestamp"

        if previous_ts is not None and ts <= previous_ts:
            return False, "Duplicate or unordered timestamps"

        if min(op, hi, lo, cl) <= 0 or vol < 0:
            return False, "Non-positive price or negative volume"

        if hi < max(op, lo, cl):
            return False, "Invalid high"

        if lo > min(op, hi, cl):
            return False, "Invalid low"

        previous_ts = ts

    return True, "OK"


def closed_bars_only(bars):
    # Remove the current, potentially unfinished candle.
    if len(bars) < 2:
        raise ValueError("Insufficient candles")

    closed = bars[:-1]
    now_ms = int(time.time() * 1000)

    # The latest closed candle should be reasonably recent.
    if now_ms - closed[-1][0] > 3 * 60 * 60 * 1000:
        raise ValueError("Last closed candle is stale")

    return closed


# ============================================================
# INDICATORS
# ============================================================

def ema_series(values, period):
    if len(values) < period:
        return [None] * len(values)

    alpha = 2.0 / (period + 1.0)
    ema = sum(values[:period]) / period
    result = [None] * (period - 1) + [ema]

    for value in values[period:]:
        ema = alpha * value + (1 - alpha) * ema
        result.append(ema)

    return result


def ema_calc(values, period):
    result = ema_series(values, period)
    return result[-1] if result and result[-1] is not None else None


def rsi_wilder(prices, period=14):
    if len(prices) < period + 1:
        return None

    deltas = [
        prices[i] - prices[i - 1]
        for i in range(1, len(prices))
    ]

    gains = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(deltas)):
        avg_gain = (
            avg_gain * (period - 1) + gains[i]
        ) / period
        avg_loss = (
            avg_loss * (period - 1) + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def atr_wilder(bars, period=14):
    if len(bars) < period + 1:
        return None

    trs = []
    for i in range(1, len(bars)):
        high = bars[i][2]
        low = bars[i][3]
        prev_close = bars[i - 1][4]

        trs.append(max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        ))

    atr = sum(trs[:period]) / period

    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period

    return atr


def macd_full(closes):
    if len(closes) < 50:
        return None

    e12 = ema_series(closes, 12)
    e26 = ema_series(closes, 26)

    macd_values = [
        (a - b)
        for a, b in zip(e12, e26)
        if a is not None and b is not None
    ]

    if len(macd_values) < 9:
        return None

    signal_values = ema_series(macd_values, 9)
    if signal_values[-1] is None:
        return None

    macd_value = macd_values[-1]
    signal_value = signal_values[-1]

    return {
        "macd": macd_value,
        "signal": signal_value,
        "hist": macd_value - signal_value,
        "bull": macd_value > signal_value and macd_value > 0,
    }


# ============================================================
# SENTIMENT: LIVE ANALYSIS ONLY
# Historical backtest never uses current sentiment.
# ============================================================

def get_fng_cached():
    now = time.time()

    if now - FNG_CACHE["time"] < 3600:
        return FNG_CACHE["value"], FNG_CACHE["text"]

    try:
        response = requests.get(
            "https://api.alternative.me/fng/?limit=1",
            timeout=8,
        )
        response.raise_for_status()
        data = response.json()["data"][0]

        value = int(data["value"])
        text = str(data["value_classification"])

        FNG_CACHE.update({
            "value": value,
            "text": text,
            "time": now,
        })
        return value, text

    except Exception:
        log.warning("Fear & Greed unavailable")
        # Do not refresh cache time after failure.
        return None, "Unavailable"


# ============================================================
# LIQUIDITY FILTER
# ============================================================

def check_liquidity(symbol, bars):
    if len(bars) < 20:
        return False, "Need 20 closed candles"

    dollar_volumes = [b[4] * b[5] for b in bars[-20:]]
    avg_volume = sum(dollar_volumes) / len(dollar_volumes)

    if not math.isfinite(avg_volume) or avg_volume < MIN_VOL_USD_AVG:
        return False, f"Low average dollar volume: {avg_volume:.0f}"

    try:
        with exchange_lock:
            book = exchange.fetch_order_book(symbol, limit=10)

        bids = book.get("bids") or []
        asks = book.get("asks") or []

        if not bids or not asks:
            return False, "Empty order book"

        bid = bids[0][0]
        ask = asks[0][0]

        if not (
            math.isfinite(bid)
            and math.isfinite(ask)
            and 0 < bid < ask
        ):
            return False, "Invalid order book"

        spread = (ask - bid) / ask
        if spread > MAX_SPREAD_PCT:
            return False, f"Spread too high: {spread * 100:.3f}%"

        bid_depth = sum(
            p * q for p, q in bids[:5]
            if p > 0 and q > 0
        )
        ask_depth = sum(
            p * q for p, q in asks[:5]
            if p > 0 and q > 0
        )

        if min(bid_depth, ask_depth) < MIN_BOOK_DEPTH_USD:
            return False, "Insufficient order book depth"

        return True, (
            f"Volume ${avg_volume:,.0f}, "
            f"spread {spread * 100:.3f}%"
        )

    except Exception:
        log.exception("Order book check failed for %s", symbol)
        return False, "Order book unavailable; signal rejected"


# ============================================================
# SIGNAL GENERATION
# ============================================================

def generate_signal(bars, include_fng=True):
    if len(bars) < MIN_BARS:
        return None, f"Need at least {MIN_BARS} closed candles"

    closes = [b[4] for b in bars]

    ema50 = ema_calc(closes, 50)
    ema200 = ema_calc(closes, 200)
    rsi = rsi_wilder(closes)
    atr = atr_wilder(bars)
    macd = macd_full(closes)

    if any(x is None for x in (ema50, ema200, rsi, atr, macd)):
        return None, "Indicators unavailable"

    if not all(
        math.isfinite(x)
        for x in (ema50, ema200, rsi, atr)
    ):
        return None, "Invalid indicator values"

    score = 0.0
    reasons = []

    if closes[-1] > ema50 > ema200:
        score += 2
        reasons.append("Uptrend EMA")

    if 50 < rsi < 68:
        score += 1
        reasons.append(f"RSI {rsi:.1f}")

    elif 40 < rsi <= 50:
        prev_rsi = rsi_wilder(closes[:-1])
        if prev_rsi is not None and rsi > prev_rsi:
            score += 1
            reasons.append("RSI rising")

    if macd["bull"]:
        score += 1
        reasons.append("MACD bullish")
    elif macd["macd"] > 0:
        score += 0.5
        reasons.append("MACD positive")

    avg_vol = sum(b[5] for b in bars[-20:]) / 20
    last_vol = bars[-1][5]

    if avg_vol > 0 and last_vol > avg_vol * 1.5:
        if closes[-1] > closes[-2]:
            score += 2
            reasons.append("Volume surge")

    fng_value, fng_text = None, "Excluded"

    if include_fng:
        fng_value, fng_text = get_fng_cached()

        # Sentiment only affects a live signal if freshly available.
        if fng_value is not None:
            if fng_value >= 85:
                score -= 1
                reasons.append("Extreme greed penalty")
            elif fng_value <= 20:
                score += 0.5
                reasons.append("Extreme fear bonus")

    # The theoretical score maximum is 6.5 before penalties.
    return {
        "score": score,
        "reasons": reasons,
        "ema50": ema50,
        "ema200": ema200,
        "rsi": rsi,
        "atr": atr,
        "macd": macd,
        "fng": fng_value,
        "fng_text": fng_text,
    }, None


# ============================================================
# POSITION SIZING
# Costs are estimated for sizing only.
# Realized backtest costs are applied to fills and fees separately.
# ============================================================

def calc_qty(price, stop_distance, sizing_capital):
    if (
        price <= 0
        or stop_distance <= 0
        or sizing_capital <= 0
    ):
        return 0.0

    risk_amount = sizing_capital * RISK_PERCENT / 100

    estimated_cost_per_unit = (
        stop_distance
        + price * (2 * FEE_PCT + 2 * SLIPPAGE_PCT)
    )

    if estimated_cost_per_unit <= 0:
        return 0.0

    qty_risk = risk_amount / estimated_cost_per_unit

    qty_cap = (
        sizing_capital * MAX_POSITION_PCT
        / (price * (1 + FEE_PCT + SLIPPAGE_PCT))
    )

    return max(0.0, min(qty_risk, qty_cap))


# ============================================================
# LIVE ANALYSIS: SIGNALS ONLY, NO ORDERS
# ============================================================

def analyze(symbol):
    symbol = symbol.strip().upper()

    if "/" not in symbol:
        symbol += "/USDT"

    if not VALID_COINS or symbol not in VALID_COINS:
        raise ValueError("Market not validated")

    bars = closed_bars_only(fetch_ohlcv(symbol, 500))

    ok, reason = check_liquidity(symbol, bars)
    if not ok:
        raise ValueError(reason)

    signal, error = generate_signal(bars, include_fng=True)
    if error:
        raise ValueError(error)

    price = bars[-1][4]
    stop_distance = max(signal["atr"] * 1.8, price * 0.02)
    qty = calc_qty(price, stop_distance, CAPITAL)

    return {
        "symbol": symbol,
        "price": price,
        "stop_distance": stop_distance,
        "stop": price - stop_distance,
        "tp1": price + stop_distance,
        "tp2": price + stop_distance * 1.618,
        "tp3": price + stop_distance * 2.618,
        "qty": qty,
        "position_value": qty * price,
        "risk_estimate": qty * (
            stop_distance + price * (
                2 * FEE_PCT + 2 * SLIPPAGE_PCT
            )
        ),
        **signal,
    }


# ============================================================
# BACKTEST ENGINE
# Long-only candle simulation; no live orders.
# Entry at next candle open after a signal.
# Costs: slippage reflected in fills; fees charged once per side.
# Conservative assumption: stop wins if SL and TP are both touched.
# ============================================================

def simulate_backtest(bars, start_idx, end_idx):
    trades = []
    open_positions = []

    realized_equity = CAPITAL
    peak_equity = CAPITAL
    max_drawdown_pct = 0.0

    equity_curve = []
    unfinished = 0

    start_idx = max(start_idx, WARMUP_BARS)
    end_idx = min(end_idx, len(bars))

    for i in range(start_idx, end_idx):
        candle = bars[i]
        op, high, low, close = candle[1:5]

        # 1. Process positions that existed before this candle.
        remaining = []

        for pos in open_positions:
            stop_hit = low <= pos["stop"]
            target_hit = high >= pos["target"]

            exit_level = None
            reason = None

            if stop_hit:
                exit_level = pos["stop"]
                reason = "SL"
            elif target_hit:
                exit_level = pos["target"]
                reason = "TP"

            if exit_level is None:
                remaining.append(pos)
                continue

            # Gap-aware stop fill: if open is beyond the stop,
            # assume the worse opening price for a long position.
            if reason == "SL" and op < exit_level:
                raw_exit = op
            else:
                raw_exit = exit_level

            exit_fill = raw_exit * (1 - SLIPPAGE_PCT)
            exit_fee = pos["qty"] * exit_fill * FEE_PCT

            gross_pnl = (
                exit_fill - pos["entry_fill"]
            ) * pos["qty"]

            net_pnl = (
                gross_pnl
                - pos["entry_fee"]
                - exit_fee
            )

            realized_equity += net_pnl

            trades.append({
                "pnl": net_pnl,
                "gross_pnl": gross_pnl,
                "entry": pos["entry_fill"],
                "exit": exit_fill,
                "qty": pos["qty"],
                "fee": pos["entry_fee"] + exit_fee,
                "result": reason,
                "entry_index": pos["entry_index"],
                "exit_index": i,
            })

        open_positions = remaining

        # 2. Calculate mark-to-market portfolio equity.
        floating_pnl = sum(
            (close - p["entry_fill"]) * p["qty"]
            - p["entry_fee"]
            for p in open_positions
        )

        mark_equity = realized_equity + floating_pnl
        peak_equity = max(peak_equity, mark_equity)

        if peak_equity > 0:
            drawdown = (
                (peak_equity - mark_equity) / peak_equity * 100
            )
            max_drawdown_pct = max(max_drawdown_pct, drawdown)

        equity_curve.append(mark_equity)

        # 3. Stop opening new positions when max open positions reached.
        if len(open_positions) >= MAX_OPEN_TRADES:
            continue

        # 4. Only use candles strictly before candle i for the signal.
        history = bars[:i]
        if len(history) < WARMUP_BARS:
            continue

        avg_dollar_volume = sum(
            b[4] * b[5] for b in history[-20:]
        ) / 20

        if avg_dollar_volume < MIN_VOL_USD_AVG:
            continue

        # No current Fear & Greed value in historical testing.
        signal, error = generate_signal(
            history,
            include_fng=False,
        )

        if error or signal["score"] < 4:
            continue

        # 5. Entry on this candle's open, after the signal exists.
        raw_entry = op
        entry_fill = raw_entry * (1 + SLIPPAGE_PCT)

        stop_distance = max(
            signal["atr"] * 1.8,
            raw_entry * 0.02,
        )

        sizing_capital = (
            realized_equity if USE_COMPOUND else CAPITAL
        )

        qty = calc_qty(
            raw_entry,
            stop_distance,
            sizing_capital,
        )

        if qty <= 0:
            continue

        entry_fee = qty * entry_fill * FEE_PCT

        position = {
            "entry_fill": entry_fill,
            "entry_fee": entry_fee,
            "qty": qty,
            "stop": raw_entry - stop_distance,
            "target": raw_entry + stop_distance * 1.618,
            "entry_index": i,
        }

        # 6. Include entry candle in the intrabar check.
        # With OHLC-only data, order of SL/TP touches is unknown;
        # stop-first is the conservative assumption.
        stop_hit = low <= position["stop"]
        target_hit = high >= position["target"]

        if stop_hit or target_hit:
            if stop_hit:
                raw_exit = (
                    op if op < position["stop"]
                    else position["stop"]
                )
                reason = "SL"
            else:
                raw_exit = position["target"]
                reason = "TP"

            exit_fill = raw_exit * (1 - SLIPPAGE_PCT)
            exit_fee = qty * exit_fill * FEE_PCT

            gross_pnl = (
                exit_fill - entry_fill
            ) * qty

            net_pnl = gross_pnl - entry_fee - exit_fee
            realized_equity += net_pnl

            trades.append({
                "pnl": net_pnl,
                "gross_pnl": gross_pnl,
                "entry": entry_fill,
                "exit": exit_fill,
                "qty": qty,
                "fee": entry_fee + exit_fee,
                "result": reason,
                "entry_index": i,
                "exit_index": i,
            })
        else:
            open_positions.append(position)

    unfinished = len(open_positions)

    # Report unrealized positions separately at the final close.
    if end_idx > 0:
        last_close = bars[end_idx - 1][4]
        floating = sum(
            (last_close - p["entry_fill"]) * p["qty"]
            - p["entry_fee"]
            for p in open_positions
        )
        final_equity = realized_equity + floating
        peak_equity = max(peak_equity, final_equity)

        if peak_equity > 0:
            max_drawdown_pct = max(
                max_drawdown_pct,
                (peak_equity - final_equity) / peak_equity * 100,
            )
    else:
        final_equity = realized_equity

    return {
        "trades": trades,
        "realized_equity": realized_equity,
        "final_equity_marked": final_equity,
        "max_drawdown_pct": max_drawdown_pct,
        "unfinished": unfinished,
        "equity_curve": equity_curve,
    }


def format_stats(result):
    trades = result["trades"]
    total = len(trades)

    if total == 0:
        return (
            "No closed trades\n"
            f"Unfinished: {result['unfinished']}"
        )

    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] < 0]
    breakeven = [
        t for t in trades if abs(t["pnl"]) < 1e-9
    ]

    net = sum(t["pnl"] for t in trades)
    gross = sum(t["gross_pnl"] for t in trades)
    fees = sum(t["fee"] for t in trades)

    avg_win = (
        sum(t["pnl"] for t in wins) / len(wins)
        if wins else 0.0
    )
    avg_loss = (
        sum(t["pnl"] for t in losses) / len(losses)
        if losses else 0.0
    )

    win_rate = len(wins) / total * 100

    return (
        f"Closed: {total} | W: {len(wins)} "
        f"| L: {len(losses)} | BE: {len(breakeven)}\n"
        f"Win rate: {win_rate:.1f}%\n"
        f"Gross PnL: ${gross:.2f}\n"
        f"Fees: ${fees:.2f}\n"
        f"Net PnL: ${net:.2f}\n"
        f"Avg win: ${avg_win:.2f} | Avg loss: ${avg_loss:.2f}\n"
        f"Realized equity: ${result['realized_equity']:.2f}\n"
        f"Equity incl. open positions: "
        f"${result['final_equity_marked']:.2f}\n"
        f"Max DD estimate: {result['max_drawdown_pct']:.2f}%\n"
        f"Unfinished: {result['unfinished']}"
    )


# ============================================================
# TELEGRAM COMMANDS
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    coins = (
        f"{len(VALID_COINS)} validated markets"
        if VALID_COINS else "PAUSED: market validation failed"
    )

    await update.effective_message.reply_text(
        "Diamond Bot V9\n"
        "Analysis and backtesting only — no live orders.\n"
        f"{coins}\n\n"
        "/analysis BTC\n"
        "/scan\n"
        "/backtest BTC 1500\n"
        "/pnl"
    )


async def analysis_cmd(update, context):
    symbol = "BTC/USDT"

    if context.args:
        symbol = context.args[0].upper()
        if "/" not in symbol:
            symbol += "/USDT"

    await update.effective_message.reply_text(
        f"Analyzing {symbol}..."
    )

    try:
        data = await asyncio.to_thread(analyze, symbol)

        await update.effective_message.reply_text(
            f"{data['symbol']} | {TIMEFRAME}\n"
            f"Price: {data['price']:.6f}\n"
            f"RSI: {data['rsi']:.2f}\n"
            f"Score: {data['score']:.1f}/6.5\n"
            f"Reasons: {', '.join(data['reasons']) or 'None'}\n"
            f"Stop: {data['stop']:.6f}\n"
            f"TP1: {data['tp1']:.6f}\n"
            f"TP2: {data['tp2']:.6f}\n"
            f"TP3: {data['tp3']:.6f}\n"
            f"Qty estimate: {data['qty']:.6f}\n"
            f"Position value: ${data['position_value']:.2f}\n"
            f"Estimated risk incl. costs: "
            f"${data['risk_estimate']:.2f}\n"
            "Analysis only; no order was placed."
        )

    except Exception:
        log.exception("Analysis failed for %s", symbol)
        await update.effective_message.reply_text(
            "تعذر إكمال التحليل. تحقق من البيانات والسيولة "
            "أو حاول لاحقًا."
        )


async def scan_cmd(update, context):
    if not VALID_COINS:
        await update.effective_message.reply_text(
            "Bot paused: market validation failed."
        )
        return

    await update.effective_message.reply_text(
        f"Scanning {len(VALID_COINS)} markets..."
    )

    found = 0

    for symbol in VALID_COINS:
        await asyncio.sleep(0.8)

        try:
            data = await asyncio.to_thread(analyze, symbol)

            if data["score"] >= 5:
                found += 1
                await update.effective_message.reply_text(
                    f"Signal: {symbol}\n"
                    f"Score: {data['score']:.1f}/6.5\n"
                    f"RSI: {data['rsi']:.1f}\n"
                    "Analysis only; no order placed."
                )

        except Exception as exc:
            log.info("Scan skipped %s: %s", symbol, exc)

    if found == 0:
        await update.effective_message.reply_text(
            "No qualifying signals found."
        )


async def backtest_cmd(update, context):
    symbol = "BTC/USDT"
    limit = 1500

    if context.args:
        symbol = context.args[0].upper()
        if "/" not in symbol:
            symbol += "/USDT"

    if len(context.args) > 1:
        try:
            limit = int(context.args[1])
        except ValueError:
            await update.effective_message.reply_text(
                "Usage: /backtest BTC 1500"
            )
            return

    if limit < MIN_BARS + 50 or limit > 1500:
        await update.effective_message.reply_text(
            "Choose a limit from 350 to 1500 candles."
        )
        return

    await update.effective_message.reply_text(
        f"Fetching {symbol} historical data..."
    )

    try:
        bars = await asyncio.to_thread(
            fetch_ohlcv, symbol, limit
        )

        # Use closed candles only. The last candle may be unfinished.
        bars = bars[:-1]

        if len(bars) < MIN_BARS + 50:
            raise ValueError("Not enough closed historical candles")

        split = int(len(bars) * 0.7)

        if split <= WARMUP_BARS + 20:
            raise ValueError("Insufficient development period")

        # Development is strictly limited to [warmup, split).
        dev = await asyncio.to_thread(
            simulate_backtest,
            bars,
            WARMUP_BARS,
            split,
        )

        # OOS starts at split; earlier bars are used only as warmup.
        test = await asyncio.to_thread(
            simulate_backtest,
            bars,
            split,
            len(bars),
        )

        report = (
            f"{symbol} | {TIMEFRAME}\n"
            f"Closed candles: {len(bars)}\n"
            f"Split index: {split}\n\n"
            f"DEVELOPMENT\n{format_stats(dev)}\n\n"
            f"OUT-OF-SAMPLE TEST\n{format_stats(test)}\n\n"
            "Assumptions: long-only, next-open entry, "
            "no overlapping positions beyond configured limit, "
            "current sentiment excluded from historical signals, "
            "fees charged per side, slippage reflected in fills.\n"
            "OHLC-only intrabar order is unknown; stop-first "
            "is used when stop and target are both touched.\n"
            "Historical order-book spread and depth are not "
            "simulated. This is not evidence of future profitability."
        )

        # Telegram message length protection.
        if len(report) > 4000:
            report = report[:3900] + "\nReport shortened."

        await update.effective_message.reply_text(report)

        with db_lock:
            conn = db_connect()
            try:
                for period, result in (
                    ("development", dev),
                    ("oos", test),
                ):
                    conn.execute(
                        """
                        INSERT INTO backtest_runs
                        (symbol, created_at, period, trades,
                         net_pnl, max_drawdown_pct)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            symbol,
                            datetime.now(timezone.utc).isoformat(),
                            period,
                            len(result["trades"]),
                            sum(t["pnl"] for t in result["trades"]),
                            result["max_drawdown_pct"],
                        ),
                    )
                conn.commit()
            finally:
                conn.close()

    except Exception:
        log.exception("Backtest failed for %s", symbol)
        await update.effective_message.reply_text(
            "فشل الاختبار. تحقق من اتصال المنصة وعدد الشموع "
            "وصحة بيانات الزوج."
        )


async def pnl_cmd(update, context):
    with db_lock:
        conn = db_connect()
        try:
            rows = conn.execute(
                """
                SELECT symbol, period, trades, net_pnl,
                       max_drawdown_pct, created_at
                FROM backtest_runs
                ORDER BY id DESC
                LIMIT 10
                """
            ).fetchall()
        finally:
            conn.close()

    if not rows:
        await update.effective_message.reply_text(
            "No saved backtest runs yet.\n"
            "This bot does not execute live trades."
        )
        return

    lines = ["Recent backtests (not live PnL):"]

    for symbol, period, trades, pnl, dd, created in rows:
        lines.append(
            f"{symbol} | {period} | trades={trades} "
            f"| net=${pnl:.2f} | DD={dd:.2f}%\n"
            f"{created}"
        )

    await update.effective_message.reply_text(
        "\n".join(lines)[:4000]
    )


async def error_handler(update, context):
    log.error(
        "Telegram handler error",
        exc_info=context.error,
    )


# ============================================================
# FLASK / STARTUP
# ============================================================

@app_flask.route("/")
def home():
    return (
        "Diamond Bot V9 - analysis/backtest only. "
        "No live order execution."
    )


def run_flask():
    port = int(os.environ.get("PORT", "10000"))
    app_flask.run(
        host="0.0.0.0",
        port=port,
        use_reloader=False,
    )


def main():
    global VALID_COINS

    if not TOKEN:
        raise RuntimeError(
            "Missing BOT_TOKEN environment variable"
        )

    VALID_COINS = validate_markets()

    if not VALID_COINS:
        log.error(
            "Market validation failed. Analysis is paused."
        )

    threading.Thread(
        target=run_flask,
        daemon=True,
    ).start()

    bot = Application.builder().token(TOKEN).build()
    bot.add_error_handler(error_handler)

    bot.add_handler(CommandHandler("start", start))
    bot.add_handler(CommandHandler("analysis", analysis_cmd))
    bot.add_handler(CommandHandler("scan", scan_cmd))
    bot.add_handler(CommandHandler("backtest", backtest_cmd))
    bot.add_handler(CommandHandler("pnl", pnl_cmd))

    log.info("Diamond Bot V9 starting; no live orders enabled.")
    bot.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
