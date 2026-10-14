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
   