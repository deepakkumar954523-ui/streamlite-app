import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, time
from streamlit_autorefresh import st_autorefresh
from SmartApi import SmartConnect
import pyotp
import requests

# ---- NumPy >=2.0 compatibility for pandas_ta ----
if not hasattr(np, "NaN"):
    np.NaN = np.nan

import pandas_ta as ta


# ===================== USER CONFIG =====================
API_KEY = "VkbMOmLR"
CLIENT_ID = "A51947827"
TOTP_SECRET = "T6LZJTSG3QR5HDBYEYCO5UTUWU"
CLIENT_PASSWORD = "2026"

BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
CHAT_ID = "YOUR_CHAT_ID"


# ===================== UI / REFRESH =====================
st.set_page_config(page_title="NIFTY/BANKNIFTY Signal App", layout="wide")

# Auto refresh every 10 sec
st_autorefresh(interval=10_000, key="datarefresh")

st.title("📈 Live NIFTY/BANKNIFTY Signal App")

# Sidebar
st.sidebar.header("⚙️ Settings")

symbol = st.sidebar.selectbox(
    "Select Index",
    ["NIFTY", "BANKNIFTY"],
    index=0
)

interval_label = st.sidebar.selectbox(
    "Interval",
    ["1 Minute", "5 Minute", "15 Minute", "30 Minute", "1 Hour", "1 Day"],
    index=1
)

# Interval Mapping
INTERVAL_MAP = {
    "1 Minute": "ONE_MINUTE",
    "5 Minute": "FIVE_MINUTE",
    "15 Minute": "FIFTEEN_MINUTE",
    "30 Minute": "THIRTY_MINUTE",
    "1 Hour": "ONE_HOUR",
    "1 Day": "ONE_DAY",
}

interval = INTERVAL_MAP[interval_label]


# ===================== Date Range =====================
st.sidebar.subheader("📅 Date Range")

default_start = (datetime.now() - timedelta(days=1)).date()
default_end = datetime.now().date()

start_date = st.sidebar.date_input("From", default_start)
end_date = st.sidebar.date_input("To", default_end)

market_open = time(9, 15)
market_close = time(15, 30)

from_dt = datetime.combine(start_date, market_open)

now = datetime.now()
if end_date == now.date():
    to_time = min(now.time(), market_close)
    to_dt = datetime.combine(end_date, to_time)
else:
    to_dt = datetime.combine(end_date, market_close)

fromdate = from_dt.strftime("%Y-%m-%d %H:%M")
todate = to_dt.strftime("%Y-%m-%d %H:%M")


# ===================== SmartAPI Login =====================
try:
    obj = SmartConnect(api_key=API_KEY)

    totp = pyotp.TOTP(TOTP_SECRET).now()
    data = obj.generateSession(CLIENT_ID, CLIENT_PASSWORD, totp)

    jwt_token = data["data"]["jwtToken"]
    feed_token = obj.getfeedToken()

    st.sidebar.success("✅ Logged in")

except Exception as e:
    st.sidebar.error(f"Login failed: {e}")
    st.stop()


# ===================== Symbol Tokens =====================
SYMBOL_TOKENS = {
    "NIFTY": "99926000",
    "BANKNIFTY": "99926009",
}

symbol_token = SYMBOL_TOKENS[symbol]


# ===================== Fetch Candle Data =====================
def fetch_candles(client, token, interval, fromdate, todate):

    payload = {
        "exchange": "NSE",
        "symboltoken": token,
        "interval": interval,
        "fromdate": fromdate,
        "todate": todate,
    }

    try:
        resp = client.getCandleData(payload)

        if not resp or "data" not in resp or resp["data"] in (None, [], "null"):
            return pd.DataFrame()

        raw = resp["data"]

        df = pd.DataFrame(
            raw,
            columns=["datetime", "open", "high", "low", "close", "volume"]
        )

        df["datetime"] = pd.to_datetime(df["datetime"])

        for c in ["open", "high", "low", "close", "volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")

        df.dropna(subset=["open", "high", "low", "close"], inplace=True)

        df.sort_values("datetime", inplace=True)
        df.set_index("datetime", inplace=True)

        return df

    except Exception:
        return pd.DataFrame()


df = fetch_candles(obj, symbol_token, interval, fromdate, todate)

if df.empty:
    st.warning("No candle data returned. Try different date or interval.")
    st.stop()


# ===================== Indicators =====================
df["EMA20"] = ta.ema(df["close"], length=20)
df["EMA50"] = ta.ema(df["close"], length=50)
df["RSI"] = ta.rsi(df["close"], length=14)

# Volume Spike
df["AvgVol20"] = df["volume"].rolling(window=20).mean()
df["VolumeSpike"] = df["volume"] > (df["AvgVol20"] * 1.5)


# ===================== Signal Logic =====================
signal = "HOLD"

valid = df.dropna(subset=["EMA20", "EMA50", "RSI"])

if not valid.empty:
    last_row = valid.iloc[-1]

    if (last_row["EMA20"] > last_row["EMA50"]) and (last_row["RSI"] < 70) and last_row["VolumeSpike"]:
        signal = "BUY"
        st.session_state["entry_price"] = float(last_row["close"])

    elif (last_row["EMA20"] < last_row["EMA50"]) and (last_row["RSI"] > 30) and last_row["VolumeSpike"]:
        signal = "SELL"
        st.session_state["entry_price"] = float(last_row["close"])


# ===================== Display =====================
st.subheader(f"📊 Latest Signal: {signal}")

st.line_chart(df[["close", "EMA20", "EMA50"]])
st.line_chart(df[["RSI"]])
st.bar_chart(df[["volume"]])


# ===================== Telegram =====================
def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        params = {"chat_id": CHAT_ID, "text": message}
        requests.get(url, params=params, timeout=5)
    except:
        pass

if st.button("Send Signal to Telegram"):
    send_telegram(f"{symbol} Signal: {signal} at {datetime.now().strftime('%H:%M:%S')}")
