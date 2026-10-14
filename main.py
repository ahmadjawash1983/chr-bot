import os, threading, requests, ccxt, pandas as pd
from flask import Flask
import pandas_ta as ta
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ========= الإعدادات - فيك تغيرها بأي وقت =========
TOKEN = os.getenv("BOT_TOKEN")
TIMEFRAME = "30m" # غيرها ل 5m / 15m / 1h / 4h
CAPITAL = 400 # رأس مالك
RISK_PERCENT = 1.5 # مخاطرة 1.5%
TOP_20_COINS = [
    "BTC/USDT","ETH/USDT","SOL/USDT","BNB/USDT","XRP/USDT",
    "DOGE/USDT","ADA/USDT","AVAX/USDT","SHIB/USDT","DOT/USDT",
    "LINK/USDT","TRX/USDT","MATIC/USDT","LTC/USDT","BCH/USDT",
    "NEAR/USDT","UNI/USDT","PEPE/USDT","ETC/USDT","APT/USDT"
]
# ===================================================

app_flask = Flask(__name__)
exchange = ccxt.binance()

@app_flask.route('/')
def home(): return "Diamond Bot Live - 400$ - 1.5% Risk"

def check_candle_pattern(df):
    last = df.iloc[-1]
    prev = df.iloc[-2]
    # ابتلاعية صاعدة
    if prev['c'] < prev['o'] and last['c'] > last['o'] and last['c'] > prev['o'] and last['o'] < prev['c']:
        return "ابتلاعية صاعدة ✅"
    # Pin Bar
    if (last['h'] - last['l']) > 2 * abs(last['c'] - last['o']) and (last['h'] - max(last['c'], last['o'])) < 0.3*(last['h']-last['l']):
        return "Pin Bar صاعد ✅"
    return "لا يوجد نموذج واضح"

def get_fear_greed():
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=5).json()
        return r['data'][0]['value'], r['data'][0]['value_classification']
    except: return "N/A", "N/A"

def analyze_symbol(symbol):
    bars = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=200)
    df = pd.DataFrame(bars, columns=['t','o','h','l','c','v'])

    # مؤشرات
    df['ema50'] = ta.ema(df['c'], 50)
    df['ema200'] = ta.ema(df['c'], 200)
    df['rsi'] = ta.rsi(df['c'], 14)
    df['atr'] = ta.atr(df['h'], df['l'], df['c'], 14)
    df['adx'] = ta.adx(df['h'], df['l'], df['c'], 14)['ADX_14']
    macd = ta.macd(df['c'])
    df = pd.concat([df, macd], axis=1)
    bb = ta.bbands(df['c'], length=20, std=2)
    df = pd.concat([df, bb], axis=1)

    last = df.iloc[-1]

    score = 0
    reasons = []

    # 1. ترند
    if last['c'] > last['ema50'] > last['ema200']:
        score+=2; reasons.append("ترند صاعد EMA")
    # 2. ADX
    if last['adx'] > 25:
        score+=1; reasons.append(f"ADX قوي {last['adx']:.0f}")
    # 3. RSI
    if 30 < last['rsi'] < 50:
        score+=1; reasons.append(f"RSI ارتداد {last['rsi']:.0f}")
    # 4. MACD
    if last['MACD_12_26_9'] > last['MACDs_12_26_9']:
        score+=1; reasons.append("MACD صاعد")
    # 5. حجم
    vol_avg = df['v'].rolling(20).mean().iloc[-1]
    if last['v'] > vol_avg * 1.5:
        score+=2; reasons.append(f"حجم عالي {last['v']/vol_avg:.1f}x")
    # 6. شموع
    pattern = check_candle_pattern(df)
    if "✅" in pattern:
        score+=1; reasons.append(pattern)
    # 7. Bollinger
    if last['c'] < last['BBL_20_2.0']:
        score+=1; reasons.append("لمس باند سفلي")

    # حساب ستوب وهدف على أساس 400$
    atr = last['atr']
    stop_price = last['l'] - atr*1.5
    risk_amount = CAPITAL * (RISK_PERCENT/100) # 6$
    risk_per_coin = (last['c'] - stop_price)
    qty = risk_amount / risk_per_coin if risk_per_coin >0 else 0
    target1 = last['c'] + atr*1.5
    target2 = last['c'] + atr*3

    return score, reasons, last, stop_price, target1, target2, qty

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"💎 بوت الماس Live\nرأس مال: {CAPITAL}$\nمخاطرة: {RISK_PERCENT}% = {CAPITAL*RISK_PERCENT/100}$\n"
        f"فريم: {TIMEFRAME}\nعدد العملات: {len(TOP_20_COINS)}\n\n"
        "الأوامر:\n/analysis BTC\n/scan - فحص كل العملات الـ20"
    )

async def analysis_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbol = "BTC/USDT"
    if context.args: symbol = f"{context.args[0].upper()}/USDT"
    await update.message.reply_text(f"⏳ عم حلل {symbol} على {TIMEFRAME}...")
    try:
        score, reasons, last, stop, t1, t2, qty = analyze_symbol(symbol)
        fg_val, fg_txt = get_fear_greed()
        msg = (f"📊 {symbol} | {TIMEFRAME}\n"
               f"السعر: {last['c']:.4f}\n"
               f"النتيجة: {score}/9\n"
               f"الأسباب: {' + '.join(reasons)}\n\n"
               f"ATR: {last['atr']:.4f}\n"
               f"ستوب: {stop:.4f}\n"
               f"هدف1: {t1:.4f} | هدف2: {t2:.4f}\n\n"
               f"الكمية المقترحة لرأس مال {CAPITAL}$: {qty:.4f} عملة\n"
               f"مخاطرة: {CAPITAL*RISK_PERCENT/100}$\n\n"
               f"مؤشر الخوف: {fg_val} - {fg_txt}\n\n"
               f"{'🟢 فرصة ذهبية' if score>=7 else '⚪ انتظار - لا تدخل'}")
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"خطأ: {e}")

async def scan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🔍 بدأ فحص {len(TOP_20_COINS)} عملة... رح ياخد دقيقة")
    found = 0
    for sym in TOP_20_COINS:
        try:
            score, reasons, last, stop, t1, t2, qty = analyze_symbol(sym)
            if score >= 7:
                found+=1
                await update.message.reply_text(
                    f"🟢 فرصة ذهبية: {sym}\n"
                    f"نتيجة: {score}/9 - {' + '.join(reasons)}\n"
                    f"سعر: {last['c']:.4f} | ستوب: {stop:.4f}\n"
                    f"هدف: {t2:.4f} | كمية: {qty:.4f}"
                )
        except: continue
    if found==0:
        await update.message.reply_text("لا يوجد فرص ذهبية حالياً 7/9 على فريم 30m. السوق عرضي.")

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
    print("Diamond Bot Started")
    app.run_polling()

if __name__ == '__main__': main()