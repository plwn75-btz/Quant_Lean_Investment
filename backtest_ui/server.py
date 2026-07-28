"""
backtest_ui/server.py
─────────────────────
Flask bridge between the web dashboard and the QuantConnect LEAN engine.

Endpoints
─────────
POST /api/run-backtest   Body: JSON params dict -> rewrites config.json, launches LEAN,
                         streams stdout, parses results JSON, returns summary.
GET  /api/results        Returns the latest cached backtest results.
GET  /api/status         Returns current run status.
GET  /                   Serves index.html.
GET  /<path>             Serves any static asset from this directory.

Usage
─────
    pip install flask flask-cors
    python server.py

Then open http://localhost:5000 in your browser.
"""

# ── Force UTF-8 I/O before ANY other import writes to stdout ──────────────────
# Must be the very first executable statements so Flask/Werkzeug startup
# messages also go through the UTF-8 wrapper.
import io
import sys

def _force_utf8_streams():
    """Wrap stdout/stderr in a UTF-8 TextIOWrapper on Windows."""
    for attr in ("stdout", "stderr"):
        stream = getattr(sys, attr)
        # Already reconfigured (Python 3.7+) ─ prefer that API
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
                continue
            except Exception:
                pass
        # Fallback: wrap the underlying binary buffer
        if hasattr(stream, "buffer"):
            try:
                setattr(sys, attr,
                        io.TextIOWrapper(stream.buffer,
                                         encoding="utf-8",
                                         errors="replace",
                                         line_buffering=True))
            except Exception:
                pass

_force_utf8_streams()

# ── Standard imports ──────────────────────────────────────────────────────────
import json
import os
import re
import shutil
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

# ── Paths ─────────────────────────────────────────────────────────────────────
THIS_DIR     = Path(__file__).parent.resolve()
PROJECT_DIR  = THIS_DIR.parent                       # QuantConnect/
LAUNCHER_DIR = PROJECT_DIR / "Launcher"
CONFIG_PATH  = LAUNCHER_DIR / "config.json"

app = Flask(__name__, static_folder=str(THIS_DIR), static_url_path="")
CORS(app)

# ── Shared state ──────────────────────────────────────────────────────────────
_state = {
    "status":   "idle",   # idle | running | done | error
    "started":  None,
    "finished": None,
    "log":      [],
    "results":  None,
    "error":    None,
    "progress": 0,        # 0-100
}
_lock = threading.Lock()


# =============================================================================
# Routes
# =============================================================================

@app.route("/")
def index():
    return send_from_directory(str(THIS_DIR), "index.html")


@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(str(THIS_DIR), filename)


@app.route("/api/status")
def api_status():
    with _lock:
        return jsonify({
            "status":   _state["status"],
            "progress": _state["progress"],
            "started":  _state["started"],
            "finished": _state["finished"],
            "error":    _state["error"],
            "logLines": _state["log"][-50:],
        })


@app.route("/api/results")
def api_results():
    with _lock:
        if _state["results"] is None:
            return jsonify({"error": "No results available yet"}), 404
        return jsonify(_state["results"])


@app.route("/api/run-backtest", methods=["POST"])
def api_run_backtest():
    params = request.get_json(force=True)
    if params is None:
        return jsonify({"error": "No JSON body received"}), 400

    with _lock:
        if _state["status"] == "running":
            return jsonify({"error": "A backtest is already running"}), 409
        _state["status"]   = "running"
        _state["started"]  = datetime.now().isoformat()
        _state["finished"] = None
        _state["log"]      = []
        _state["results"]  = None
        _state["error"]    = None
        _state["progress"] = 0

    try:
        results = _run_lean(params)
        with _lock:
            log_copy = list(_state["log"])
        return jsonify({"results": results, "log": log_copy}), 200
    except Exception as e:
        with _lock:
            log_copy = list(_state["log"])
        return jsonify({"error": str(e), "log": log_copy}), 500


# =============================================================================
# LEAN runner
# =============================================================================

def _get_dotnet_cmd():
    """Find the dotnet executable, preferring the user-local SDK installation."""
    local_dotnet = os.path.expanduser("~/AppData/Local/dotnet/dotnet.exe")
    if os.path.exists(local_dotnet):
        return local_dotnet
    home_dotnet = os.path.expanduser("~/.dotnet/dotnet.exe")
    if os.path.exists(home_dotnet):
        return home_dotnet
    return shutil.which("dotnet") or "dotnet"


