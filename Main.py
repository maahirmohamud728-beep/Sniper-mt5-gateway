
import os
from typing import List, Literal
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

API_KEY = os.getenv("SNIPER_API_KEY", "")
app = FastAPI(title="SNIPER MT5 GATEWAY", version="1.0.0")


class Candle(BaseModel):
    time: int
    open: float
    high: float
    low: float
    close: float
    tick_volume: int = 0


class SignalRequest(BaseModel):
    symbol: str
    timeframe: str
    candles: List[Candle]


class SignalResponse(BaseModel):
    symbol: str
    timeframe: str
    action: Literal["BUY", "SELL", "HOLD"]
    reason: str
    entry: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None


def authorize(key):
    if not API_KEY:
        raise HTTPException(503, "API key not configured")
    if key != API_KEY:
        raise HTTPException(401, "Invalid API key")


def ema(values, period):
    if len(values) < period:
        return None

    alpha = 2 / (period + 1)
    result = sum(values[:period]) / period

    for value in values[period:]:
        result = alpha * value + (1-alpha) * result

    return result


def rsi(values, period=14):
    if len(values) < period + 1:
        return None

    changes = [
        values[i] - values[i-1]
        for i in range(1, len(values))
    ]

    gains = [max(x, 0) for x in changes]
    losses = [max(-x, 0) for x in changes]

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def atr(candles, period=14):
    if len(candles) < period + 1:
        return None

    ranges = []

    for i in range(1, len(candles)):
        current = candles[i]
        previous = candles[i-1].close

        tr = max(
            current.high - current.low,
            abs(current.high - previous),
            abs(current.low - previous)
        )

        ranges.append(tr)

    return sum(ranges[-period:]) / period


@app.get("/")
def home():
    return {
        "service": "SNIPER MT5 GATEWAY",
        "status": "running",
        "market": "XAUUSD"
    }


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/signal", response_model=SignalResponse)
def get_signal(
    data: SignalRequest,
    x_api_key: str | None = Header(default=None)
):

    authorize(x_api_key)

    if data.symbol.upper() != "XAUUSD":
        raise HTTPException(400, "XAUUSD only")

    if data.timeframe.upper() != "M1":
        raise HTTPException(400, "M1 only")

    if len(data.candles) < 30:
        raise HTTPException(400, "Send at least 30 candles")

    candles = data.candles[-100:]
    closes = [c.close for c in candles]

    fast = ema(closes, 9)
    slow = ema(closes, 21)
    momentum = rsi(closes, 14)
    volatility = atr(candles, 14)

    price = closes[-1]

    action = "HOLD"
    reason = "No clear setup. Wait."

    if fast > slow and 50 < momentum < 70:
        action = "BUY"
        reason = "Bullish EMA and RSI confirmation."

    elif fast < slow and 30 < momentum < 50:
        action = "SELL"
        reason = "Bearish EMA and RSI confirmation."

    if action == "HOLD" or volatility <= 0:
        return SignalResponse(
            symbol="XAUUSD",
            timeframe="M1",
            action="HOLD",
            reason=reason
        )

    sl_distance = 1.5 * volatility
    tp_distance = 2.0 * volatility

    if action == "BUY":
        sl = price - sl_distance
        tp = price + tp_distance
    else:
        sl = price + sl_distance
        tp = price - tp_distance

    return SignalResponse(
        symbol="XAUUSD",
        timeframe="M1",
        action=action,
        reason=reason,
        entry=round(price, 3),
        stop_loss=round(sl, 3),
        take_profit=round(tp, 3)
    )

fastapi==0.115.12
uvicorn[standard]==0.34.2
pydantic==2.11.4

FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

EXPOSE 10000

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000}"]

services:
  - type: web
    name: sniper-mt5-gateway
    runtime: docker
    plan: free
    healthCheckPath: /health
