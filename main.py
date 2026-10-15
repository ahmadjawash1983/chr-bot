import os
import requests
import numpy as np
import telebot
from datetime import datetime

BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)

FEE = 0.001 # 0.1% بينانس سبوت
RISK_PCT = 0.01 # 1% من الرصيد لكل صفقة

# ============ المؤشرات المصححة 100% ============

def get_klines(symbol="BTCUSDT", interval="4h", limit=200):
    """جيب شموع مغلقة فقط - نستبعد الشمعة المفتوحة"""
    symbol = symbol.upper().strip()
    if "USDT" not in symbol:
        symbol += "USDT"

    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        r = requests.get(url, timeout=10).json()
        if isinstance(r, dict) and "msg" in r:
            return None, f"الرمز {symbol} غير موجود"
        # r = [[open_time, open, high, low, close,...]]
        closes = [float(x[4]) for x in r]
        # استبعاد الشمعة المفتوحة - اهم تصليح
        closes = closes[:-1]
        return closes, symbol
    except Exception as e:
        return None, str(e)

def ema(prices, period):
    if len(prices) < period:
        return None
    k = 2 / (period + 1)
    ema_val = sum(prices[:period]) / period
    for price in prices[period:]:
        ema_val = price * k + ema_val * (1 - k)
    return ema_val

def ema_series(prices, period):
    """سلسلة EMA كاملة"""
    if len(prices) < period:
        return [None]*len(prices)
    k = 2 / (period + 1)
    series = []
    ema_val = sum(prices[:period]) / period
    for i in range(len(prices)):
        if i < period-1:
            series.append(None)
        elif i == period-1:
            series.append(ema_val)
        else:
            ema_val = prices[i] * k + ema_val * (1 - k)
            series.append(ema_val)
    return series

def rsi_calc_proper(prices, period=14):
    """RSI مصحح بطريقة Wilder الصحيحة"""
    if len(prices) < period + 1:
        return 50.0
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)

def macd_calc_proper(prices):
    """MACD حسب توثيق TradingView الرسمي"""
    if len(prices) < 35:
        return None
    ema12 = ema_series(prices, 12)
    ema26 = ema_series(prices, 26)

    macd_line = []
    for i in range(len(prices)):
        if ema12[i] is None or ema26[i] is None:
            macd_line.append(None)
        else:
            macd_line.append(ema12[i] - ema26[i])

    # فلترة None
    macd_clean = [x for x in macd_line if x is not None]
    if len(macd_clean) < 9:
        return None

    # Signal = EMA9 لـ MACD
    signal_series = ema_series(macd_clean, 9)
    macd_val = macd_clean[-1]
    signal_val = signal_series[-1]

    if signal_val is None:
        return None

    histogram = macd_val - signal_val
    return {
        "macd": round(macd_val, 4),
        "signal": round(signal_val, 4),
        "hist": round(histogram, 4),
        "bullish": histogram > 0
    }

def atr_calc(prices, period=14):
    if len(prices) < period + 1:
        return None
    trs = [abs(prices[i] - prices[i-1]) for i in range(1, len(prices))]
    return sum(trs[-period:]) / period

# ============ إدارة المخاطر المصححة مع الرسوم ============

def calc_trade_levels(price, atr, balance=1000):
    # ستوب ديناميكي مع حد أدنى 2% + رسوم
    stop_dist = max(1.8 * atr, price * 0.02)
    stop_price = price - stop_dist

    # الخسارة الحقيقية = المسافة + رسوم دخول وخروج
    real_risk_per_unit = (price - stop_price) + (price * FEE * 2)
    risk_amount = balance * RISK_PCT
    qty = risk_amount / real_risk_per_unit if real_risk_per_unit > 0 else 0

    risk = price - stop_price
    tp1 = price + risk * 1.0 # 38.2% - بيع 40%
    tp2 = price + risk * 1.618 # 61.8% - بيع 30%
    tp3 = price + risk * 2.618 # 100% - بيع 30%

    return {
        "stop": round(stop_price, 4),
        "tp1": round(tp1, 4),
        "tp2": round(tp2, 4),
        "tp3": round(tp3, 4),
        "qty": round(qty, 4),
        "real_risk_pct": round((real_risk_per_unit/price)*100, 2)
    }

# ============ التحليل ============

