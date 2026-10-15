import os, threading, requests, ccxt, asyncio
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")
TIMEFRAME = "30m"
CAPITAL = 400
RISK_PERCENT = 1.5
MAX_POSITION_PCT = 0.95
FEE_PCT = 0.001

TOP_COINS = ["BTC/USDT","ETH/USDT","SOL/USDT","HNT/USDT","XRP/USDT","ARKM/USDT","ADA/USDT","AVAX/USDT","ONE/USDT","DOT/USDT","LINK/USDT","TRX/USDT","MATIC/USDT","POND/USDT","BCH/USDT","NEAR/USDT","CHR/USDT","TİA/USDT","ZRO/USDT","APT/USDT"]

app_flask = Flask(__name__)
exchange = ccxt.kucoin()

@app_flask.route('/')
def home():
    return "Diamond Bot Live V3 - All Fixed"

def get_fear_greed():
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10).json()
        return int(r['data'][0]['value']), r['data'][0]['value_classification']
    except:
        return 50, "Unknown"

def get_news():
    try:
        r = requests.get("https://min-api.cryptocompare.com/data/v2/news/?lang=EN", timeout=10).json()
        return r['Data'][:3]
    except:
        return []

def ema_calc_proper(prices, period):
    if len(prices) < period: return sum(prices)/len(prices)
    ema = sum(prices[:period]) / period
    k = 2 / (period + 1)
    for p in prices[period:]:
        ema = p*k + ema*(1-k)
    return ema

def rsi_calc_proper(prices, period=14):
    if len(prices) < period + 1: return 50
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains = [max(d, 0) for d in deltas[-period:]]
    losses = [abs(min(d, 0)) for d in deltas[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0: return 100 if avg_gain > 0 else 50
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain*(period-1) + max(deltas[i],0)) / period
        avg_loss = (avg_loss*(period-1) + abs(min(deltas[i],0))) / period
    if avg_loss == 0: return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def atr_calc_proper(bars, period=14):
    if len(bars) < period+1: return 0
    trs = []
    for i in range(1, len(bars)):
        high = bars[i][2]
        low = bars[i][3]
        prev_close = bars[i-1][4]
        tr = max(high-low, abs(high-prev_close), abs(low-prev_close))
        trs.append(tr)
    return sum(trs[-period:]) / period

def analyze(symbol):
    bars = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=201)
    closed_bars = bars[:-1] # شمعة مغلقة فقط
    if len(closed_bars) < 200: closed_bars = bars
    closes=[b[4] for b in closed_bars]
    vols=[b[5] for b in closed_bars]
    c=closes[-1]
    ema50=ema_calc_proper(closes,50)
    ema200=ema_calc_proper(closes,200)
    rsi=rsi_calc_proper(closes,14)
    e12=ema_calc_proper(closes,12)
    e26=ema_calc_proper(closes,26)
    macd=e12-e26
    macd_prev = ema_calc_proper(closes[:-1],12) - ema_calc_proper(closes[:-1],26)
    vol_avg=sum(vols[-20:])/20 if len(vols)>=20 else vols[-1]
    vol=vols[-1]
    score=0; reasons=[]
    if c>ema50 and ema50>ema200: score+=2; reasons.append("Uptrend EMA")
    if rsi > 50 and rsi < 68: score+=1; reasons.append("RSI %d Bull" % int(rsi))
    elif 40 < rsi < 50 and rsi > rsi_calc_proper(closes[:-1],14): score+=1; reasons.append("RSI Imp %d" % int(rsi))
    if macd>0 and macd>macd_prev: score+=1; reasons.append("MACD Up")
    elif macd>0: score+=0.5; reasons.append("MACD+")
    if vol>vol_avg*1.5 and closes[-1] > closes[-2]: score+=2; reasons.append("Vol %.1fx" % (vol/vol_avg))
    elif vol>vol_avg*1.5: score+=0.5; reasons.append("VolH %.1fx" % (vol/vol_avg))
    atr = atr_calc_proper(closed_bars, 14)
    if atr == 0: atr = c * 0.01
    atr_distance = atr * 1.8
    min_distance = c * 0.02
    stop_distance = max(atr_distance, min_distance)
    stop = c - stop_distance
    tp1 = c + (stop_distance * 1.0)
    tp2 = c + (stop_distance * 1.618)
    tp3 = c + (stop_distance * 2.618)
    risk_amt = CAPITAL * (RISK_PERCENT/100)
    qty_by_risk = risk_amt / stop_distance if stop_distance>0 else 0
    max_cost = CAPITAL * MAX_POSITION_PCT
    qty_by_capital = max_cost / (c * (1+FEE_PCT)) if c>0 else 1
    qty = min(qty_by_risk, qty_by_capital)
    position_value = qty * c
    return {"score": score, "reasons": reasons, "price": c, "stop": stop, "tp1": tp1, "tp2": tp2, "tp3": tp3, "qty": qty, "position_value": position_value, "atr": atr}