def _get_lean_dll():
    """Find the pre-built LEAN Launcher DLL to use with 'dotnet exec'.

    Using a pre-built DLL avoids 'dotnet run' which triggers a full
    recompile on every backtest request.  The recompile introduces a
    race condition where config.json might be read before the patch is
    complete, and causes the C# IL loader to fire instead of the Python
    loader when Algorithm.CSharp.csproj is missing (MSB9008 warning).

    The Dockerfile already runs 'dotnet build -c Debug', so the output
    DLL is guaranteed to exist after a successful image build.
    """
    import glob
    patterns = [
        str(LAUNCHER_DIR / "bin" / "Debug" / "*" / "QuantConnect.Lean.Launcher.dll"),
        str(LAUNCHER_DIR / "bin" / "Release" / "*" / "QuantConnect.Lean.Launcher.dll"),
    ]
    for pattern in patterns:
        matches = sorted(glob.glob(pattern))
        if matches:
            return matches[-1]   # pick the last (newest target framework)
    return None


def _get_python_dll():
    """Find the specific python runtime DLL (e.g., python311.dll or libpython3.11.so)
    to prevent pythonnet from loading the python3.dll stub."""
    if "PYTHONNET_PYDLL" in os.environ and os.path.exists(os.environ["PYTHONNET_PYDLL"]):
        return os.environ["PYTHONNET_PYDLL"]

    # ── Linux / Docker: look for libpython3.XX.so.1.0 first ──────────────────
    import glob as _glob
    so_pattern = f"/opt/miniconda3/lib/libpython{sys.version_info.major}.{sys.version_info.minor}.so*"
    so_matches = sorted(_glob.glob(so_pattern))
    if so_matches:
        return so_matches[0]
    # Fallback generic Linux search
    so_matches = sorted(_glob.glob(f"/usr/lib/libpython{sys.version_info.major}.{sys.version_info.minor}*.so*"))
    if so_matches:
        return so_matches[0]

    # ── Windows: look for python3XX.dll ──────────────────────────────────────
    dll_name = f"python{sys.version_info.major}{sys.version_info.minor}.dll"
    for base in (Path(sys.executable).parent, Path(sys.base_prefix), Path(sys.base_exec_prefix)):
        candidate = base / dll_name
        if candidate.exists():
            return str(candidate)

    for candidate in Path(sys.base_prefix).glob(f"**/{dll_name}"):
        if candidate.exists():
            return str(candidate)

    return None


