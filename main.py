import os
import threading
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")

app_flask = Flask(__name__)

@app_flask.route('/')
def home():
    return "Bot is Alive!"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ البوت اشتغل! أهلا وسهلا أحمد")

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host='0.0.0.0', port=port)

def main():
    # شغل موقع وهمي مشان Render ما يطفي البوت
    threading.Thread(target=run_flask, daemon=True).start()
    
    # شغل بوت التليجرام
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    print("Bot starting...")
    application.run_polling()

if __name__ == '__main__':
    main()