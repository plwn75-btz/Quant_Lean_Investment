# QuantConnect Interactive Backtesting UI
## Technical & Operational Handoff Report

**Last Updated:** 28 Jul 2026

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

- **Cloud Deployment (Render.com via Docker):**
  - `Dockerfile.render` builds on `quantconnect/lean:foundation` (provides .NET SDK + Python + TA-Lib).
  - Explicit `COPY` instructions for each LEAN project directory (Algorithm.Python, Launcher, Common, Engine, etc.).
  - `dotnet restore && dotnet build` runs during image build so the Launcher is pre-compiled.
  - **DLL Existence Verification:** A `RUN find ... && test -n ...` step was added after the build to fail the Docker image early if the Launcher DLL is missing (instead of silently deferring to runtime).
  - Flask server binds to the `PORT` environment variable injected by Render at runtime.
  - Repository: `https://github.com/plwn75-btz/Quant_Lean_Investment`
- **LEAN Execution Method Fixed (`dotnet exec` vs `dotnet run`):**
  - Root cause: `dotnet run --project Launcher/` triggered a full MSBuild recompile on every backtest inside the Docker container. With `Algorithm.CSharp.csproj` absent (MSB9008), the LEAN job-queue routed `MultiSignalStrategy.py` through the C# IL loader instead of the Python loader, causing `System.BadImageFormatException: Bad IL format`.
  - Fix: Added `_get_lean_dll()` to `server.py` that scans `Launcher/bin/Debug/*/` and `Launcher/bin/Release/*/` for the pre-built DLL. Execution is now `dotnet <dll_path>` (dotnet exec), bypassing MSBuild entirely.
  - Fallback: If the DLL is not found (e.g., local dev without a prior build), the server logs a warning and falls back to `dotnet run`.
- **Yahoo Finance Rate-Limit Handling Fixed:**
  - Root cause: Render.com's shared outbound IP is frequently rate-limited by Yahoo Finance. The original code silently returned on empty data, causing LEAN to launch with no market data and producing a misleading "0 trades" result.
  - Fix: `_ensure_data()` now retries up to 3 times with exponential backoff (2s, 4s+jitter). On exhaustion, it raises `RuntimeError` with a clear user-facing message, aborting the backtest before LEAN is even launched.
- **`_get_python_dll()` Enhanced for Linux/Docker:**
  - Added explicit search for `libpython3.XX.so*` under `/opt/miniconda3/lib/` (the path used in the `quantconnect/lean:foundation` image) before falling back to the Windows `python3XX.dll` search.
- **`config.json` Default Paths Corrected:**
  - `algorithm-location` and `data-folder` now default to `/app/...` Docker paths instead of the local Windows developer path. `_patch_config()` always overwrites these at runtime, but the Docker-safe defaults act as a safety net.
- **Git Configuration:**
  - `.gitignore` updated with whitelist rules (`!backtest_ui/**`, `!Algorithm.Python/MultiSignalStrategy.py`, etc.) to override the aggressive upstream LEAN ignore patterns.
  - `.dockerignore` updated to ensure `backtest_ui/` is included in Docker build context.
  - LEAN runtime artifacts (data-monitor reports, failed/succeeded data request logs) are explicitly ignored.

### 2.2 What is PENDING / NEXT STEPS
- **Pre-warmed Ticker Cache (Optional):** Yahoo Finance rate-limiting on Render.com's shared IP means the first download of any new ticker may still fail even with retries. Consider pre-bundling a baseline set of commonly used tickers (GOOG, AAPL, AOT.BK) as ZIP files in the Docker image so the first backtest always succeeds without a network call.
- **Advanced Asset Classes:** Currently, data downloading is tuned for US & International Equities (including `.BK` Thai stocks). If crypto or forex is needed, the `yfinance` parser can be extended to map to those specific LEAN data folder structures.
- **Git LFS (Optional):** GitHub flagged `Data/option/usa/minute/aapl/20140606_quote_american.zip` (53.89 MB) as exceeding the 50 MB recommendation. If more large data files are added, consider enabling Git LFS.
- **Production WSGI Server:** The current Flask development server works but consider switching to `gunicorn` for production-grade request handling on Render.

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
| `backtest_ui/server.py` | ✅ DONE | Flask bridge. `dotnet exec` (pre-built DLL), retry+abort on yfinance rate-limit, Linux `.so` DLL detection. |
| `Dockerfile.render` | ✅ DONE | Docker image for Render.com. DLL verification step added; silent build error swallow removed. |
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