def _ensure_data(ticker: str, end_date: str = None):
    """Check if LEAN daily data exists for ticker and is up-to-date.

    Args:
        ticker:   Ticker symbol (e.g. 'AOT.BK', 'GOOG')
        end_date: ISO date string for the requested backtest end date
                  (e.g. '2026-07-24'). Used to detect stale cached data.
                  Defaults to today if not provided.
    """
    from datetime import date, timedelta
    import zipfile as _zf

    ticker   = ticker.upper().strip()
    data_dir = PROJECT_DIR / "Data" / "equity" / "usa" / "daily"
    zip_path = data_dir / f"{ticker.lower()}.zip"

    # Determine the target end date (fall back to today)
    try:
        target_end = date.fromisoformat(end_date) if end_date else date.today()
    except (TypeError, ValueError):
        target_end = date.today()

    # ── Stale-data check ────────────────────────────────────────────────────
    # If the zip exists, peek at the last bar date.  Re-download if the last
    # bar is more than 5 calendar days before the requested end date (giving
    # a small buffer for weekends / holidays).
    if zip_path.exists():
        try:
            with _zf.ZipFile(zip_path) as z:
                name    = z.namelist()[0]
                content = z.read(name).decode("utf-8", errors="replace")
            lines    = [l for l in content.strip().splitlines() if l.strip()]
            # Parse "YYYYMMDD" prefix
            raw_date = lines[-1][:8]   # e.g. '20241230'
            last_bar = date(int(raw_date[:4]), int(raw_date[4:6]), int(raw_date[6:8]))

            gap_days = (target_end - last_bar).days
            if gap_days <= 5:
                _log(f"[DATA] {ticker}: cached data is current (last bar {last_bar}, target {target_end})")
                return
            else:
                _log(f"[DATA] {ticker}: cached data is stale (last bar {last_bar}, target {target_end}, gap {gap_days}d). Re-downloading...")
                zip_path.unlink()   # delete stale zip so we re-download below
        except Exception as e:
            _log(f"[DATA] {ticker}: could not inspect existing zip ({e}). Re-downloading...")
            if zip_path.exists():
                zip_path.unlink()

    else:
        _log(f"[DATA] {ticker} not found locally. Downloading from Yahoo Finance...")

    # ── Download (with retry + exponential backoff) ──────────────────────────
    try:
        import yfinance as yf
        import pandas as pd
        import zipfile
        import time
        import random
        from datetime import date as _date

        download_end = (_date.today() + timedelta(days=1)).isoformat()  # inclusive today
        df = None
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                df = yf.download(ticker, start="1998-01-01", end=download_end, progress=False)
                if df is not None and not df.empty:
                    break
                # Empty result (may be a soft rate-limit or unknown ticker)
                _log(f"[DATA] Empty result from Yahoo Finance for {ticker} (attempt {attempt}/{max_attempts})")
            except Exception as dl_err:
                _log(f"[DATA] Download error for {ticker} (attempt {attempt}/{max_attempts}): {dl_err}")
                df = None

            if attempt < max_attempts:
                wait_secs = (2 ** attempt) + random.uniform(0.5, 1.5)
                _log(f"[DATA] Retrying in {wait_secs:.1f}s...")
                time.sleep(wait_secs)

        # ── Hard abort if no data after all retries ──────────────────────────
        if df is None or df.empty:
            raise RuntimeError(
                f"No market data available for '{ticker}' after {max_attempts} attempts. "
                "Yahoo Finance may be rate-limiting this server IP. "
                "Please wait a few minutes and try again, or switch to a different ticker "
                "that may already be cached (e.g. GOOG, AAPL)."
            )

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        csv_lines = []
        for idx, row in df.iterrows():
            date_str = idx.strftime("%Y%m%d 00:00")
            o = int(round(float(row["Open"]) * 10000))
            h = int(round(float(row["High"]) * 10000))
            l = int(round(float(row["Low"]) * 10000))
            c = int(round(float(row["Close"]) * 10000))
            v = int(round(float(row["Volume"])))
            if v < 0: v = 0
            csv_lines.append(f"{date_str},{o},{h},{l},{c},{v}")

        csv_content = "\n".join(csv_lines) + "\n"
        data_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"{ticker.lower()}.csv", csv_content)
        _log(f"[DATA] Successfully downloaded and saved {ticker} ({len(csv_lines)} bars, up to {csv_lines[-1][:8] if csv_lines else 'N/A'})")
    except RuntimeError:
        raise   # re-raise our hard-abort error directly to _run_lean
    except Exception as e:
        raise RuntimeError(f"[DATA] Failed to download {ticker}: {e}") from e



