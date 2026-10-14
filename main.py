import ccxt, pandas as pd, requests, time, threading, os
from flask import Flask

TELEGRAM_TOKEN = "8809582860:AAEbunAHrIaNu3u6B_SQvrYu4O1N7qOFv4E"
TELEGRAM_CHAT_ID = None
BUDGET = 400

app = Flask(__name__)
@app.route('/')
def home():
    return "Bot 24h ON"

def send_tg(msg):
    global TELEGRAM_CHAT_ID
    if not TELEGRAM_CHAT_ID: return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=10)
    except: pass

def get_chat_id_loop():
    global TELEGRAM_CHAT_ID
    while not TELEGRAM_CHAT_ID:
        try:
            r = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates", timeout=10).json()
            if r.get('result'):
                TELEGRAM_CHAT_ID = r['result'][-1]['message']['chat']['id']
                print(f"Chat ID: {TELEGRAM_CHAT_ID}")
                send_tg(f"✅ البوت اشتغل 24 ساعة\n💰 {BUDGET}$")
                break
        except: pass
        time.sleep(10)

def analyze(symbol, exchange):
    try:
        bars = exchange.fetch_ohlcv(symbol, '1h', limit=100)
        df = pd.DataFrame(bars, columns=['t','o','h','l','c','v'])
        close = df['c']; price = close.iloc[-1]
        delta = close.diff()
        gain = delta.where(delta>0,0).rolling(14).mean()
        loss = -delta.where(delta<0,0).rolling(14).mean()
        rsi = (100 - (100/(1+gain/loss))).iloc[-1]
        ema12 = close.ewm(span=12).mean().iloc[-1]
        ema26 = close.ewm(span=26).mean().iloc[-1]
        ema50 = close.ewm(span=50).mean().iloc[-1]
        score=0; reasons=[]
        if rsi<35: score+=2; reasons.append(f"RSI {rsi:.0f}")
        if ema12>ema26: score+=1; reasons.append("MACD صاعد")
        if price>ema50: score+=1; reasons.append("فوق EMA50")
        return price, rsi, score, reasons
    except: return 0,0,0,[]

def bot_loop():
    get_chat_id_loop()
    exchange = ccxt.binance()
    while True:
        for sym in ["CHR/USDT", "HNT/USDT"]:
            price, rsi, score, reasons = analyze(sym, exchange)
            if score>=3:
                msg = f"📊 {sym}\nسعر: {price:.4f}\nRSI: {rsi:.0f}\n{' + '.join(reasons)}\nشراء 20$ هدف +6%"
                send_tg(msg)
        time.sleep(300)

threading.Thread(target=bot_loop, daemon=True).start()
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
