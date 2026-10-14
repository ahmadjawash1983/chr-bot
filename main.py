import os, threading
from flask import Flask
import ccxt
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

flask_app = Flask(__name__)
@flask_app.route('/')
def home(): return "BOT LIVE"
def run_flask():
    flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
threading.Thread(target=run_flask, daemon=True).start()

exchange = ccxt.kucoin()
async def analysis_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        s = "BTC/USDT"
        if context.args:
            a = context.args[0].upper()
            s = a + "/USDT" if "/" not in a else a
        t = exchange.fetch_ticker(s)
        await update.message.reply_text(f"{s} Price: {t['last']} ✅ LIVE")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def scan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Scan LIVE ✅")

if __name__ == "__main__":
    print("BOT STARTING...")
    app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()
    app.add_handler(CommandHandler("analysis", analysis_cmd))
    app.add_handler(CommandHandler("scan", scan_cmd))
    app.run_polling(drop_pending_updates=True)