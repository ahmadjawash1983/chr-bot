import ccxt
import pandas as pd
import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

exchange = ccxt.kucoin()

COINS = ['BTC/USDT','ETH/USDT','SOL/USDT','BNB/USDT','XRP/USDT','ADA/USDT','DOGE/USDT','AVAX/USDT','DOT/USDT','LINK/USDT']

def analyze(symbol):
    bars = exchange.fetch_ohlcv(symbol, '30m', limit=100)
    df = pd.DataFrame(bars, columns=['t','o','h','l','c','v'])
    close = df['c']
    price = float(close.iloc[-1])
    ema20 = close.ewm(span=20).mean().iloc[-1]
    ema50 = close.ewm(span=50).mean().iloc[-1]
    rsi = 50
    try:
        delta = close.diff()
        gain = delta.where(delta > 0, 0).ewm(span=14).mean()
        loss = -delta.where(delta < 0, 0).ewm(span=14).mean()
        rs = gain.iloc[-1] / (loss.iloc[-1] + 1e-9)
        rsi = 100 - (100 / (1 + rs))
    except:
        pass

    score = 0
    reasons = []
    if price > ema20 > ema50:
        score += 1
        reasons.append("EMA UP")
    if 40 <= rsi <= 60:
        score += 1
        reasons.append(f"RSI {rsi:.0f}")
    if close.iloc[-1] > close.iloc[-20]:
        score += 1
        reasons.append("Trend UP")

    status = "GOLDEN BUY" if score >= 2 else "WAIT"
    return price, score, reasons, status

async def analysis_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbol = "BTC/USDT"
    if context.args:
        arg = context.args[0].upper()
        symbol = arg + "/USDT" if "/" not in arg else arg
    await update.message.reply_text(f"Analyzing {symbol}...")
    try:
        price, score, reasons, status = analyze(symbol)
        await update.message.reply_text(f"{symbol}\nPrice {price:.2f}\nScore {score}/3 - {', '.join(reasons)}\n{status}")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def scan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Scanning {len(COINS)} coins...")
    found = []
    checked = 0
    for s in COINS:
        try:
            price, score, reasons, status = analyze(s)
            checked += 1
            if score >= 1:
                found.append(f"{s}: {price:.2f} | Score {score} | {', '.join(reasons)}")
        except:
            continue
    if found:
        await update.message.reply_text("\n\n".join(found))
    else:
        await update.message.reply_text(f"Checked {checked} coins, no GOLDEN now.")

if __name__ == "__main__":
    TOKEN = os.getenv("BOT_TOKEN")
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("analysis", analysis_cmd))
    app.add_handler(CommandHandler("scan", scan_cmd))
    print("BOT STARTED")
    app.run_polling()