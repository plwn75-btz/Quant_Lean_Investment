# Quant-LEAN Engineering UI

A premium, interactive backtesting dashboard for multi-condition buy/sell signal strategies, powered by the **QuantConnect LEAN** engine.

## Quick Start

### 1. Install the Flask server dependencies

```powershell
cd backtest_ui
pip install -r requirements.txt
```

### 2. Start the server

```powershell
python server.py
```

### 3. Open the dashboard

Open your browser and go to:
```
http://localhost:5000
```

---

## How It Works

```
Browser (index.html + app.js)
    ↓ POST /api/run-backtest (JSON params)
Flask server (server.py)
    ↓ patches Launcher/config.json
    ↓ runs: dotnet run --project Launcher/
QuantConnect LEAN Engine
    ↓ executes Algorithm.Python/MultiSignalStrategy.py
    ↓ writes log with BUY/SELL entries
Flask server
    ↑ parses log → JSON results
Browser
    ↑ renders equity curve + trade table
```

---

## Strategy Parameters

All parameters can be adjusted in the UI sidebar:

| Section | Parameters |
|---|---|
| Setup | Symbol, Date Range, Capital, Position Size |
| Buy Conditions | BCOND1–BCOND13 toggles |
| Sell Conditions | SCOND1–SCOND12 toggles |
| EMA | EMA13/50/200 periods, proximity threshold |
| RSI | Period, oversold / overbought thresholds |
| MACD | Fast, Slow, Signal periods |
| Stochastic | Period, %K smoothing, buy/sell thresholds |
| ADX | Period, ADX threshold, PDI threshold |
| Parabolic SAR | Acceleration, Max Acceleration |
| Bollinger Bands | Period, Width (σ) |
| Volume | Avg period, Buy/Sell volume ratio |
| 52-Week | High/Low margins, Gap Up/Down % |

---

## Default Active Conditions

**Buy** = BCOND1 AND BCOND3 AND BCOND9 AND BCOND10 AND BCOND11 AND BCOND12

**Sell** = SCOND1 OR SCOND9 OR SCOND12

---

## Adding New Symbols

The default dataset includes `GOOG`. To backtest other symbols:

**Option A — Download via yfinance:**
```python
import yfinance as yf
# Download and convert to LEAN CSV format under Data/equity/usa/daily/<TICKER>/
```

**Option B — QuantConnect Cloud:** Upload the algorithm file and run it on [quantconnect.com](https://www.quantconnect.com).

---

## File Structure

```
backtest_ui/
├── server.py           Flask API bridge
├── index.html          Dashboard UI
├── style.css           Premium dark-mode styles
├── app.js              UI logic + Chart.js rendering
└── requirements.txt    Python deps

Algorithm.Python/
└── MultiSignalStrategy.py   LEAN algorithm (all conditions)

Launcher/
└── config.json              All parameters (auto-updated by server)
```
