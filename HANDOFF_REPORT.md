# QuantConnect Interactive Backtesting UI
## Technical & Operational Handoff Report

**Last Updated:** 1 Aug 2026

---

## 1. Conceptual Overview

### 1.1 Background & Purpose
The **QuantConnect Interactive Backtesting UI** acts as a bridge between a powerful but strictly code-driven algorithmic trading engine (LEAN) and an intuitive, visual web interface. It allows users to rapidly prototype, configure, and backtest complex multi-signal trading strategies without needing to modify Python code for every permutation.

### 1.2 High-Level Architecture
- **LEAN Algorithm (`MultiSignalStrategy.py`):** A highly parameterized Python script running on the QuantConnect LEAN engine. It reads external JSON configuration parameters and evaluates up to 13 buy conditions and 12 sell conditions on a daily resolution.
- **Frontend Dashboard (`backtest_ui/`):** A vanilla HTML/CSS/JS single-page application (SPA). It provides range sliders, condition toggles, dynamic date pickers, and interactive Chart.js visualizations (PnL Curve, Per-Trade Bar, and Buy/Sell Price chart views).
- **Integration Layer (Completed):** A lightweight Flask server (`server.py`) acting as an asynchronous execution bridge. It receives UI configurations, handles resilient data sourcing (auto-downloading and refreshing CSVs via `yfinance` with soft fallback for cached data), executes pre-compiled LEAN binaries via `dotnet exec`, and streams real-time status and logs to the UI.

---

## 2. Current Implementation Status

### 2.1 What is COMPLETED
- **The LEAN Python Algorithm (`MultiSignalStrategy.py`):**
  - Fully implements 13 diverse Buy Conditions (EMA crosses, RSI, PSAR, ADX, MACD, Stochastic, Bollinger Bands, 52W margins, gaps).
  - Fully implements 12 diverse Sell Conditions (trend reversals, overbought metrics, etc.).
  - Dynamic indicator warmup calculation (`warm_up = self._ema200_period`) to skip unnecessary rolling window overhead when 52-week conditions are disabled.
  - Parameters (periods, thresholds, margins) are all externally configurable using `self.get_parameter()`.
  - Manual tracking of previous bar states (`_prev_high`, `_prev_low`) for complex logic like Gaps and Crosses.
  - Generates diagnostic logs and custom Chart series.
- **The Frontend Dashboard (`backtest_ui`):**
  - Modern, responsive, dark-mode CSS styling (`style.css`).
  - Comprehensive HTML layout (`index.html`) with grouped sections for Strategy Setup, Buy/Sell toggles, and Indicator Settings.
  - JavaScript logic (`app.js`) supporting asynchronous HTTP 202 job launching and status polling (`/api/status`).
  - **AmiBroker-Style Detailed Strategy Statistics Table & Metrics:**
    - Full 3-column performance statistics breakdown (**All trades**, **Long trades**, **Short trades**).
    - Strict dynamic color coding across all tables and metric cards (Total Return, Avg Win, Avg Loss): Green (`#10b981`) for positive gains/ratios, Red (`#f43f5e`) for losses/drawdowns.
    - Covers Capital & Profit, All Trades, Winners, Losers, Drawdowns, and Advanced Performance Ratios (CAR/MaxDD, Recovery Factor, Profit Factor, Payoff Ratio, Ulcer Index, Sharpe Ratio, K-Ratio).
- **The Execution Bridge (`server.py`):**
  - **Asynchronous Worker Thread Architecture (Rev.1):** Launches LEAN backtests in background daemon threads and responds immediately with HTTP `202 Accepted`, eliminating request timeouts.
  - **Resilient Data Sourcing & Soft Fallback (LL-20):** Retains cached `.zip` files when `yfinance` refresh is rate-limited by cloud IPs, preventing hard failures.
  - **PythonNet DLL Resolution:** Automatically detects and sets `PYTHONNET_PYDLL` to ensure LEAN embeds Python 3.11 seamlessly.
  - Dynamically patches `config.json` with user parameters across CWD and MSBuild output directories.
- **Cloud Deployment & WSGI Production Server (Render.com via Docker):**
  - `Dockerfile.render` uses multi-worker `gunicorn` (`--workers 2 --threads 4`) bound to Render's injected `$PORT`.
  - Pre-compiles Launcher DLL and pre-bundles ticker data (`GOOG`, `AAPL`, `AOT.BK`, `PTT.BK`, `SCB.BK`, `KBANK.BK`) at build time.
