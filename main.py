import ccxt
import pandas as pd
import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

exchange = ccxt.kucoin()

def analyze(symbol):
    bars = exchange.fetch_ohlcv(symbol, '30m', limit=100)
    df = pd.DataFrame(bars, columns=['t','o','h','l','c','v'])
    price = float(df['c'].iloc[-1])
    return price

async def analysis_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbol = "BTC/USDT"
    if context.args:
        arg = context.args[0].upper()
        symbol = arg + "/USDT" if "/" not in arg else arg

    await update.message.reply_text(f"🔍 عم حلل {symbol}...")
    try:
        price = analyze(symbol)
        await update.message.reply_text(f"{symbol} Price: {price} ✅\nBot LIVE")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def scan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Scan manual ready ✅\nاستخدم /analysis BTC")

if __name__ == "__main__":
    TOKEN = os.getenv("BOT_TOKEN")
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("analysis", analysis_cmd))
    app.add_handler(CommandHandler("scan", scan_cmd))
    print("BOT STARTED - LAST WORKING VERSION")
    app.run_polling()