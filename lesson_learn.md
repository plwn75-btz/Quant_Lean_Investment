# Lessons Learned — Quant-LEAN Engineering UI & Strategy
**Project:** QuantConnect Multi-Signal Strategy & Interactive UI
**Last Updated:** 27 Jul 2026

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

## LL-10: Forked Repository `.gitignore` Conflicts
**Problem:** Forking or cloning the official QuantConnect/Lean repository inherits an aggressive `.gitignore` with broad wildcard patterns (e.g., `*Data/*`, `*/bin/*`, `*.sh`). When adding custom project files (like `backtest_ui/`, `MultiSignalStrategy.py`, `Dockerfile.render`), these files are **silently ignored by Git** — `git add` appears to succeed but the files never make it into the commit. Pushing to GitHub results in a repository that is missing critical application files, causing downstream Docker builds to fail with "No such file or directory" errors.
**Fix:** Added explicit whitelist rules at the bottom of `.gitignore` using the `!` negation prefix:
```
!backtest_ui/
!backtest_ui/**
!Algorithm.Python/MultiSignalStrategy.py
!Dockerfile.render
```
**Lesson:** When building on top of a forked open-source repository, **always audit the inherited `.gitignore`** before your first commit. Use `git check-ignore -v <file>` to diagnose why files are not being tracked, and add targeted `!` negation rules rather than removing upstream ignore patterns.

