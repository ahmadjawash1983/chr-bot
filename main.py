import ccxt
import pandas as pd
import os
import asyncio
from threading import Thread
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- الاعدادات الماسية ---
CAPITAL = 400
RISK_PCT = 1.5
TIMEFRAME = '30m'
COINS = ['BTC/USDT','ETH/USDT','SOL/USDT','BNB/USDT','XRP/USDT','ADA/USDT','DOGE/USDT','AVAX/USDT','DOT/USDT','LINK/USDT','MATIC/USDT','LTC/USDT','TRX/USDT','SHIB/USDT','UNI/USDT','ATOM/USDT','ETC/USDT','XLM/USDT','NEAR/USDT','ARB/USDT']

exchange = ccxt.kucoin()
ALERT_CHAT_ID = None # رح ينحفظ تلقائي أول ما تبعت أي أمر

# --- كيب ألايف مشان Render ما ينام ---
flask_app = Flask('')
@flask_app.route('/')
def home(): return "Bot is ALIVE - Diamond V3"
def run_flask():
    flask_app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
def keep_alive():
    Thread(target=run_flask, daemon=True).start()

# --- التحليل ---
def analyze(symbol):
    bars = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=100)
    df = pd.DataFrame(bars, columns=['t','o','h','l','c','v'])
    close = df['c']
    price = float(close.iloc[-1])
    ema20 = close.ewm(span=20).mean().iloc[-1]
    ema50 = close.ewm(span=50).mean().iloc[-1]
    delta = close.diff()
    gain = delta.where(delta>0,0).ewm(span=14).mean()
    loss = -delta.where(delta<0,0).ewm(span=14).mean()
    rs = gain.iloc[-1] / (loss.iloc[-1] + 1e-9)
    rsi = 100 - (100/(1+rs))
    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    macd = ema12 - ema26
    macd_signal = macd.ewm(span=9).mean()
    vol_avg = df['v'].rolling(20).mean().iloc[-1]
    vol_now = df['v'].iloc[-1]
    vol_ratio = vol_now / (vol_avg + 1e-9)
    reasons = []
    score = 0
    if price > ema20 > ema50:
        score+=1; reasons.append("EMA Uptrend")
    if 40 <= rsi <= 60:
        score+=1; reasons.append(f"RSI {rsi:.1f}")
    if macd.iloc[-1] > macd_signal.iloc[-1]:
        score+=1; reasons.append("MACD Bull")
    if vol_ratio > 1.2:
        score+=1; reasons.append(f"Vol {vol_ratio:.1f}x")
    if close.iloc[-1] > close.iloc[-20]:
        score+=1; reasons.append("Trend Up")
    low20 = df['l'].rolling(20).min().iloc[-1]
    if price > low20 * 1.02:
        score+=1; reasons.append("Above support")
    risk_usd = CAPITAL * RISK_PCT / 100
    stop_dist = price * 0.0042
    stop = price - stop_dist
    target = price + stop_dist * 2
    qty = risk_usd / stop_dist if stop_dist>0 else 0
    status = "GOLDEN BUY 🔥" if score >=4 else "WAIT"
    return price, score, reasons, stop, target, qty, status

# --- أوامر التيليجرام ---
async def analysis_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ALERT_CHAT_ID
    ALERT_CHAT_ID = update.effective_chat.id
    symbol = "BTC/USDT"
    if context.args:
        a = context.args[0].upper()
        symbol = a + "/USDT" if "/" not in a else a
    await update.message.reply_text(f"Analyzing {symbol}...")
    try:
        price, score, reasons, stop, target, qty, status = analyze(symbol)
        txt = f"{symbol} | {TIMEFRAME}\nPrice: {price:.2f}\nScore: {score}/6\nReasons: {', '.join(reasons)}\nStop: {stop:.4f}\nTarget: {target:.4f}\nQty: {qty:.4f}\n{status}\n\nAuto scan ON ✅ كل 30 دقيقة"
        await update.message.reply_text(txt)
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def scan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ALERT_CHAT_ID
    ALERT_CHAT_ID = update.effective_chat.id
    await update.message.reply_text(f"Scanning {len(COINS)} coins... Auto ALERT ON")
    found = []
    for s in COINS:
        try:
            price, score, reasons, stop, target, qty, status = analyze(s)
            if score >=4:
                found.append(f"{status}: {s} | Score {score}/6 | Price {price:.2f}")
        except: pass
    if found:
        await update.message.reply_text("\n\n".join(found))
    else:
        await update.message.reply_text("No golden now. رح أفحص تلقائي كل 30 دقيقة وأبعتلك بس اذا لقيت GOLDEN 🔔")

# --- السكان التلقائي كل 30 دقيقة ---
async def auto_scan_job(context: ContextTypes.DEFAULT_TYPE):
    global ALERT_CHAT_ID
    if not ALERT_CHAT_ID: return
    found = []
    for s in COINS:
        try:
            price, score, reasons, stop, target, qty, status = analyze(s)
            if score >=4:
                found.append(f"🚨 GOLDEN FOUND 🔥\n{s} | Score {score}/6\nPrice {price:.2f}\nReasons: {', '.join(reasons)}\nStop {stop:.2f} Target {target:.2f}\nQty {qty:.4f}")
        except: pass
    if found:
        for msg in found:
            await context.bot.send_message(chat_id=ALERT_CHAT_ID, text=msg)

if __name__ == "__main__":
    keep_alive()
    TOKEN = os.getenv("BOT_TOKEN")
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("analysis", analysis_cmd))
    app.add_handler(CommandHandler("scan", scan_cmd))
    # كل 30 دقيقة = 1800 ثانية
    app.job_queue.run_repeating(auto_scan_job, interval=1800, first=60)
    app.run_polling()