async def error_handler(update, context):
    print("Error: %s" % context.error)
    # ما يخلي البوت يطفي لو صار Conflict
    if "Conflict" in str(context.error):
        print("Conflict ignored - another instance running")
        await asyncio.sleep(5)

async def start(update, context):
    await update.message.reply_text("Diamond Bot V3 Ready\n/analysis BTC\n/scan\n/news")

async def news_cmd(update, context):
    try:
        fg_val, fg_txt = get_fear_greed()
        msg = "F&G: %d - %s\n" % (fg_val, fg_txt)
        if fg_val>=75: msg+="High greed\n\n"
        elif fg_val<=25: msg+="High fear\n\n"
        else: msg+="Neutral\n\n"
        news = get_news()
        if news:
            for n in news: msg+="- %s\n" % n['title'][:80]
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text("News err: %s" % e)

async def analysis_cmd(update, context):
    sym="BTC/USDT"
    if context.args: sym="%s/USDT" % context.args[0].upper()
    await update.message.reply_text("Analyzing %s..." % sym)
    try:
        fg_val, fg_txt = get_fear_greed()
        d = await asyncio.to_thread(analyze, sym)
        if d['score']>=5: status="GOLDEN"
        elif d['score']>=4: status="GOOD"
        elif d['score']>=2: status="WATCH"
        else: status="WAIT"
        reason_txt = " + ".join(d['reasons']) if d['reasons'] else "None"
        lines = []
        lines.append("%s | %s" % (sym, TIMEFRAME))
        lines.append("Price: %.4f ATR: %.4f" % (d['price'], d['atr']))
        lines.append("F&G: %d (%s)" % (fg_val, fg_txt))
        lines.append("Score: %s/6 %s" % (d['score'], reason_txt))
        lines.append("Stop: %.4f -%.1f%%" % (d['stop'], abs(d['price']-d['stop'])/d['price']*100))
        lines.append("TP1 R1: %.4f +%.1f%% 40%%" % (d['tp1'], abs(d['tp1']-d['price'])/d['price']*100))
        lines.append("TP2 R1.6: %.4f +%.1f%% 30%%" % (d['tp2'], abs(d['tp2']-d['price'])/d['price']*100))
        lines.append("TP3 R2.6: %.4f +%.1f%% 30%%" % (d['tp3'], abs(d['tp3']-d['price'])/d['price']*100))
        lines.append("Qty: %.4f Pos: $%.2f" % (d['qty'], d['position_value']))
        lines.append(status)
        txt = "\n".join(lines)
        await update.message.reply_text(txt)
    except Exception as e:
        await update.message.reply_text("Error: %s" % e)

async def scan_cmd(update, context):
    fg_val, fg_txt = get_fear_greed()
    await update.message.reply_text("Scanning %d coins..." % len(TOP_COINS))
    found=0
    for s in TOP_COINS:
        try:
            await asyncio.sleep(0.4)
            d = await asyncio.to_thread(analyze, s)
            if d['score']>=5:
                if fg_val>=85: continue
                found+=1
                msg = "GOLDEN: %s Score %s Price %.4f Pos $%.0f TP1 %.4f TP2 %.4f TP3 %.4f" % (s, d['score'], d['price'], d['position_value'], d['tp1'], d['tp2'], d['tp3'])
                await update.message.reply_text(msg)
        except: continue
    if found==0: await update.message.reply_text("No golden now.")

def run_flask():
    port=int(os.environ.get("PORT",10000))
    app_flask.run(host='0.0.0.0', port=port)

def main():
    if not TOKEN: print("BOT_TOKEN missing"); return
    threading.Thread(target=run_flask, daemon=True).start()
    app=Application.builder().token(TOKEN).build()
    app.add_error_handler(error_handler)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("analysis", analysis_cmd))
    app.add_handler(CommandHandler("price", analysis_cmd))
    app.add_handler(CommandHandler("scan", scan_cmd))
    app.add_handler(CommandHandler("news", news_cmd))
    print("Bot V3 Started - Conflict protected")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

if __name__=='__main__': main()