## LL-11: Multi-Runtime Docker Images for Hybrid Projects
**Problem:** The Quant-LEAN dashboard requires both **Python** (Flask server, yfinance data download) and **.NET SDK** (to compile and run the LEAN C# engine via `dotnet run`). Standard cloud platforms like Render.com only provide single-language runtimes by default.
**Fix:** Used `quantconnect/lean:foundation` as the Docker base image, which ships with .NET SDK, Python 3.11, and TA-Lib pre-installed. The `Dockerfile.render` uses explicit `COPY` instructions for each required LEAN project directory and runs `dotnet restore && dotnet build` during the image build to pre-compile the Launcher.
**Lesson:** For hybrid-runtime projects, always look for an official foundation image from the upstream project before attempting to build a custom multi-SDK Docker image from scratch. Also use explicit per-directory `COPY` statements instead of `COPY . /app/` to maintain fine-grained control over what enters the container and to leverage Docker layer caching.

## LL-12: Render.com PORT Binding & Git Branch Mapping
**Problem:** Render.com injects a `PORT` environment variable at runtime and expects the application to bind to it. Hardcoding `port=5000` causes the health check to fail and the service to never become "live." Additionally, the local Git branch was `master` while the GitHub remote expected `main`, and the `origin` remote was still pointing to the upstream `QuantConnect/Lean` repository instead of the user's fork.
**Fix:**
1. Updated `server.py` to use `port = int(os.environ.get("PORT", 5000))`.
2. Changed the remote URL: `git remote set-url origin https://github.com/plwn75-btz/Quant_Lean_Investment.git`.
3. Used `git push origin master:main` to map the local `master` branch to the remote `main` branch.
**Lesson:** When deploying to PaaS platforms (Render, Heroku, Railway), always bind to the `PORT` environment variable. When working with forked repos, verify `git remote -v` before pushing — the remote URL often still points to the original upstream repository. Use `git push origin <local-branch>:<remote-branch>` when branch names differ.

## LL-13: `dotnet run` vs `dotnet exec` — IL Loader Race Condition in Docker
**Problem:** `server.py` used `dotnet run --project Launcher/` to execute LEAN. Inside the Docker container this triggers a **full MSBuild recompile on every backtest request** (~25 s). During recompile, `Algorithm.CSharp.csproj` is referenced but absent (MSB9008 warning), which causes the LEAN job-queue to route the Python `.py` file through the **C# IL assembly loader** instead of the Python loader. The result is a fatal `System.BadImageFormatException: Bad IL format` on `MultiSignalStrategy.py`, and the backtest exits with code 1 after ~90 seconds producing zero trades.
**Fix:**
1. Added `_get_lean_dll()` to `server.py` — scans `Launcher/bin/Debug/*/*.dll` and `Launcher/bin/Release/*/*.dll` for the pre-built launcher DLL.
2. Switched the execution command to `dotnet <dll_path>` (equivalent to `dotnet exec`) when the DLL is found. This skips all recompilation, loads config.json only **after** `_patch_config()` has written it, and always activates the correct Python loader via `algorithm-language: "Python"`.
3. Removed the silent `|| echo "LEAN build skipped"` from `Dockerfile.render` so build failures are surfaced during image build rather than silently deferred to runtime.
4. Added a DLL existence verification step in `Dockerfile.render` (`find /app/Launcher/bin ... && test -n ...`) so a missing DLL fails the Docker build early.
**Lesson:** Never use `dotnet run --project` in a production container if the DLL is already pre-built. Always prefer `dotnet exec <dll>` or `dotnet <dll>` to bypass MSBuild entirely. The missing C# project reference (MSB9008) is a silent build warning that turns into a fatal runtime error via the wrong loader path.

## LL-14: Yahoo Finance Rate Limiting on Cloud Server IPs
**Problem:** On Render.com, the outbound IP of the container is shared across many tenants. Yahoo Finance aggressively rate-limits shared cloud IPs, causing `YFRateLimitError('Too Many Requests')` on the first download attempt. The original `_ensure_data()` simply logged `[DATA] ERROR: No data returned` and returned silently — LEAN then launched with no market data, produced zero trades, and the UI showed a misleading "0 trades" result with no error message.
**Fix:**
1. Wrapped the `yf.download()` call in a retry loop (max 3 attempts) with **exponential backoff + random jitter** (2, 4+ seconds between retries).
2. After all retries are exhausted with an empty result, `_ensure_data()` now raises `RuntimeError` with a human-readable message instead of silently returning. This propagates to `_run_lean()` and is returned as a 500 response with the clear message: *"No market data available for 'X' after 3 attempts. Yahoo Finance may be rate-limiting this server IP..."*
**Lesson:** Cloud platform IPs are frequently pre-blocked or heavily rate-limited by external APIs. Always implement retry-with-backoff, and **always surface a hard error rather than proceeding with empty data**. A silent "0 trades" result is far worse than a clear failure message.

## LL-15: LEAN `AppDomain.BaseDirectory` Config Fallback — CLI Args Are the Only Guarantee
**Problem:** Even after switching to `dotnet exec` (pre-built DLL), the `TryCreateILAlgorithm` error can still occur via a second failure path. LEAN's `Config.cs` reads `config.json` using a two-step lookup:
1. `Directory.GetCurrentDirectory() + "/config.json"` (our patched file at `/app/Launcher/config.json`)
2. `AppDomain.CurrentDomain.BaseDirectory + "/config.json"` (MSBuild output copy at `/app/Launcher/bin/Debug/net*/config.json`)

When `dotnet run` is used (e.g., as a fallback when the pre-built DLL isn't found), MSBuild copies the **original unpatched `config.json`** from the repo into `bin/Debug/net*/` via a `CopyToOutputDirectory` rule in the `.csproj`. If the CWD lookup fails for any reason — race condition, Docker path quirk, SDK version difference — LEAN silently falls back to the output-directory copy, which has `algorithm-language: "CSharp"` as the default. This routes the `.py` file through the C# IL assembly loader (`TryCreateILAlgorithm`) and produces `System.BadImageFormatException: Bad IL format` without ever trying the Python loader.

**Root cause chain:**
```
MSBuild copies config.json to bin/Debug/ → LEAN AppDomain fallback reads it
    → algorithm-language defaults to "CSharp"
    → JobQueue.Language = Language.CSharp
    → Loader._language = Language.CSharp  
    → TryCreateILAlgorithm fires on .py file
    → BadImageFormatException
    → TryCreatePythonAlgorithm is NEVER called
```

**Fix:** Pass `--algorithm-language Python --algorithm-type-name MultiSignalStrategy --algorithm-location <path>` as **explicit CLI arguments** to the LEAN process. LEAN's startup sequence merges CLI args ON TOP of config.json via `Config.MergeCommandLineArgumentsWithConfig()`, making CLI args the highest-priority override. This eliminates the config file race entirely — Python loader is guaranteed regardless of which config.json LEAN reads.
- For `dotnet exec <dll>`: args are passed directly after the DLL path.
- For `dotnet run` fallback: args are passed after `--` separator (MSBuild boundary).

**Lesson:** Never rely solely on a config file for critical runtime settings in Docker. Always reinforce the most critical settings (algorithm language, algorithm path) as **command-line arguments** to the subprocess. Config files can be overwritten, cached, or read from an unexpected path; CLI args cannot be silently overridden.

## LL-16: Pre-Bundle Ticker Data at Docker Build Time to Bypass Runtime Rate-Limiting
**Problem:** Render.com assigns persistent outbound IPs to its web services. Over time, these IPs get rate-limited by Yahoo Finance because many other tenants use the same IP pool. Any runtime download of a new ticker will fail with `YFRateLimitError`, and even the retry logic (LL-14) exhausts all attempts. For Thai SET tickers (`AOT.BK`, `PTT.BK`, etc.) this is especially problematic since they are always "new" on a fresh container.
**Fix:** Add a `RUN python3 -c "import yfinance..."` step in `Dockerfile.render` to pre-download common tickers (GOOG, AAPL, AOT.BK, PTT.BK, SCB.BK, KBANK.BK) during the Docker **image build phase**. Docker build runs on ephemeral builder IPs (not the service's persistent IP), which are far less likely to be pre-blocked. The resulting `.zip` files are baked into the image layers and available immediately at container startup.
- The existing stale-data check in `_ensure_data()` still handles re-downloads for expired cached data (>5 days behind requested end date).
- Build failures for individual tickers are non-fatal (the script logs `WARN:` and continues), so a single unavailable ticker does not block the image build.
**Lesson:** For cloud deployments where runtime network access to external APIs is unreliable, move data acquisition to build time where possible. Docker build environments use transient IPs with clean rate-limit histories, making them far more reliable for bulk data fetches than persistent server IPs.

## LL-17: JobQueue Readonly Field Initialization Trap
**Problem:** The `System.BadImageFormatException` (IL loader attempting to load Python scripts) persisted even after adding CLI overrides like `--algorithm-language Python`.
**Root cause:** The LEAN `JobQueue` class declares `AlgorithmLocation` and `AlgorithmTypeName` as `readonly` fields that read from `Config` at *class instantiation time*. Because `JobQueue` is instantiated by `Composer` *before* `Program.Main()` calls `Config.MergeCommandLineArgumentsWithConfig()`, these fields freeze their values using the unpatched `config.json` (read from `AppDomain.BaseDirectory` i.e. `bin/Debug/net*/`). This causes `AlgorithmLocation` to fall back to the default `QuantConnect.Algorithm.CSharp.dll`. Later, the `Language` property dynamically checks `algorithm-language`; if empty, it infers the language from the `.dll` extension of `AlgorithmLocation`, permanently locking the engine into C# IL mode.
**Fix:** Modified `server.py` `_patch_config()` to write the patched `config.json` to BOTH the source directory (`/app/Launcher/config.json`) AND all MSBuild output directories (`/app/Launcher/bin/Debug/*/*/config.json`). This ensures that regardless of whether LEAN reads the config from CWD or `AppDomain.BaseDirectory`, it sees `algorithm-language: Python` before `JobQueue` is instantiated.
**Lesson:** CLI arguments are merged too late for fields initialized at class construction via dependency injection/Composer. When modifying configuration for older or complex .NET systems, patching the physical configuration file at all possible read locations is the only guaranteed way to affect startup state.

## LL-18: Python Cannot Find AlgorithmImports.py
**Problem:** After fixing the C# IL loader fallback issue, LEAN threw a new exception: `No module named 'AlgorithmImports'` when initializing the Python engine.
**Root cause:** LEAN copies `AlgorithmImports.py` to the build output directory (e.g. `Launcher/bin/Debug/net*`) during the `dotnet build` step. At runtime, `PythonInitializer` automatically appends `Environment.CurrentDirectory` and the algorithm directory to `sys.path`. Because we execute `dotnet exec` with the working directory set to `/app/Launcher`, Python does not automatically search the MSBuild `bin/Debug` folders where the DLL and `AlgorithmImports.py` actually reside.
**Fix:** Modified `server.py` `_patch_config()` to detect the physical directory containing the pre-built `QuantConnect.Lean.Launcher.dll` and dynamically append it to the `python-additional-paths` array in `config.json` before launch.
**Lesson:** Bypassing `dotnet run` in favor of `dotnet exec` alters the default paths LEAN injects into Python. You must explicitly configure `python-additional-paths` in `config.json` to include the output directory so Python can resolve internally bundled modules like `AlgorithmImports.py`.

## LL-19: Synchronous Subprocess Blocking in Single-Threaded WSGI Server
**Problem:** Running `_run_lean()` directly inside the HTTP `POST /api/run-backtest` request handler blocks the Werkzeug dev server event loop. On cloud platforms like Render.com, long execution times cause HTTP proxy timeouts, drop connections, and prevent frontend status polling (`/api/status`) from acquiring `_lock`.
**Fix:**
1. Refactored `api_run_backtest()` to spawn `_run_lean()` in a background daemon thread (`threading.Thread`) and return HTTP `202 Accepted` immediately (~50ms).
2. Deployed multi-worker `gunicorn` (`--workers 2 --threads 4`) in `Dockerfile.render` to process concurrent requests smoothly.
**Lesson:** Never run heavy subprocess calls or long-running computations directly on an HTTP request thread. Launch background workers and stream progress to the UI via asynchronous polling endpoints.

## LL-20: Soft Fallback for Cached Market Data on API Rate Limiting
**Problem:** When `_ensure_data()` detected a cached `.zip` file with a last bar >5 days old, it deleted the zip file before attempting to download fresh data from Yahoo Finance. On Render.com, shared outbound server IPs are aggressively rate-limited by Yahoo Finance. If the download failed, the user was left with no data file at all, causing a hard crash.
**Fix:** Retain cached zip files during refresh attempts. If Yahoo Finance rate-limits or returns an empty result, log a warning and fall back to using the existing cached data file instead of failing.
**Lesson:** Never delete cached data until a replacement has been successfully downloaded and validated. Preserving slightly older data allows backtests to proceed safely when external APIs are rate-limited or unreachable.

## LL-21: Signal Bar Close vs Fill Price Order Execution Divergence
**Problem:** In `MultiSignalStrategy.py`, trade log entries capture `Close` prices when a signal fires (`BUY | Close=X`). LEAN's engine executes market orders on the *next bar's Open* price (or fill price). On volatile assets, computing multi-year compounded trade returns using signal-bar Close prices introduces minor variance compared to LEAN's native `End Equity` report.
**Lesson:** For 100% exact mathematical matching between external UI calculators and LEAN's C# engine portfolio report, record actual execution prices from LEAN's `OnOrderEvent` handler (`orderEvent.FillPrice`) rather than bar close prices.

## LL-22: Non-Nested `bin/Debug` DLL Path Glob Mismatch & `AlgorithmImports` Fallback Cascade
**Problem:** In Docker container environment on Render.com, `QuantConnect.Lean.Launcher.csproj` builds output directly to `Launcher/bin/Debug/QuantConnect.Lean.Launcher.dll` because `<AppendTargetFrameworkToOutputPath>false</AppendTargetFrameworkToOutputPath>` is specified in the `.csproj`.
The helper function `_get_lean_dll()` previously used `Launcher/bin/Debug/*/QuantConnect.Lean.Launcher.dll` (expecting a target framework subdirectory like `net10.0`). Because there was no middle directory, `_get_lean_dll()` returned `None`.
This triggered a 2-step cascade failure:
1. `server.py` fell back to `dotnet run`, triggering slow runtime recompiles and MSB9008 warnings.
2. Because `dll_path` was `None`, `python-additional-paths` in `config.json` was NOT updated with the output folder. Python failed with `No module named 'AlgorithmImports'`.
**Fix:**
1. Updated `_get_lean_dll()` glob patterns to include both non-nested (`Launcher/bin/Debug/QuantConnect.Lean.Launcher.dll`) and nested (`Launcher/bin/Debug/*/QuantConnect.Lean.Launcher.dll`) paths.
2. Updated `_patch_config()` to unconditionally include `Common/`, `Launcher/bin/Debug/`, `Launcher/bin/Release/`, and `dll_dir` in `python-additional-paths`.
3. Updated `output_configs` patching in `_patch_config()` to include non-nested `config.json` paths.
**Lesson:** Always account for both `<AppendTargetFrameworkToOutputPath>false` (flat `bin/Debug/`) and standard nested (`bin/Debug/net*/`) output structures when scanning for build artifacts in .NET applications. Never rely solely on optional runtime lookups for core Python dependencies—always populate fallback search paths (`Common/`, `bin/Debug/`) in `python-additional-paths`.

## LL-23: `No module named 'QuantConnect.Research'` in Docker & `PythonInitializer` Reversed `sys.path` Ordering
**Problem:** After resolving `AlgorithmImports` module discovery on Render.com, `Loader.TryCreatePythonAlgorithm()` threw `No module named 'QuantConnect.Research'` at `AlgorithmImports.py: line 42` (`from QuantConnect.Research import *`).
**Root cause (3 interconnected factors):**
1. **Missing Project Directories in `Dockerfile.render`:** `Dockerfile.render` used selective per-directory `COPY` statements that omitted `Research/`, `Algorithm.Framework/`, `Optimizer/`, `Optimizer.Launcher/`, and `ToolBox/`. During `dotnet build Launcher/QuantConnect.Lean.Launcher.csproj`, MSBuild emitted `MSB9008` warnings for those missing `<ProjectReference>` targets and skipped building `QuantConnect.Research.dll` and `QuantConnect.Algorithm.Framework.dll`.
2. **Reversed `sys.path.insert(0)` Ordering in `PythonInitializer.cs`:** `Common/Python/PythonInitializer.cs` (lines 143–145) iterates through `python-additional-paths` and executes `sys.path.insert(0, path)` for each item sequentially—which **reverses** their final order in `sys.path`. On Render (where `bin/Release` did not exist), `python-additional-paths` was `['/app/Launcher/bin/Debug', '/app/Common']`, causing `/app/Common` to be inserted at index `0` *after* `bin/Debug`. Python therefore loaded `/app/Common/AlgorithmImports.py` (where `os.listdir(path)` finds **zero** `.dll` files) instead of `/app/Launcher/bin/Debug/AlgorithmImports.py`.
3. **Hard Import of Optional Assemblies in `AlgorithmImports.py`:** `Common/AlgorithmImports.py` only scanned `os.path.dirname(__file__)` for `QuantConnect.*.dll` and performed unguarded `from QuantConnect.Research import *` and `from QuantConnect.Algorithm.Framework import *` imports.
**Fix:**
1. Added `COPY` instructions for `Algorithm.Framework/`, `Research/`, `Optimizer/`, `Optimizer.Launcher/`, `ToolBox/`, and `LICENSE` in `Dockerfile.render`, and updated the stub `Algorithm.CSharp.csproj` to `net10.0` with a reference to `Algorithm.Framework.csproj`.
2. Updated `Common/AlgorithmImports.py` to scan fallback build output directories (`Launcher/bin/Debug`, `Launcher/bin/Release`, `os.getcwd()`) for `QuantConnect.*.dll` assemblies and wrapped optional `QuantConnect.Research` and `QuantConnect.Algorithm.Framework` imports in `try ... except ImportError: pass`.
3. Updated `server.py` `_patch_config()` to place `dll_dir` (`Launcher/bin/Debug`) **last** in `python-additional-paths` (so `PythonInitializer.cs`'s `sys.path.insert(0, ...)` places it **first** in `sys.path`) and automatically sync `Common/AlgorithmImports.py` into `dll_dir`.
**Lesson:** When a C# host injects Python paths via sequential `sys.path.insert(0, p)`, the last item in the config list wins highest priority in `sys.path`. Furthermore, any script that dynamically loads CLR assemblies via `os.listdir(os.path.dirname(__file__))` must always resolve from the compiled binary output directory (`bin/Debug`), never from the C# source directory (`Common/`).

## LL-24: Render BuildKit Disk Exhaustion (`no space left on device` During Image Export)
**Problem:** During the Render.com Docker build, all compilation and ticker caching steps (`#35`–`#38`) succeeded, but the final step (`#39 exporting to image`) failed with `ResourceExhausted: ... write /var/lib/buildkit-root/.../data: no space left on device` while archiving `/app/Data/forex/fxcm/second/eurusd/20140508_quote.zip`.
**Root cause:**
1. Compiling 15+ LEAN `.csproj` projects populates `/root/.nuget/packages/` (~1.5 GB), intermediate `/app/*/obj/` (~600 MB), and duplicate `/app/<subproject>/bin/` output folders (~900 MB) inside the `RUN dotnet restore && dotnet build` layer.
2. Copying the entire `Data/` directory included ~215 MB of unused sample tick/forex/option/future/cfd archives.
3. When BuildKit exports the image layers into a compressed diff tar stream at the end of the build, the combined layer size exceeded the ephemeral builder's disk quota.
**Fix:**
1. Updated `.dockerignore` and `Dockerfile.render` to exclude unused non-equity/high-frequency sample datasets (`Data/option`, `Data/future`, `Data/forex`, `Data/cfd`, `Data/equity/usa/tick`, etc.) and unreferenced heavy projects (`Optimizer`, `Optimizer.Launcher`, `ToolBox`).
2. Disabled `.pdb` symbol generation (`-p:DebugType=none -p:DebugSymbols=false`) and chained cleanup commands (`dotnet nuget locals all --clear`, `rm -rf /root/.nuget /app/*/obj`, and removing all subproject `bin/` directories except `/app/Launcher/bin`) **within the same `RUN` instruction** as `dotnet build`.
**Lesson:** In multi-project .NET Docker builds on cloud PaaS builders with strict disk quotas, always purge NuGet caches, `obj/` directories, and duplicate subproject `bin/` directories within the **same** `RUN` layer as `dotnet build`—deleting files in a subsequent `RUN` instruction does not shrink the previous layer's tar diff.

## LL-25: Render Deployment Duration Breakdown & Optimization Roadmap (~11.5 Min Total)
**Problem:** Although the Render.com deployment succeeded and the service went live, the end-to-end deployment duration took ~11 minutes 36 seconds (`17:31:30Z` to `17:43:06Z`), which is too slow for rapid iteration.
**Timeline & Root Cause Analysis (from Render Build & Deploy Logs):**
1. **Phase 1 — Docker Layer Copy & Setup (`~1s`):** Steps `#1`–`#31` completed almost instantaneously via BuildKit cache and `.dockerignore` filtering.
2. **Phase 2 — C# Compilation & Roslyn Code Analyzers (`74.7s`, `17:31:30Z` → `17:32:45Z`):**
   - Step `#32` (`dotnet restore && dotnet build`) took `74.7s` (`60.39s` inside MSBuild).
   - MSBuild evaluated **3,150 Roslyn code-analysis warnings** (`CA2000`, `CA1031`, `CA1810`, `CA1822`, `CA1307`, etc.) across all LEAN projects because `<AnalysisMode>AllEnabledByDefault</AnalysisMode>` is active in the `.csproj` files, overflowing Render's 2 MiB build log buffer (`[output clipped, log limit 2MiB reached]`).
3. **Phase 3 — Ticker Pre-Warm & Image Registry Push (`15.5s`, `17:32:45Z` → `17:32:55Z`):**
   - Step `#34` (`ticker_cache.py`) took `3.9s`; `#36` (`exporting to image` & `pushing layers`) took `5.2s`; `#37` (`sending cache export`) took `6.0s`.
4. **Phase 4 — Render Runtime Node Image Pull & Extraction (`9m 14s`, `17:33:06Z` → `17:42:20Z` — 80% of Total Time):**
   - Between `==> Deploying...` (`17:33:06Z`) and `Starting gunicorn 23.0.0` (`17:42:20Z`), **9 minutes and 14 seconds** elapsed with no log output.
   - **Root cause:** `Dockerfile.render` uses `FROM quantconnect/lean:foundation` as both its build and runtime image. `quantconnect/lean:foundation` is a massive **~5.5+ GB** monolithic image (containing Miniconda, C++/Boost, Java, R, Julia, .NET SDKs, and hundreds of thousands of files/inodes). When Render transitions from the Build Node to the Runtime Host Node at `==> Deploying...`, the Runtime Host must pull and extract this multi-gigabyte image onto containerd's overlayfs before starting the container.
5. **Phase 5 — Cold-Start Assembly Scan on First Backtest (`13.4s`, `17:42:52Z` → `17:43:06Z`):**
   - `Composer(): Loading Assemblies from /app/Launcher/bin/Debug/` took `13.4s` on the first run due to cold disk I/O scanning 100+ DLLs in `Launcher/bin/Debug/`.

**Actionable Optimization Ideas (For Future Implementation) — Trade-Off Analysis (Pros & Cons):**

1. **Idea 1: Reorder `Dockerfile.render` Layers so Python/UI Edits Skip `dotnet build`**
   - **Mechanism:** Place `COPY backtest_ui/` and `COPY Algorithm.Python/` **after** `RUN dotnet restore && dotnet build`.
   - **Pros:**
     - **Massive Time Savings on Daily Iterations:** Whenever only Python strategies (`MultiSignalStrategy.py`), server logic (`server.py`), or HTML/JS are committed, BuildKit reuses the cached C# layer. Build time drops from ~75s to **0s** for the C# compile step.
     - **Zero Risk / Pure Docker Layering:** Does not alter compiler settings, runtime binaries, or system packages.
     - **Extremely Low Implementation Effort:** Only requires moving 2 lines down in `Dockerfile.render`.
   - **Cons:**
     - **No Impact on Initial or C# Changes:** If a C# file or project file is modified, the full ~75s build must still run.
     - **Does Not Shrink the Image:** Does not reduce the 9m 14s runtime node image pull/unpack phase.

2. **Idea 2: Disable Roslyn Code Analyzers During Docker Build**
   - **Mechanism:** Pass `-p:RunAnalyzers=false -p:RunAnalyzersDuringBuild=false -p:AnalysisMode=None -v q -nologo` to `dotnet build`.
   - **Pros:**
     - **Faster Compilation (~40–50% drop in build time):** Eliminates evaluating 3,150 static analysis rules (`CA2000`, `CA1031`, etc.), reducing MSBuild CPU time from ~60s to ~30–35s.
     - **Clean Build Logs:** Prevents hitting Render's 2 MiB log buffer cap (`[output clipped, log limit 2MiB reached]`), allowing actual compilation errors (if any) to remain visible.
     - **Very Low Implementation Effort:** Single-line argument addition in `Dockerfile.render`.
   - **Cons:**
     - **Bypasses Code Quality Warnings in Docker:** Code quality/style issues won't be flagged during container build (though local IDE/developer builds still catch them).
     - **Does Not Shrink the Image:** Does not affect the 9m 14s runtime pull/unpack phase.

3. **Idea 3: Multi-Stage Docker Build with a Slim Runtime Image (`mcr.microsoft.com/dotnet/runtime:10.0-noble`)**
   - **Mechanism:** Build C# in Stage 1 (`quantconnect/lean:foundation`), then copy only `/app/Launcher/bin/Debug/`, Python files, Data, and UI into a slim .NET runtime + Python 3.11 base (~450 MB).
   - **Pros:**
     - **Solves the 80% Bottleneck (Cuts Deploy Time by ~8 to 9 Minutes):** Shrinks the container image from ~5.5 GB to ~450 MB. Render's `==> Deploying...` phase drops from **9m 14s down to ~30–45s**.
     - **Drastically Reduced Memory & Disk Footprint:** Eliminates gigabytes of unused SDKs, Java/R/Julia runtimes, and Boost libraries from the container filesystem.
     - **Faster Cold Starts:** Quicker container spin-up and less memory overhead on Render's shared tier.
   - **Cons:**
     - **Highest Implementation Effort & Verification Risk:** Must precisely configure the runtime stage with the exact shared native dependencies (`libpython3.11.so`, `pythonnet`, C-runtime libraries) that QuantConnect LEAN relies on. Any missing `.so` dependency could cause runtime errors that require testing.
     - **Initial Build is Slightly Slower:** First build must install Python packages in the slim stage (mitigated by Docker layer caching thereafter).

4. **Idea 4: Strip C# Source Folders Post-Build (Single-Stage Cleanup)**
   - **Mechanism:** Add `rm -rf /app/Engine /app/Brokerages /app/Indicators /app/Algorithm /app/Algorithm.Framework /app/AlgorithmFactory /app/Api /app/Compression /app/Configuration /app/DownloaderDataProvider /app/Logging /app/Messaging /app/Queues /app/Research` at the end of the `RUN dotnet build` layer.
   - **Pros:**
     - **Quick Image Slimming:** Deletes ~150 MB of source `.cs` files and tens of thousands of file inodes before layer export.
     - **Faster Layer Compression & Extraction:** Fewer files for containerd to unpack during deploy.
     - **Zero Runtime Risk for C#:** The compiled binaries in `/app/Launcher/bin/Debug/` already contain all IL code; source files are never read by the engine.
   - **Cons:**
     - **Moderate Impact Only:** Does not remove the underlying foundation OS bloat (~5 GB), so deploy phase might only drop by ~30–60s rather than 8+ minutes.
     - **Must Preserve `Common/AlgorithmImports.py`:** Cleanup script must carefully avoid deleting `AlgorithmImports.py`.

## LL-26: Gunicorn `WORKER TIMEOUT`, Multi-Worker State Desynchronization, & `.NET` Server GC OOM Crash on Render
**Problem:** After running 3–4 sequential stock backtests on Render (`GOOG`, `KCE.BK`, `IVL.BK`, `BBL.BK`), the web dashboard stopped responding. Render logs showed:
1. `[CRITICAL] WORKER TIMEOUT (pid:9)` followed by `Worker (pid:9) was sent SIGKILL! Perhaps out of memory?` during `IVL.BK`.
2. `Isolator.ExecuteWithTimeLimit(): Used: 58, Sample: 91, App: 766` followed by `==> Instance ... restarted` during `BBL.BK`.
**Root cause:**
1. **Gunicorn 30s Default Worker Timeout:** `Dockerfile.render` ran `gunicorn --workers 2 --threads 4` without `--timeout`. When a 6-year daily backtest + indicator warmup saturated Render's shared vCPU for >30s, the worker missed its heartbeat ping to the Gunicorn master and was killed via `SIGKILL`.
2. **Multi-Worker In-Memory State Desync (`--workers 2`):** `_state` in `backtest_ui/server.py` is an in-process Python dictionary. With 2 OS workers (`pid 8` and `pid 9`), `POST /api/run-backtest` mutated `_state` in one worker while half of the browser's 1-second `GET /api/status` polls hit the other idle worker—and also doubled the Flask/Pandas memory footprint (~240 MB).
3. **`.NET` Server GC (`<ServerGarbageCollection>true</ServerGarbageCollection>`) & Unneeded Matplotlib Import:** `Launcher/QuantConnect.Lean.Launcher.csproj` sets `<ServerGarbageCollection>true</ServerGarbageCollection>`, causing `.NET 10.0` to reserve ~766 MB of heap memory (`App: 766`) and hold onto it instead of returning pages to the OS. Combined with two Gunicorn workers and `import matplotlib.pyplot as plt` in `AlgorithmImports.py`, total container memory exceeded Render's 512 MB cgroup limit and triggered the Linux OOM killer.
**Fix:**
1. Changed Gunicorn command in `Dockerfile.render` to `--workers 1 --threads 8 --timeout 300 --graceful-timeout 30` (1 shared-memory worker process, 8 concurrent threads, 5-minute timeout).
2. Compiled `Launcher` with `-p:ServerGarbageCollection=false` and set `DOTNET_gcServer=0`, `DOTNET_GCHeapHardLimit=0x16000000` (~350 MB cap), and `DOTNET_GCHighMemPercent=75` in both `Dockerfile.render` and `server.py`.
3. Guarded `import matplotlib.pyplot as plt` and `from QuantConnect.Research import *` in `Common/AlgorithmImports.py` behind `LEAN_SKIP_MATPLOTLIB=1` / `LEAN_SKIP_RESEARCH=1` environment variables (saving ~60 MB RAM and ~15–20s per backtest import).
4. Added `_active_proc` tracking with `try ... finally` process termination (`_terminate_proc`), explicit `gc.collect()` after `yfinance` downloads and backtest runs, and bounded `_state["log"]` in `backtest_ui/server.py`.
**Lesson:** Never use multi-process Gunicorn (`--workers > 1`) when job state is stored in a Python process global dictionary or on 512 MB containers; use `--workers 1 --threads N --timeout 300`. Always disable `.NET` `ServerGarbageCollection` (`DOTNET_gcServer=0`) in memory-constrained containers.

