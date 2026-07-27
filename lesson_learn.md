# Lessons Learned — Quant-LEAN Engineering UI & Strategy
**Project:** QuantConnect Multi-Signal Strategy & Interactive UI
**Last Updated:** 25 Jul 2026

---

## LL-01: Modular Strategy Parameterization
**Observation:** Hardcoding indicator periods and thresholds in the LEAN algorithm requires recompiling or modifying code for every backtest.
**Lesson:** Exposing all variables (periods, thresholds, margins, and toggles) via `self.get_parameter()` allows a completely data-driven approach. The `MultiSignalStrategy` can now be controlled entirely from the frontend UI without touching the Python code.

## LL-02: Mutually Exclusive Conditions
**Problem:** Some buy conditions contradict each other (e.g., RSI oversold vs. Stochastic K > 70).
**Fix/Decision:** Documented warnings in the strategy (e.g., `BCOND3` and `BCOND10`). 
**Lesson:** The UI should ideally enforce logical grouping or provide warnings when mutually exclusive conditions are selected simultaneously, preventing users from running guaranteed-to-fail backtests.

## LL-03: Gap Detection Requires Previous Bar State
**Problem:** Checking for a "Gap Up" or "Gap Down" requires the previous day's high/low, which LEAN doesn't provide automatically in the current bar's slice unless explicitly tracked or queried via a RollingWindow.
**Fix:** Created private instance variables (`self._prev_high`, `self._prev_low`, etc.) and updated them at the end of every `on_data` loop to maintain the state with minimal overhead.
**Lesson:** For simple cross-bar logic, manual state tracking (`_prev_*`) is often more lightweight and direct than setting up an entire `RollingWindow` array.

## LL-04: UI/UX Separation of Concerns
**Observation:** Building an interactive backtest UI in vanilla HTML/CSS/JS requires careful management of state, especially with many range sliders and toggles.
**Lesson:** Using data attributes and simple event delegation keeps the JS lightweight. Grouping settings logically (Strategy Setup, Buy Conditions, Sell Conditions, Indicator Parameters) makes the complex LEAN engine accessible to non-programmers.

## LL-05: Chart.js Multi-View Visualization
**Observation:** Real-time feedback and clear visual correlation between PnL percentage and underlying asset price movements are critical for trading strategy design.
**Lesson:** Providing multiple chart modes (*PnL Curve*, *Per-Trade Bar*, and *Buy/Sell Price*) allows users to evaluate both overall portfolio equity growth and individual trade entry/exit execution relative to stock price levels.

## LL-06: Cached Data Stale Check & Dynamic End Dates
**Problem:** Hardcoding static end dates (e.g., `2024-12-31`) in data downloader scripts causes backtests for current dates to cut off prematurely. Furthermore, cached data `.zip` files in `Data/equity/usa/daily/` would be reused indefinitely without verifying if they contained bars up to the requested backtest end date.
**Fix:** Modified `server.py`'s `_ensure_data()` method to dynamically fetch data up to `date.today()`, and implemented a stale-data inspection check. If the last bar inside an existing `.zip` file is >5 days behind the requested end date, the zip is automatically deleted and re-downloaded fresh from Yahoo Finance.
**Lesson:** Always complement local caching with timestamp validation against requested query ranges to prevent silent data truncations.

## LL-07: Interactive Price & Trade Signal Overlay
**Observation:** A cumulative PnL curve shows portfolio returns, but fails to convey trade entry/exit precision against market price action.
**Lesson:** Adding a dedicated "Buy/Sell Price" scatter/line view using Chart.js (with custom triangle ▲ / diamond ◆ markers, outcome-based point colors, hold-period connector lines, and an absolute price Y-axis) gives traders immediate visual insight into whether trades were entered/exited at optimal price points.

## LL-08: PythonNet DLL Environment Resolution for LEAN
**Problem:** Executing LEAN via `dotnet run` outside of pre-configured IDE environments can trigger `Python.Runtime.BadPythonDllException: Runtime.PythonDLL was not set or does not point to a supported Python runtime DLL`.
**Fix:** The Flask server (`server.py`) explicitly detects the active Python runtime's DLL (`python311.dll`) and passes `PYTHONNET_PYDLL` in the process environment dictionary when invoking `dotnet run`.
**Lesson:** When wrapping C#/.NET projects that embed Python (via Python.Runtime/PythonNet), explicit environment variable initialization is necessary to ensure cross-process startup reliability.

## LL-09: AmiBroker-Style Strategy Statistics Report & Color Conventions
**Observation:** Standard high-level metric cards (Win Rate, Total Return) do not provide the exhaustive statistical breakdowns expected by quantitative traders accustomed to platforms like AmiBroker.
**Lesson:** Computing 30+ detailed metrics (Capital & Profit, All/Long/Short trade splits, Win/Loss streaks, Max Drawdown $, CAR/MaxDD, Profit Factor, Payoff Ratio, Ulcer Index, Sharpe, K-Ratio) directly from trade logs and rendering them in a dedicated 3-column table creates an enterprise-grade report.
**Color Convention:** Enforce strict visual encoding across the entire dashboard (including top metric cards like AVG WIN and AVG LOSS): positive gains/ratios styled in **Green** (`#10b981`), negative losses/drawdowns styled in **Red** (`#f43f5e`), and neutral values in muted blue-grey (`#8a9ab8`). This dynamic styling prevents visual ambiguity.

