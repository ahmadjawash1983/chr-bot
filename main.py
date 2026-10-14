import os, threading
from flask import Flask
import ccxt, pandas as pd
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

flask_app = Flask(__name__)
@flask_app.route('/')
def home(): return "BOT LIVE"
threading.Thread(target=lambda: flask_app.run(host="0.0.0.0", port=int(os.getenv("PORT",10000))), daemon=True).start()

exchange = ccxt.kucoin()

def analyze(symbol):
    bars = exchange.fetch_ohlcv(symbol,'30m',limit=100)
    df = pd.DataFrame(bars, columns=['t','o','h','l','c','v'])
    return float(df['c'].iloc[-1])

async def analysis_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Price {analyze('BTC/USDT'):.2f} ✅ LIVE")

async def scan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Scan LIVE ✅")

if __name__ == "__main__":
    app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()
    app.add_handler(CommandHandler("analysis", analysis_cmd))
    app.add_handler(CommandHandler("scan", scan_cmd))
    print("BOT STARTED")
    app.run_polling()