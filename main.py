import ccxt, pandas as pd, os
from threading import Thread
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

CAPITAL = 400
TIMEFRAME = '30m'
COINS = ['BTC/USDT','ETH/USDT','SOL/USDT','BNB/USDT','XRP/USDT','ADA/USDT','DOGE/USDT','AVAX/USDT','DOT/USDT','LINK/USDT']

exchange = ccxt.kucoin()
ALERT_CHAT_ID = None

# Keep Alive for Render
app_flask = Flask('')
@app_flask.route('/')
def home(): return "BOT ALIVE V3.2"
def run_flask():
    app_flask.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
def keep_alive():
    Thread(target=run_flask, daemon=True).start()

def analyze(symbol):
    bars = exchange.fetch_ohlcv(symbol, TIMEFRAME, limit=100)
    df = pd.DataFrame(bars, columns=['t','o','h','l','c','v'])
    close = df['c']
    price = float(close.iloc[-1])
    ema20 = close.ewm(span=20).mean().iloc[-1]
    ema50 = close.ewm(span=50).mean().iloc[-1]
    rsi = 50
    try:
        delta = close.diff()
        gain = delta.where(delta>0,0).ewm(span=14).mean()
        loss = -delta.where(delta<0,0).ewm(span=14).mean()
        rs = gain.iloc[-1] / (loss.iloc[-1] + 1e-9)
        rsi = 100 - (100/(1+rs))
    except: pass
    score = 0
    reasons = []
    if price > ema20 > ema50:
        score+=1; reasons.append("EMA UP")
    if 40 <= rsi <= 60:
        score+=1; reasons.append(f"RSI {rsi:.0f}")
    if close.iloc[-1] > close.iloc[-20]:
        score+=1; reasons.append("Trend UP")
    status = "GOLDEN BUY 🔥" if score >=2 else "WAIT"
    return price, score, reasons, status

async def analysis_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ALERT_CHAT_ID
    ALERT_CHAT_ID = update.effective_chat.id
    symbol = "BTC/USDT"
    if context.args:
        a = context.args[0].upper()
        symbol = a + "/USDT" if "/" not in a else a
    await update.message.reply_text(f"Analyzing {symbol}...")
    try:
        price, score, reasons, status = analyze(symbol)
        await update.message.reply_text(f"{symbol} | {TIMEFRAME}\nPrice {price:.2f}\nScore {score}/3 - {', '.join(reasons)}\n{status}\n\nAuto Alert ON ✅")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def scan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ALERT_CHAT_ID
    ALERT_CHAT_ID = update.effective_chat.id
    await update.message.reply_text(f"🚀 Scanning {len(COINS)} coins... رح ابعتلك النتيجة بعد 15 ثانية")
    found=[]
    for s in COINS:
        try:
            price, score, reasons, status = analyze(s)
            if score>=2:
                found.append(f"{status}: {s} {price:.2f} Score {score}")
        except: pass
    if found:
        await update.message.reply_text("\n\n".join(found))
    else:
        await update.message.reply_text("No golden now. رح افحص كل 30 دقيقة تلقائي 🔔")

async def auto_scan_job(context: ContextTypes.DEFAULT_TYPE):
    if not ALERT_CHAT_ID: return
    for s in COINS:
        try:
            price, score, reasons, status = analyze(s)
            if score>=2:
                await context.bot.send_message(chat_id=ALERT_CHAT_ID, text=f"🚨 GOLDEN {s} Price {price:.2f} Score {score}")
        except: pass

if __name__ == "__main__":
    keep_alive()
    TOKEN = os.getenv("BOT_TOKEN")
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("analysis", analysis_cmd))
    app.add_handler(CommandHandler("scan", scan_cmd))
    app.job_queue.run_repeating(auto_scan_job, interval=1800, first=60)
    print("BOT STARTED V3.2")
    app.run_polling()