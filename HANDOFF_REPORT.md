# QuantConnect Interactive Backtesting UI
## Technical & Operational Handoff Report

**Last Updated:** 25 Jul 2026

---

## 1. Conceptual Overview

### 1.1 Background & Purpose
The **QuantConnect Interactive Backtesting UI** acts as a bridge between a powerful but strictly code-driven algorithmic trading engine (LEAN) and an intuitive, visual web interface. It allows users to rapidly prototype, configure, and backtest complex multi-signal trading strategies without needing to modify Python code for every permutation.

### 1.2 High-Level Architecture
- **LEAN Algorithm (`MultiSignalStrategy.py`):** A highly parameterized Python script running on the QuantConnect LEAN engine. It reads external JSON configuration parameters and evaluates up to 13 buy conditions and 12 sell conditions on a daily resolution.
- **Frontend Dashboard (`backtest_ui/`):** A vanilla HTML/CSS/JS single-page application (SPA). It provides range sliders, condition toggles, dynamic date pickers, and interactive Chart.js visualizations (PnL Curve, Per-Trade Bar, and Buy/Sell Price chart views).
- **Integration Layer (Completed):** A lightweight local Flask server (`server.py`) that acts as the execution bridge. It receives the UI configuration, handles data sourcing (auto-downloading and refreshing CSVs via `yfinance` up to the current date or routing to the QC Cloud API), executes `dotnet run` on the LEAN Launcher with proper `PYTHONNET_PYDLL` environment settings, parses the raw LEAN JSON/log outputs, and streams real-time status and logs back to the UI.

---

## 2. Current Implementation Status

### 2.1 What is COMPLETED
- **The LEAN Python Algorithm (`MultiSignalStrategy.py`):**
  - Fully implements 13 diverse Buy Conditions (EMA crosses, RSI, PSAR, ADX, MACD, Stochastic, Bollinger Bands, 52W margins, gaps).
  - Fully implements 12 diverse Sell Conditions (trend reversals, overbought metrics, etc.).
  - Parameters (periods, thresholds, margins) are all externally configurable using `self.get_parameter()`.
  - Manual tracking of previous bar states (`_prev_high`, `_prev_low`) for complex logic like Gaps and Crosses.
  - Generates diagnostic logs and custom Chart series.
- **The Frontend Dashboard (`backtest_ui`):**
  - Modern, responsive, dark-mode CSS styling (`style.css`).
  - Comprehensive HTML layout (`index.html`) with grouped sections for Strategy Setup, Buy/Sell toggles, and Indicator Settings.
  - JavaScript logic (`app.js`) to sync sliders with numerical displays, toggle sections, and dynamically initialize date inputs to the latest 6-year window ending today.
  - **AmiBroker-Style Detailed Strategy Statistics Table & Metrics:**
    - Full 3-column performance statistics breakdown (**All trades**, **Long trades**, **Short trades**).
    - Strict dynamic color coding across all tables and metric cards (Total Return, Avg Win, Avg Loss): Green (`#10b981`) for positive gains/ratios, Red (`#f43f5e`) for losses/drawdowns.
    - Covers Capital & Profit, All Trades, Winners, Losers, Drawdowns, and Advanced Performance Ratios (CAR/MaxDD, Recovery Factor, Profit Factor, Payoff Ratio, Ulcer Index, Sharpe Ratio, K-Ratio).
- **The Execution Bridge (`server.py`):**

  - Fully implemented synchronous Flask server backend.
  - **Dynamic Yahoo Finance Data Pipeline:** Automatically fetches daily historical data from `1998-01-01` to `date.today()`.
  - **Stale Data Detection:** Peeks inside cached `.zip` files in `Data/equity/usa/daily/` and automatically invalidates and re-downloads data if the cached last bar is >5 days behind the requested backtest end date.
  - **PythonNet DLL Resolution:** Automatically detects and sets `PYTHONNET_PYDLL` to ensure LEAN embeds Python 3.11 seamlessly.
  - Fallback support to the QuantConnect Cloud API.
  - Dynamically patches `config.json` with user parameters.
  - Parses LEAN logs to capture trades, computing PnL, Win Rates, and cumulative chart series.

### 2.2 What is PENDING / NEXT STEPS
- **Cloud Deployment (Optional):** If needed, the Flask server and UI could be packaged into a Docker container and deployed to a remote server.
- **Advanced Asset Classes:** Currently, data downloading is tuned for US & International Equities (including `.BK` Thai stocks). If crypto or forex is needed, the `yfinance` parser can be extended to map to those specific LEAN data folder structures.

---

## 3. Operational Guide

### 3.1 Reviewing the Strategy
You can review the algorithm logic in `Algorithm.Python/MultiSignalStrategy.py`. It is designed to be highly modular. By default, it expects parameters like `bcond1` (1 or 0) to enable/disable specific logic gates.

### 3.2 Running the Dashboard
1. Open a terminal in `backtest_ui/`.
2. Run `python server.py`.
3. Open `http://localhost:5000` in your web browser.
4. Set your symbol (e.g., `AOT.BK`, `GOOG`, `AAPL`), adjust date ranges (defaults to the latest 6 years), select conditions, and click **Run Backtest**.

### 3.3 Adding New Conditions
To add a new condition (e.g., `BCOND14`):
1. Add the toggle in `index.html` under the Buy Conditions section.
2. In `app.js`, ensure the toggle maps to the correct `bcond14` key.
3. In `MultiSignalStrategy.py`, read the parameter: `14: int(self.get_parameter("bcond14", "0"))`.
4. Add the boolean evaluation logic to the `bcond` dictionary inside the `on_data` method.

---

## 4. Deliverables Checklist

| File | Status | Description |
|:---|:---:|:---|
| `Algorithm.Python/MultiSignalStrategy.py` | DONE | Fully parameterized multi-condition LEAN algorithm. |
| `backtest_ui/index.html` | DONE | Interactive HTML layout with dynamic date pickers and 3-tab chart. |
| `backtest_ui/style.css` | DONE | Dark mode, glassmorphic styling. |
| `backtest_ui/app.js` | DONE | UI logic complete; dynamic 6-year date setup, 3 chart views (PnL, Bar, Price). |
| `backtest_ui/server.py` | DONE | Flask bridge with auto data download, stale-data detection, and `PYTHONNET_PYDLL` resolution. |
| `HANDOFF_REPORT.md` | DONE | Technical & Operational handoff documentation. |
| `lesson_learn.md` | DONE | Known gotchas, system caveats, and architectural lessons learned. |
