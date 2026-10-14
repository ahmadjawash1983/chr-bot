import os
import time
import threading
import requests
import ccxt
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
exchange = ccxt.kucoin()

@app_flask.route('/')
def home():
    return "Diamond Bot Live - News + Fear"

def get_fear_greed():
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=5).json()
        val = int(r['data'][0]['value'])
        txt = r['data'][0]['value_classification']
        return val, txt
    except:
        return 50, "Unknown"

def get_news():
    try:
        r = requests.get("https://min-api.cryptocompare.com/data/v2/news/?lang=EN", timeout=5).json()
        news = r['Data'][:3]
        return news
    except:
        return []

def ema_calc(prices, period):
    k = 2 / (period + 1)
    ema = prices[0]
    for p in prices[1:]:
        ema = p * k + ema * (1 - k)
    return ema

def rsi_calc(prices, period=14):
    gains, losses = 0, 0
    for i in range(1, period+1):
        d = prices[-i] - prices[-i-1]
        if d > 0: gains += d
        else: losses -= d
    if losses == 0: return 70
    rs = (gains/period) / (losses/period)
    return 100 - (100 / (1 + rs))

def analyze(symbol):
    bars = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=200)
    closes = [b[4] for b in bars]
    highs = [b[2] for b in bars]
    lows = [b[3] for b in bars]
    vols = [b[5] for b in bars]
    c = closes[-1]
    ema50 = ema_calc(closes[-50:], 50)
    ema200 = ema_calc(closes[-200:], 200)
    rsi = rsi_calc(closes, 14)
    e12 = ema_calc(closes[-12:], 12)
    e26 = ema_calc(closes[-26:], 26)
    macd = e12 - e26
    vol_avg = sum(vols[-20:]) / 20
    vol = vols[-1]
    score = 0
    reasons = []
    if c > ema50 and ema50 > ema200:
        score += 2
        reasons.append("Uptrend EMA")
    if 30 < rsi < 50:
        score += 1
        reasons.append(f"RSI {rsi:.0f}")
    if macd > 0:
        score += 1
        reasons.append("MACD Bullish")
    if vol > vol_avg * 1.5:
        score += 2
        reasons.append(f"Vol {vol/vol_avg:.1f}x")
    low = lows[-1]
    atr = (max(highs[-14:]) - min(lows[-14:])) / 14
    stop = low - atr * 1.5
    risk_amt = CAPITAL * (RISK_PERCENT / 100)
    risk_per_coin = c - stop if c > stop else atr
    qty = risk_amt / risk_per_coin if risk_per_coin > 0 else 0
    target = c + atr * 3
    return score, reasons, c, stop, target, qty

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Diamond Bot 400$ - News + Fear\n/scan\n/analysis BTC\n/news")

async def news_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("جاري جلب الاخبار...")
    fg_val, fg_txt = get_fear_greed()
    news = get_news()
    msg = f"📊 Fear & Greed: {fg_val} - {fg_txt}\n"
    if fg_val >= 75:
        msg += "⚠️ طمع عالي - لا تدخل حتى لو GOLDEN\n\n"
    elif fg_val <= 25:
        msg += "✅ خوف عالي - وقت ممتاز للشراء\n\n"
    else:
        msg += "➖ سوق متوازن\n\n"
    msg += "📰 اهم الاخبار:\n"
    for n in news:
        msg += f"- {n['title'][:80]}...\n"
    await update.message.reply_text(msg)

async def analysis_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sym = "BTC/USDT"
    if context.args:
        sym = f"{context.args[0].upper()}/USDT"
    await update.message.reply_text(f"Analyzing {sym}...")
    try:
        fg_val, fg_txt = get_fear_greed()
        score, reasons, c, stop, target, qty = analyze(sym)
        status = "GOLDEN" if score >=5 else "GOOD" if score >=4 else "WATCH" if score >=2 else "WAIT"
        if fg_val >= 85 and score >=5:
            status = f"{status} BUT FEAR {fg_val} TOO HIGH - WAIT"
        txt = f"{sym} | {TIMEFRAME}\nPrice: {c}\nF&G: {fg_val} ({fg_txt})\nScore: {score}/6\nReasons: {' + '.join(reasons) if reasons else 'None'}\nStop: {stop:.4f}\nTarget: {target:.4f}\nQty: {qty:.4f}\n{status}"
        await update.message.reply_text(txt)
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def scan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fg_val, fg_txt = get_fear_greed()
    await update.message.reply_text(f"Scanning {len(TOP_COINS)} coins...\nF&G: {fg_val} ({fg_txt})")
    found = 0
    for s in TOP_COINS:
        try:
            time.sleep(0.3)
            score, reasons, c, stop, target, qty = analyze(s)
            if score >= 5:
                if fg_val >= 85:
                    await update.message.reply_text(f"{s} Score {score} BUT SKIP - Greed {fg_val} too high")
                    continue
                found += 1
                await update.message.reply_text(f"GOLDEN: {s}\nScore {score}/6 - {' + '.join(reasons)}\nPrice {c:.4f}")
        except:
            continue
    if found == 0:
        await update.message.reply_text("No golden now.")

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host='0.0.0.0', port=port)

def main():
    if not TOKEN:
        print("BOT_TOKEN missing")
        return
    threading.Thread(target=run_flask, daemon=True).start()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("analysis", analysis_cmd))
    app.add_handler(CommandHandler("price", analysis_cmd))
    app.add_handler(CommandHandler("scan", scan_cmd))
    app.add_handler(CommandHandler("news", news_cmd))
    print("Bot Started")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()