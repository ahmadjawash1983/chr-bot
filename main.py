import os, threading, requests, ccxt, pandas as pd
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")
TIMEFRAME = "30m"
CAPITAL = 400
RISK_PERCENT = 1.5
TOP_20_COINS = ["BTC/USDT","ETH/USDT","SOL/USDT","BNB/USDT","XRP/USDT","DOGE/USDT","ADA/USDT","AVAX/USDT","SHIB/USDT","DOT/USDT","LINK/USDT","TRX/USDT","MATIC/USDT","LTC/USDT","BCH/USDT","NEAR/USDT","UNI/USDT","PEPE/USDT","ETC/USDT","APT/USDT"]

app_flask = Flask(__name__)
exchange = ccxt.binance()

@app_flask.route('/')
def home(): return "Diamond Bot Live - Fixed Version - 400$"

def calc_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def calc_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/period, adjust=False).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calc_atr(h, l, c, period=14):
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()

def analyze_symbol(symbol):
    bars = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=200)
    df = pd.DataFrame(bars, columns=['t','o','h','l','c','v'])
    df['ema50'] = calc_ema(df['c'], 50)
    df['ema200'] = calc_ema(df['c'], 200)
    df['rsi'] = calc_rsi(df['c'], 14)
    df['atr'] = calc_atr(df['h'], df['l'], df['c'], 14)
    # MACD simple
    ema12 = calc_ema(df['c'], 12)
    ema26 = calc_ema(df['c'], 26)
    df['macd'] = ema12 - ema26
    df['signal'] = calc_ema(df['macd'], 9)

    last = df.iloc[-1]
    vol_avg = df['v'].rolling(20).mean().iloc[-1]

    score = 0
    reasons = []
    if last['c'] > last['ema50'] > last['ema200']:
        score+=2; reasons.append("ترند صاعد")
    if 30 < last['rsi'] < 50:
        score+=1; reasons.append(f"RSI {last['rsi']:.0f}")
    if last['macd'] > last['signal']:
        score+=1; reasons.append("MACD صاعد")
    if last['v'] > vol_avg * 1.5:
        score+=2; reasons.append(f"حجم {last['v']/vol_avg:.1f}x")
    if last['c'] < last['o']*0.99: # مثال Pin
        score+=1

    stop = last['l'] - last['atr']*1.5
    risk_amount = CAPITAL * (RISK_PERCENT/100)
    risk_per_coin = last['c'] - stop
    qty = risk_amount / risk_per_coin if risk_per_coin>0 else 0
    t2 = last['c'] + last['atr']*3
    return score, reasons, last, stop, t2, qty, vol_avg

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"💎 بوت الماس شغال!\nرأس مال {CAPITAL}$\nفريم {TIMEFRAME}\n/analysis BTC\n/scan")

async def analysis_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbol = "BTC/USDT"
    if context.args: symbol = f"{context.args[0].upper()}/USDT"
    await update.message.reply_text(f"⏳ عم حلل {symbol}...")
    try:
        score, reasons, last, stop, t2, qty, vol_avg = analyze_symbol(symbol)
        msg = f"📊 {symbol} | {TIMEFRAME}\nسعر: {last['c']}\nنتيجة: {score}/6\nأسباب: {' + '.join(reasons)}\nستوب: {stop:.4f}\nهدف: {t2:.4f}\nكمية: {qty:.4f}\n{'🟢 ذهبية' if score>=5 else '⚪ انتظار'}"
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"خطأ: {e}")

async def scan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🔍 بفحص {len(TOP_20_COINS)} عملة...")
    found=0
    for sym in TOP_20_COINS:
        try:
            score, reasons, last, stop, t2, qty, vol_avg = analyze_symbol(sym)
            if score >=5:
                found+=1
                await update.message.reply_text(f"🟢 {sym} | {score}/6 | {' + '.join(reasons)}\nسعر {last['c']:.4f} ستوب {stop:.4f}")
        except: continue
    if found==0: await update.message.reply_text("لا يوجد فرص ذهبية حالياً")

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host='0.0.0.0', port=port)

def main():
    threading.Thread(target=run_flask, daemon=True).start()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("analysis", analysis_cmd))
    app.add_handler(CommandHandler("price", analysis_cmd))
    app.add_handler(CommandHandler("scan", scan_cmd))
    print("Diamond Bot Fixed Started")
    app.run_polling()

if __name__ == '__main__': main()