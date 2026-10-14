import os
import threading
import ccxt
import pandas as pd
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")
TIMEFRAME = "30m"
CAPITAL = 400
RISK_PERCENT = 1.5

TOP_COINS = [
    "BTC/USDT","ETH/USDT","SOL/USDT","BNB/USDT","XRP/USDT",
    "DOGE/USDT","ADA/USDT","AVAX/USDT","SHIB/USDT","DOT/USDT",
    "LINK/USDT","TRX/USDT","MATIC/USDT","LTC/USDT","BCH/USDT",
    "NEAR/USDT","UNI/USDT","PEPE/USDT","ETC/USDT","APT/USDT"
]

app_flask = Flask(__name__)
exchange = ccxt.binance()

@app_flask.route('/')
def home():
    return "Diamond Bot Live - 400$ - Fixed"

def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0).ewm(alpha=1/period, adjust=False).mean()
    loss = -delta.where(delta < 0, 0).ewm(alpha=1/period, adjust=False).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def atr(h, l, c, period=14):
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()

def analyze(symbol):
    bars = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=200)
    df = pd.DataFrame(bars, columns=['t','o','h','l','c','v'])
    df['ema50'] = ema(df['c'], 50)
    df['ema200'] = ema(df['c'], 200)
    df['rsi'] = rsi(df['c'], 14)
    df['atr'] = atr(df['h'], df['l'], df['c'], 14)
    e12 = ema(df['c'], 12)
    e26 = ema(df['c'], 26)
    df['macd'] = e12 - e26
    df['signal'] = ema(df['macd'], 9)
    last = df.iloc[-1]
    vol_avg = df['v'].rolling(20).mean().iloc[-1]

    score = 0
    reasons = []
    if last['c'] > last['ema50'] and last['ema50'] > last['ema200']:
        score += 2
        reasons.append("Uptrend EMA")
    if 30 < last['rsi'] < 50:
        score += 1
        reasons.append(f"RSI {last['rsi']:.0f}")
    if last['macd'] > last['signal']:
        score += 1
        reasons.append("MACD Bullish")
    if last['v'] > vol_avg * 1.5:
        score += 2
        reasons.append(f"Vol {last['v']/vol_avg:.1f}x")

    stop = last['l'] - last['atr'] * 1.5
    risk_amt = CAPITAL * (RISK_PERCENT / 100)
    risk_per_coin = last['c'] - stop
    qty = risk_amt / risk_per_coin if risk_per_coin > 0 else 0
    target = last['c'] + last['atr'] * 3
    return score, reasons, last, stop, target, qty

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
       