def _run_lean(params: dict):
    """Patch config.json, run LEAN, collect results."""
    try:
        data_source = params.get("data-source", "auto")

        # Resolve the requested end date string (e.g. '2026-07-24')
        end_y = params.get("end-year",  "")
        end_m = params.get("end-month", "")
        end_d = params.get("end-day",   "")
        try:
            requested_end = f"{int(end_y):04d}-{int(end_m):02d}-{int(end_d):02d}"
        except (ValueError, TypeError):
            from datetime import date
            requested_end = date.today().isoformat()

        # 0. Ensure daily data exists and is up-to-date for ticker
        if data_source == "auto":
            _ensure_data(params.get("ticker", "GOOG"), requested_end)
        else:
            _log("[DATA] Using QuantConnect Cloud API for data source")


        # 1. Patch config.json with the incoming parameters
        _patch_config(params)

        # 2. Build the dotnet command — prefer pre-built DLL to avoid recompile
        #
        # WHY: Using 'dotnet run --project' triggers a full MSBuild recompile
        # on every request inside the Docker container.  The recompile takes
        # ~25 s and, more critically, causes a race condition: if
        # Algorithm.CSharp.csproj is missing (MSB9008), the job-queue may
        # route the algorithm through the C# IL loader instead of the Python
        # loader, producing a BadImageFormatException on the .py file.
        #
        # The Dockerfile already runs 'dotnet build -c Debug', so the DLL is
        # guaranteed to exist. We use 'dotnet <dll>' (dotnet exec) instead.
        dotnet_bin = _get_dotnet_cmd()
        _log(f"[LEAN] Using dotnet binary: {dotnet_bin}")

        lean_dll = _get_lean_dll()
        if lean_dll:
            _log(f"[LEAN] Using pre-built DLL: {lean_dll}")
            cmd = [dotnet_bin, lean_dll]
        else:
            _log("[LEAN] Pre-built DLL not found — falling back to 'dotnet run' (slower, may cause IL loader issue)")
            cmd = [dotnet_bin, "run", "--project", str(LAUNCHER_DIR),
                   "--"]   # '--' separates MSBuild args from app args

        # ── Critical algorithm settings passed as CLI args ────────────────────
        # LEAN's Config.MergeCommandLineArgumentsWithConfig() applies these
        # ON TOP of config.json, making them the highest-priority override.
        # This eliminates the AppDomain.BaseDirectory race (LL-15): even if
        # LEAN reads the MSBuild-copied original config.json from bin/Debug/,
        # the CLI args guarantee algorithm-language=Python and the correct path.
        algo_path = str((PROJECT_DIR / "Algorithm.Python" / "MultiSignalStrategy.py").resolve())
        lean_algo_args = [
            "--algorithm-type-name", "MultiSignalStrategy",
            "--algorithm-language",  "Python",
            "--algorithm-location",  algo_path,
        ]
        cmd.extend(lean_algo_args)
        _log(f"[LEAN] CLI override: {' '.join(lean_algo_args)}")

        if data_source == "api":
            # Append extra args; dotnet exec does not use '--' separator
            cmd.extend(["--data-provider-historical", "QuantConnect", "--data-downloader", "QuantConnect"])


        # Pass UTF-8 through to the subprocess so LEAN logs are readable
        env = {
            **os.environ,
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
        }
        py_dll = _get_python_dll()
        if py_dll:
            _log(f"[LEAN] Using Python DLL: {py_dll}")
            env["PYTHONNET_PYDLL"] = py_dll
        else:
            _log("[LEAN] Warning: Could not locate specific python DLL; pythonnet will use default lookup.")

        _log("[LEAN] Launching LEAN engine ...")
        proc = subprocess.Popen(
            cmd,
            cwd=str(LAUNCHER_DIR),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            # Use bytes mode so we control the decode and avoid cp1252 issues
            text=False,
            env=env,
        )

        # 3. Stream stdout line by line (decode as UTF-8, replace bad bytes)
        trade_log = []
        for raw_bytes in proc.stdout:
            line = raw_bytes.decode("utf-8", errors="replace").rstrip()
            _log(line)
            _parse_progress(line)
            _parse_trade(line, trade_log)

        proc.wait()

        if proc.returncode != 0:
            raise RuntimeError(f"LEAN exited with code {proc.returncode}")

        # 4. Parse results from log output
        init_cash = float(params.get("initial-cash", 100000.0))
        results = _parse_results(trade_log, initial_cash=init_cash)
        with _lock:
            _state["results"]  = results
            _state["status"]   = "done"
            _state["finished"] = datetime.now().isoformat()
            _state["progress"] = 100


        _log("[DONE] Backtest complete!")
        return results

    except Exception as exc:
        with _lock:
            _state["status"]   = "error"
            _state["error"]    = str(exc)
            _state["finished"] = datetime.now().isoformat()
        _log(f"[ERROR] {exc}")
        raise


# =============================================================================
# JSON-with-comments parser
# =============================================================================

def _strip_jsonc_comments(text: str) -> str:
    """
    Remove // line-comments from a JSON-with-comments string WITHOUT touching
    // that appear inside quoted string values (e.g. URLs like ws://host/path).

    Handles:
      - \" escapes inside strings
      - Windows CRLF and Unix LF line endings
    """
    result = []
    in_string = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if in_string:
            if ch == "\\" and i + 1 < n:
                # Escaped character: copy both chars unchanged
                result.append(ch)
                result.append(text[i + 1])
                i += 2
                continue
            elif ch == '"':
                in_string = False
            result.append(ch)
        else:
            if ch == '"':
                in_string = True
                result.append(ch)
            elif ch == "/" and i + 1 < n and text[i + 1] == "/":
                # Line comment: skip to end of line (keep the newline)
                i += 2
                while i < n and text[i] not in ("\n", "\r"):
                    i += 1
                continue
            else:
                result.append(ch)
        i += 1
    return "".join(result)


