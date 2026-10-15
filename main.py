# -*- coding: utf-8 -*-
import os, time, threading, requests, ccxt, asyncio
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")
TIMEFRAME = "30m"
CAPITAL = 400
RISK_PERCENT = 1.5
MAX_POSITION_PCT = 0.95
FEE_PCT = 0.001

TOP_COINS = ["BTC/USDT","ETH/USDT","SOL/USDT","BNB/USDT","XRP/USDT","DOGE/USDT","ADA/USDT","AVAX/USDT","SHIB/USDT","DOT/USDT","LINK/USDT","TRX/USDT","MATIC/USDT","LTC/USDT","BCH/USDT","NEAR/USDT","UNI/USDT","PEPE/USDT","ETC/USDT","APT/USDT"]

app_flask = Flask(__name__)
exchange = ccxt.kucoin()

@app_flask.route('/')
def home():
    return "Diamond Bot Live V2 Fixed"

def get_fear_greed():
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10).json()
        return int(r['data'][0]['value']), r['data'][0]['value_classification']
    except:
        return 50, "Unknown"

def get_news():
    try:
        r = requests.get("https://min-api.cryptocompare.com/data/v2/news/?lang=EN", timeout=10).json()
        return r['Data'][:3]
    except:
        return []

def ema_calc_proper(prices, period):
    if len(prices) < period: return sum(prices)/len(prices)
    ema = sum(prices[:period]) / period
    k = 2 / (period + 1)
    for p in prices[period:]:
        ema = p*k + ema*(1-k)
    return ema

def rsi_calc_proper(prices, period=14):
    if len(prices) < period + 1: return 50
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains = [max(d, 0) for d in deltas[-period:]]
    losses = [abs(min(d, 0)) for d in deltas[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0: return 100 if avg_gain > 0 else 50
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain*(period-1) + max(deltas[i],0)) / period
        avg_loss = (avg_loss*(period-1) + abs(min(deltas[i],0))) / period
    if avg_loss == 0: return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def atr_calc_proper(bars, period=14):
    if len(bars) < period+1: return 0
    trs = []
    for i in range(1, len(bars)):
        high = bars[i][2]
        low = bars[i][3]
        prev_close = bars[i-1][4]
        tr = max(high-low, abs(high-prev_close), abs(low-prev_close))
        trs.append(tr)
    return sum(trs[-period:]) / period

def analyze(symbol):
    bars = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=201)
    closed_bars = bars[:-1]
    if len(closed_bars) < 200: closed_bars = bars
    closes=[b[4] for b in closed_bars]; highs=[b[2] for b in closed_bars]; lows=[b[3] for b in closed_bars]; vols=[b[5] for b in closed_bars]
    c=closes[-1]
    ema50=ema_calc_proper(closes,50)
    ema200=ema_calc_proper(closes,200)
    rsi=rsi_calc_proper(closes,14)
    e12=ema_calc_proper(closes,12)
    e26=ema_calc_proper(closes,26)
    macd=e12-e26
    macd_prev = ema_calc_proper(closes[:-1],12) - ema_calc_proper(closes[:-1],26)
    vol_avg=sum(vols[-20:])/20 if len(vols)>=20 else vols[-1]
    vol=vols[-1]
    score=0; reasons=[]
    if c>ema50 and ema50>ema200: score+=2; reasons.append("Uptrend EMA")
    if rsi > 50 and rsi < 68:
        score+=1; reasons.append(f"RSI {rsi:.0f} Bullish")
    elif 40 < rsi < 50 and rsi > rsi_calc_proper(closes[:-1],14):
        score+=1; reasons.append(f"RSI Improving {rsi:.0f}")
    if macd>0 and macd>macd_prev: score+=1; reasons.append("MACD Rising")
    elif macd>0: score+=0.5; reasons.append("MACD +")
    if vol>vol_avg*1.5 and closes[-1] > closes[-2]: score+=2; reasons.append(f"Vol Buy {vol/vol_avg:.1f}x")
    elif vol>vol_avg*1.5: score+=0.5; reasons.append(f"Vol High {vol/vol_avg:.1f}x")
    atr = atr_calc_proper(closed_bars, 14)
    if atr == 0: atr = (max(highs[-14:])-min(lows[-14:]))/14
    atr_distance = atr * 1.8
    min_distance = c * 0.02
    stop_distance = max(atr_distance, min_distance)
    stop = c - stop_distance
    tp1 = c + (stop_distance * 1.0)
    tp2 = c + (stop_distance * 1.618)
    tp3 = c + (stop_distance * 2.618)
    target = tp2
    risk_amt = CAPITAL * (RISK_PERCENT/100)
    qty_by_risk = risk_amt / stop_distance if stop_distance>0 else 0
    max_cost = CAPITAL * MAX_POSITION_PCT
    qty_by_capital = max_cost / (c * (1+FEE_PCT)) if c>0 else 1
    qty = min(qty_by_risk, qty_by_capital)
    position_value = qty * c
    return {"score": score, "reasons": reasons, "price": c, "stop": stop, "tp1": tp1, "tp2": tp2, "tp3": tp3, "qty": qty, "position_value": position_value, "atr": atr, "stop_dist": stop_distance}

async def start(update, context):
    await update.message.reply_text("Diamond Bot V2 Fixed Ready\n/analysis BTC\n/scan\n/news")

async def news_cmd(update, context):
    try:
        fg_val, fg_txt = get_fear_greed()
        news = get_news()
        msg = f"Fear & Greed: {fg_val} - {fg_txt}\n"
        if fg_val>=75: msg+="High greed - caution\n\n"
        elif fg_val<=25: msg+="High fear - opportunity\n\n"
        else: msg+="Neutral market\n\n"
        if news:
            msg+="Top news:\n"
            for n in news: msg+=f"- {n['title'][:90]}\n"
        else: msg+="News unavailable"
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"News error: {e}")

async def analysis_cmd(update, context):
    sym="BTC/USDT"
    if context.args: sym=f"{context.args[0].upper()}/USDT"
    await update.message.reply_text(f"Analyzing {sym}...")
    try:
        fg_val, fg_txt = get_fear_greed()
        d = await asyncio.to_thread(analyze, sym)
        status="GOLDEN" if d['score']>=5 else "GOOD" if d['score']>=4 else "WATCH" if d['score']>=2 else "WAIT"
        stop_pct = abs(d['price']-d['stop'])/d['price']*100
        txt=(f"{sym} | {TIMEFRAME} (Closed)\nPrice: {