def analyze_symbol(symbol_input):
    closes, res = get_klines(symbol_input)
    if closes is None:
        return f"❌ خطأ: {res}"

    symbol = res
    price = closes[-1]
    rsi = rsi_calc_proper(closes)
    macd = macd_calc_proper(closes)
    atr = atr_calc(closes)

    if not macd or not atr:
        return "❌ بيانات غير كافية"

    levels = calc_trade_levels(price, atr)

    # تقييم GOLDEN بشروط صارمة
    score = 0
    if 45 < rsi < 60: score += 1
    if macd["bullish"]: score += 1
    if macd["hist"] > 0 and macd["macd"] > macd["signal"]: score += 1
    if price > ema(closes, 50): score += 1

    if score >= 4:
        grade = "GOLDEN 🔥"
    elif score == 3:
        grade = "GOOD 👍"
    else:
        grade = "WEAK ⚠️"

    msg = f"""📊 {symbol} - 4H (شموع مغلقة فقط)
السعر: {price}
RSI (Wilder): {rsi}
MACD: {macd['macd']} | Signal: {macd['signal']} | Hist: {macd['hist']} {'📈' if macd['bullish'] else '📉'}
ATR: {round(atr,4)}

التقييم: {grade} ({score}/4)

🛡️ إدارة مخاطر مع رسوم 0.2%:
ستوب: {levels['stop']} (خسارة حقيقية {levels['real_risk_pct']}%)
TP1 (40%): {levels['tp1']} = 1R
TP2 (30%): {levels['tp2']} = 1.618R
TP3 (30%): {levels['tp3']} = 2.618R
الكمية لرصيد 1000$: {levels['qty']}
"""
    return msg

# ============ أوامر البوت ============

@bot.message_handler(commands=['analysis', 'a'])
def handle_analysis(message):
    try:
        parts = message.text.split()
        symbol = parts[1] if len(parts) > 1 else "BTCUSDT"
        bot.send_message(message.chat.id, "⏳ جاري التحليل (بدون الشمعة المفتوحة)...")
        result = analyze_symbol(symbol)
        bot.send_message(message.chat.id, result)
    except Exception as e:
        bot.send_message(message.chat.id, f"خطأ: {e}")

@bot.message_handler(commands=['scan'])
def handle_scan(message):
    coins = ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","ADAUSDT","AVAXUSDT","DOGEUSDT","LINKUSDT","CHRUSDT"]
    bot.send_message(message.chat.id, "🔍 فحص 10 عملات...")
    for c in coins:
        res = analyze_symbol(c)
        if "GOLDEN" in res:
            bot.send_message(message.chat.id, res)

@bot.message_handler(commands=['backtest'])
def handle_backtest(message):
    parts = message.text.split()
    symbol = parts[1] if len(parts) > 1 else "BTCUSDT"
    closes, _ = get_klines(symbol, limit=300)
    if not closes:
        bot.send_message(message.chat.id, "خطأ بالرمز")
        return

    wins = 0
    total = 0
    pnl = 0
    for i in range(100, len(closes)-20):
        slice_prices = closes[:i]
        rsi = rsi_calc_proper(slice_prices)
        macd = macd_calc_proper(slice_prices)
        if not macd: continue
        if 45 < rsi < 60 and macd["bullish"]:
            total += 1
            entry = slice_prices[-1]
            atr = atr_calc(slice_prices)
            if not atr: continue
            tp = entry + (max(1.8*atr, entry*0.02) * 1.618)
            sl = entry - max(1.8*atr, entry*0.02)
            # تحقق بعد 10 شموع مع رسوم
            future = closes[i:i+10]
            if not future: continue
            max_p = max(future)
            min_p = min(future)
            if max_p >= tp:
                wins += 1
                pnl += (tp - entry)/entry - FEE*2
            elif min_p <= sl:
                pnl -= (entry - sl)/entry + FEE*2

    winrate = (wins/total*100) if total>0 else 0
    bot.send_message(message.chat.id, f"📈 باكتيست {symbol} (مع رسوم 0.2%):\nصفقات GOLDEN: {total}\nنجاح: {wins}\nنسبة نجاح: {round(winrate,1)}%\nصافي ربح تراكمي: {round(pnl*100,2)}%")

@bot.message_handler(commands=['start','help'])
def handle_start(message):
    bot.send_message(message.chat.id, "Diamond Bot V5 ✅\n/analysis BTC\n/scan\n/backtest CHR\n\nكل الحسابات: شموع مغلقة فقط + Wilder RSI + TradingView MACD + رسوم")

print("Bot V5 running...")
bot.infinity_polling()