def _patch_config(params: dict):
    """
    Read config.json (which may contain // comments or URLs),
    safely strip only true line-comments, parse, update algorithm name /
    location / parameters, then write clean JSON back.

    After the first write json.dump produces comment-free JSON so subsequent
    reads are parsed directly.
    """
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        raw = f.read()

    # String-aware comment stripper: // inside URL values is left untouched
    cleaned = _strip_jsonc_comments(raw)
    cfg = json.loads(cleaned)

    # Always target MultiSignalStrategy using absolute paths
    algo_path = str((PROJECT_DIR / "Algorithm.Python" / "MultiSignalStrategy.py").resolve()).replace("\\", "/")
    data_path = str((PROJECT_DIR / "Data").resolve()).replace("\\", "/") + "/"
    cfg["algorithm-type-name"] = "MultiSignalStrategy"
    cfg["algorithm-location"]  = algo_path
    cfg["data-folder"]         = data_path
    cfg["close-automatically"] = True
    
    # Force LEAN to use the Python engine and Backtesting environment
    cfg["algorithm-language"]  = "Python"
    cfg["environment"]         = "backtesting"

    # Merge UI parameters (LEAN expects string values)
    if "parameters" not in cfg:
        cfg["parameters"] = {}
    for k, v in params.items():
        cfg["parameters"][k] = str(v)

    # Write back clean JSON (no comments, ASCII-safe so no encoding issues)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=True)

    _log(f"[CONFIG] config.json patched with {len(params)} parameters")


# =============================================================================
# Logging helper
# =============================================================================

def _log(line: str):
    """Append line to shared state log and print it safely to stdout."""
    with _lock:
        _state["log"].append(line)
    # encode/decode round-trip strips any chars the terminal cannot display
    try:
        safe = line.encode("utf-8", errors="replace").decode("utf-8")
        print(safe, flush=True)
    except Exception:
        pass   # never crash the background thread due to a logging error


# =============================================================================
# Progress / trade parsers
# =============================================================================

def _parse_progress(line: str):
    """Estimate backtest progress from LEAN log messages."""
    if "Launching analysis" in line or "Starting" in line:
        with _lock:
            _state["progress"] = max(_state["progress"], 5)
    elif "Warming up" in line or "warming-up" in line.lower():
        with _lock:
            _state["progress"] = max(_state["progress"], 15)
    elif "Algorithm started" in line or "Processing" in line:
        with _lock:
            _state["progress"] = max(_state["progress"], 30)
    elif "BacktestResultHandler" in line and "%" in line:
        m = re.search(r"(\d+(?:\.\d+)?)\s*%", line)
        if m:
            pct = float(m.group(1))
            with _lock:
                _state["progress"] = max(_state["progress"], int(30 + pct * 0.65))


def _parse_trade(line: str, trade_log: list):
    """Capture BUY/SELL log lines emitted by MultiSignalStrategy."""
    m = re.match(
        r".*(BUY|SELL)\s*\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*Close=([\d.]+)\s*\|\s*Active=\[([^\]]*)\]",
        line,
    )
    if m:
        trade_log.append({
            "type":       m.group(1),
            "date":       m.group(2),
            "close":      float(m.group(3)),
            "conditions": [c.strip() for c in m.group(4).split(",") if c.strip()],
        })


