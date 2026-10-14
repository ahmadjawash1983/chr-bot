import os, threading
from flask import Flask
import ccxt
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# حل رقم 2 و 3 و 4 - Port
flask_app = Flask(__name__)
@flask_app.route('/')
def home(): return "BOT LIVE"
def run_flask():
    flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
threading.Thread(target=run_flask, daemon=True).start()

# حل رقم 5 - ApplicationBuilder بدل Updater القديم
exchange = ccxt.kucoin()

async def analysis_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        symbol = "BTC/USDT"
        if context.args:
            a = context.args[0].upper()
            symbol = a + "/USDT" if "/" not in a else a
        ticker = exchange.fetch_ticker(symbol)
        await update.message.reply_text(f"{symbol} Price: {ticker['last']} ✅ LIVE")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def scan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Scan LIVE ✅")

if __name__ == "__main__":
    TOKEN = os.getenv("BOT_TOKEN")
    print("BOT STARTING...")
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("analysis", analysis_cmd))
    app.add_handler(CommandHandler("scan", scan_cmd))
    app.run_polling(drop_pending_updates=True)