- **Strategy Accuracy Audit & Multi-Ticker Benchmark Evaluation:**
  - Evaluated performance across Thai SET stocks (`AOT.BK`, `BH.BK`, `IVL.BK`) and US equities (`GOOG`, `AAPL`) over a 5-year window (2019–2024).
  - **Top Performer:** `BH.BK` achieved **+72.72% return, 2.65 Profit Factor, +0.81 Sharpe ratio**.
  - Confirmed 100% mathematical consistency between LEAN native engine totals and server metric calculations.

### 2.2 What is PENDING / NEXT STEPS
- **Advanced Asset Classes:** Currently, data downloading is tuned for US & International Equities (including `.BK` Thai stocks). If crypto or forex is needed, the `yfinance` parser can be extended to map to those specific LEAN data folder structures.
- **Git LFS (Optional):** GitHub flagged `Data/option/usa/minute/aapl/20140606_quote_american.zip` (53.89 MB) as exceeding the 50 MB recommendation. If more large data files are added, consider enabling Git LFS.

---

## 3. Operational Guide

### 3.1 Reviewing the Strategy
You can review the algorithm logic in `Algorithm.Python/MultiSignalStrategy.py`. It is designed to be highly modular. By default, it expects parameters like `bcond1` (1 or 0) to enable/disable specific logic gates.

### 3.2 Running the Dashboard (Local)
1. Open a terminal in `backtest_ui/`.
2. Run `python server.py`.
3. Open `http://localhost:5000` in your web browser.
4. Set your symbol (e.g., `AOT.BK`, `GOOG`, `AAPL`), adjust date ranges (defaults to the latest 6 years), select conditions, and click **Run Backtest**.

### 3.3 Deploying to Render.com
1. Push all changes to GitHub: `git push origin master:main`.
2. On Render.com, create a **Web Service** connected to the GitHub repo.
3. Set **Dockerfile Path** to `./Dockerfile.render`.
4. Render automatically injects the `PORT` environment variable; the server binds to it.
5. Deploy triggers automatically on every push to `main`.

### 3.4 Adding New Conditions
To add a new condition (e.g., `BCOND14`):
1. Add the toggle in `index.html` under the Buy Conditions section.
2. In `app.js`, ensure the toggle maps to the correct `bcond14` key.
3. In `MultiSignalStrategy.py`, read the parameter: `14: int(self.get_parameter("bcond14", "0"))`.
4. Add the boolean evaluation logic to the `bcond` dictionary inside the `on_data` method.

---

## 4. Deliverables Checklist

| File | Status | Description |
|:---|:---:|:---|
| `Algorithm.Python/MultiSignalStrategy.py` | ✅ DONE | Fully parameterized multi-condition LEAN algorithm. |
| `backtest_ui/index.html` | ✅ DONE | Interactive HTML layout with dynamic date pickers and 3-tab chart. |
| `backtest_ui/style.css` | ✅ DONE | Dark mode, glassmorphic styling with dynamic PnL color coding. |
| `backtest_ui/app.js` | ✅ DONE | UI logic; dynamic 6-year date setup, 3 chart views, dynamic metric card colors. |
| `backtest_ui/server.py` | ✅ DONE | Flask bridge. `dotnet exec` + CLI arg override (`--algorithm-language Python`), retry+abort on yfinance, Linux `.so` detection (LL-13, LL-15). |
| `Dockerfile.render` | ✅ DONE | Stub `Algorithm.CSharp.csproj` (MSB9008 fix), pre-bundled ticker cache (GOOG/AAPL/AOT.BK/PTT.BK/SCB.BK/KBANK.BK), DLL verification (LL-15, LL-16). |
| `Launcher/config.json` | ✅ DONE | Default paths updated to Docker `/app/...` paths (patched at runtime by server.py). |
| `.gitignore` | ✅ DONE | Updated with whitelist rules for custom project files. |
| `.dockerignore` | ✅ DONE | Updated to include `backtest_ui/` in Docker build context. |
| `HANDOFF_REPORT.md` | ✅ DONE | Technical & Operational handoff documentation. |
| `lesson_learn.md` | ✅ DONE | Known gotchas, system caveats, and architectural lessons learned. |

---

## 5. Repository & Deployment Info

| Item | Value |
|:---|:---|
| GitHub Repository | `https://github.com/plwn75-btz/Quant_Lean_Investment` |
| Local Branch | `master` |
| Remote Branch | `main` |
| Push Command | `git push origin master:main` |
| Render Dockerfile | `./Dockerfile.render` |
| Base Docker Image | `quantconnect/lean:foundation` |
| Server Port Binding | `os.environ.get("PORT", 5000)` |