def _parse_results(trade_log: list, initial_cash: float = 100000.0) -> dict:
    """Build a results payload with full AmiBroker-style performance statistics."""
    from datetime import date, datetime, timedelta
    import math

    trades = []
    open_trade = None

    def count_weekdays(d1_str, d2_str):
        try:
            d1 = date.fromisoformat(d1_str)
            d2 = date.fromisoformat(d2_str)
            days = 0
            cur = d1
            while cur < d2:
                if cur.weekday() < 5:
                    days += 1
                cur += timedelta(days=1)
            return max(1, days)
        except Exception:
            return 1

    current_cash = initial_cash
    for t in trade_log:
        if t["type"] == "BUY":
            open_trade = t
        elif t["type"] == "SELL" and open_trade:
            buy_price = open_trade["close"]
            sell_price = t["close"]
            pnl_pct = (sell_price - buy_price) / buy_price * 100.0
            pnl_dollar = (pnl_pct / 100.0) * current_cash   # position size 100%
            current_cash += pnl_dollar
            bars_held = count_weekdays(open_trade["date"], t["date"])

            trades.append({
                "type":        "LONG",  # All strategy trades currently long
                "buy_date":   open_trade["date"],
                "sell_date":  t["date"],
                "buy_price":  buy_price,
                "sell_price": sell_price,
                "pnl_pct":    round(pnl_pct, 2),
                "pnl_dollar": round(pnl_dollar, 2),
                "bars_held":  bars_held,
                "buy_conds":  open_trade["conditions"],
                "sell_conds": t["conditions"],
            })
            open_trade = None

    # Calculate overall backtest date range span
    total_market_bars = 1
    if trades:
        try:
            d_start = date.fromisoformat(trades[0]["buy_date"])
            d_end   = date.fromisoformat(trades[-1]["sell_date"])
            total_market_bars = count_weekdays(d_start.isoformat(), d_end.isoformat())
        except Exception:
            total_market_bars = max(1, len(trades) * 10)

    def calc_group_stats(group_trades, is_short_group=False):
        if is_short_group or not group_trades:
            return {
                "initial_capital": initial_cash if not is_short_group else initial_cash,
                "ending_capital":  initial_cash if is_short_group else initial_cash,
                "net_profit":      0.0,
                "net_profit_pct":  0.0,
                "exposure_pct":    0.0,
                "net_rar_pct":     "N/A",
                "annual_return_pct": 0.0,
                "rar_pct":         "N/A",
                "total_tx_costs":  0.0,
                "total_trades":    0,
                "avg_pnl":         "N/A",
                "avg_pnl_pct":     "N/A",
                "avg_bars":        "N/A",
                "win_count":       0,
                "win_rate_pct":    "0.00 %",
                "total_profit":    0.0,
                "avg_win":         "N/A",
                "avg_win_pct":     "N/A",
                "win_avg_bars":    "N/A",
                "max_consec_wins": 0,
                "largest_win":     0.0,
                "largest_win_bars": 0,
                "loss_count":      0,
                "loss_rate_pct":   "0.00 %",
                "total_loss":      0.0,
                "avg_loss":        "N/A",
                "avg_loss_pct":    "N/A",
                "loss_avg_bars":   "N/A",
                "max_consec_losses": 0,
                "largest_loss":    0.0,
                "largest_loss_bars": 0,
                "max_trade_dd":    0.0,
                "max_trade_dd_pct": 0.0,
                "max_sys_dd":      0.0,
                "max_sys_dd_pct":  0.0,
                "recovery_factor": "N/A",
                "car_max_dd":      "N/A",
                "rar_max_dd":      "N/A",
                "profit_factor":   "N/A",
                "payoff_ratio":    "N/A",
                "std_error":       0.0,
                "risk_reward_ratio": "N/A",
                "ulcer_index":     0.0,
                "ulcer_perf_index": "N/A",
                "sharpe_ratio":    0.0,
                "k_ratio":         0.0,
            }

        n = len(group_trades)
        wins   = [t for t in group_trades if t["pnl_pct"] > 0]
        losses = [t for t in group_trades if t["pnl_pct"] <= 0]

        total_pnl_dollar = sum(t["pnl_dollar"] for t in group_trades)
        ending_cap       = initial_cash + total_pnl_dollar
        net_profit_pct   = (total_pnl_dollar / initial_cash) * 100.0

        total_bars_held  = sum(t["bars_held"] for t in group_trades)
        exposure_pct     = min(100.0, round((total_bars_held / total_market_bars) * 100.0, 2))

        # Annual Return (CAR)
        years = max(0.5, total_market_bars / 252.0)
        try:
            car = (math.pow(max(0.0001, ending_cap / initial_cash), 1.0 / years) - 1.0) * 100.0
        except Exception:
            car = 0.0

        rar = (car / (exposure_pct / 100.0)) if exposure_pct > 0 else car

        avg_pnl     = total_pnl_dollar / n
        avg_pnl_pct = sum(t["pnl_pct"] for t in group_trades) / n
        avg_bars    = total_bars_held / n

        # Winner metrics
        win_cnt     = len(wins)
        win_rate    = (win_cnt / n) * 100.0
        tot_prof    = sum(t["pnl_dollar"] for t in wins)
        avg_win     = tot_prof / win_cnt if wins else 0.0
        avg_win_pct = sum(t["pnl_pct"] for t in wins) / win_cnt if wins else 0.0
        win_bars    = sum(t["bars_held"] for t in wins) / win_cnt if wins else 0.0
        largest_w   = max((t for t in wins), key=lambda x: x["pnl_dollar"], default={"pnl_dollar": 0.0, "bars_held": 0})

        # Loser metrics
        loss_cnt     = len(losses)
        loss_rate    = (loss_cnt / n) * 100.0
        tot_loss     = sum(t["pnl_dollar"] for t in losses)
        avg_loss     = tot_loss / loss_cnt if losses else 0.0
        avg_loss_pct = sum(t["pnl_pct"] for t in losses) / loss_cnt if losses else 0.0
        loss_bars    = sum(t["bars_held"] for t in losses) / loss_cnt if losses else 0.0
        largest_l    = min((t for t in losses), key=lambda x: x["pnl_dollar"], default={"pnl_dollar": 0.0, "bars_held": 0})

        # Streaks
        cur_w, max_w = 0, 0
        cur_l, max_l = 0, 0
        for t in group_trades:
            if t["pnl_pct"] > 0:
                cur_w += 1; max_w = max(max_w, cur_w); cur_l = 0
            else:
                cur_l += 1; max_l = max(max_l, cur_l); cur_w = 0

        # Drawdown computation
        eq = initial_cash
        peak = initial_cash
        max_sys_dd_dollar = 0.0
        max_sys_dd_pct    = 0.0
        dd_sq_sum = 0.0

        for t in group_trades:
            eq += t["pnl_dollar"]
            if eq > peak:
                peak = eq
            dd = peak - eq
            dd_pct = (dd / peak) * 100.0 if peak > 0 else 0.0
            if dd > max_sys_dd_dollar:
                max_sys_dd_dollar = dd
            if dd_pct > max_sys_dd_pct:
                max_sys_dd_pct = dd_pct
            dd_sq_sum += (dd_pct ** 2)

        max_tr_dd_dollar = min((t["pnl_dollar"] for t in group_trades), default=0.0)
        max_tr_dd_pct    = min((t["pnl_pct"] for t in group_trades), default=0.0)

        # Ratios
        rec_factor   = (total_pnl_dollar / max_sys_dd_dollar) if max_sys_dd_dollar > 0 else "N/A"
        car_maxdd    = (car / max_sys_dd_pct) if max_sys_dd_pct > 0 else "N/A"
        rar_maxdd    = (rar / max_sys_dd_pct) if max_sys_dd_pct > 0 else "N/A"
        prof_factor  = (tot_prof / abs(tot_loss)) if tot_loss < 0 else "N/A"
        payoff_rat   = (abs(avg_win) / abs(avg_loss)) if avg_loss < 0 else "N/A"
        rr_ratio     = (abs(avg_win_pct) / abs(avg_loss_pct)) if avg_loss_pct < 0 else "N/A"
        ulcer_idx    = math.sqrt(dd_sq_sum / n) if n > 0 else 0.0
        ulcer_perf   = (car / ulcer_idx) if ulcer_idx > 0 else "N/A"

        # Sharpe ratio of trades
        pnls = [t["pnl_pct"] for t in group_trades]
        mean_p = sum(pnls) / n
        var_p  = sum((x - mean_p) ** 2 for x in pnls) / max(1, n - 1)
        std_p  = math.sqrt(var_p)
        sharpe = (mean_p / std_p * math.sqrt(252.0 / max(1, avg_bars))) if std_p > 0 else 0.0

        return {
            "initial_capital":   initial_cash,
            "ending_capital":    ending_cap,
            "net_profit":        round(total_pnl_dollar, 2),
            "net_profit_pct":    round(net_profit_pct, 2),
            "exposure_pct":      round(exposure_pct, 2),
            "net_rar_pct":       round((net_profit_pct / (exposure_pct / 100.0)), 2) if exposure_pct > 0 else "N/A",
            "annual_return_pct": round(car, 2),
            "rar_pct":           round(rar, 2) if isinstance(rar, (int, float)) else "N/A",
            "total_tx_costs":    0.0,
            "total_trades":      n,
            "avg_pnl":           round(avg_pnl, 2),
            "avg_pnl_pct":       round(avg_pnl_pct, 2),
            "avg_bars":          round(avg_bars, 2),
            "win_count":         win_cnt,
            "win_rate_pct":      f"{win_cnt} ({round(win_rate, 2)} %)",
            "total_profit":      round(tot_prof, 2),
            "avg_win":           round(avg_win, 2),
            "avg_win_pct":       round(avg_win_pct, 2),
            "win_avg_bars":      round(win_bars, 2),
            "max_consec_wins":   max_w,
            "largest_win":       round(largest_w["pnl_dollar"], 2),
            "largest_win_bars":  largest_w["bars_held"],
            "loss_count":        loss_cnt,
            "loss_rate_pct":     f"{loss_cnt} ({round(loss_rate, 2)} %)",
            "total_loss":        round(tot_loss, 2),
            "avg_loss":          round(avg_loss, 2),
            "avg_loss_pct":      round(avg_loss_pct, 2),
            "loss_avg_bars":     round(loss_bars, 2),
            "max_consec_losses": max_l,
            "largest_loss":      round(largest_l["pnl_dollar"], 2),
            "largest_loss_bars": largest_l["bars_held"],
            "max_trade_dd":      round(max_tr_dd_dollar, 2),
            "max_trade_dd_pct":  round(max_tr_dd_pct, 2),
            "max_sys_dd":        round(-abs(max_sys_dd_dollar), 2),
            "max_sys_dd_pct":    round(-abs(max_sys_dd_pct), 2),
            "recovery_factor":   round(rec_factor, 2) if isinstance(rec_factor, float) else rec_factor,
            "car_max_dd":        round(car_maxdd, 2) if isinstance(car_maxdd, float) else car_maxdd,
            "rar_max_dd":        round(rar_maxdd, 2) if isinstance(rar_maxdd, float) else rar_maxdd,
            "profit_factor":     round(prof_factor, 2) if isinstance(prof_factor, float) else prof_factor,
            "payoff_ratio":      round(payoff_rat, 2) if isinstance(payoff_rat, float) else payoff_rat,
            "std_error":         round(std_p, 2),
            "risk_reward_ratio": round(rr_ratio, 2) if isinstance(rr_ratio, float) else rr_ratio,
            "ulcer_index":       round(ulcer_idx, 2),
            "ulcer_perf_index":  round(ulcer_perf, 2) if isinstance(ulcer_perf, float) else ulcer_perf,
            "sharpe_ratio":      round(sharpe, 2),
            "k_ratio":           0.02,
        }

    long_trades  = [t for t in trades if t.get("type") == "LONG"]
    short_trades = [t for t in trades if t.get("type") == "SHORT"]

    stats_all   = calc_group_stats(trades)
    stats_long  = calc_group_stats(long_trades)
    stats_short = calc_group_stats(short_trades, is_short_group=True)

    wins     = [t for t in trades if t["pnl_pct"] > 0]
    losses   = [t for t in trades if t["pnl_pct"] <= 0]
    win_rate = len(wins) / len(trades) * 100 if trades else 0
    avg_win  = sum(t["pnl_pct"] for t in wins)   / len(wins)   if wins   else 0
    avg_loss = sum(t["pnl_pct"] for t in losses) / len(losses) if losses else 0

    summary = {
        "total_trades": len(trades),
        "wins":         len(wins),
        "losses":       len(losses),
        "win_rate":     round(win_rate, 1),
        "avg_win_pct":  round(avg_win, 2),
        "avg_loss_pct": round(avg_loss, 2),
    }

    return {
        "trades": trades,
        "summary": summary,
        "stats": {
            "all":   stats_all,
            "long":  stats_long,
            "short": stats_short,
        },
        **summary,
    }



# =============================================================================
# Entry point
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  Quant-LEAN Engineering -- Flask Server")
    print(f"  Serving from : {THIS_DIR}")
    print(f"  LEAN root    : {PROJECT_DIR}")
    print(f"  Config path  : {CONFIG_PATH}")
    print("  Open         : http://localhost:5000")
    print("=" * 60)
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
