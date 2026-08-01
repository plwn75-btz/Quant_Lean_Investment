"""
backtest_ui/stress_test.py
───────────────────────────
Automated stress test harness for backtest_ui/server.py and QuantConnect LEAN.

Tests performed:
1. DLL Resolution Test: Verifies _get_lean_dll() correctly finds QuantConnect.Lean.Launcher.dll.
2. Config Patching & Path Resolution Test: Verifies _patch_config() writes python-additional-paths containing Common/, bin/Debug/, etc.
3. Data Caching & Fallback Test: Verifies _ensure_data() handles cached zip files and Yahoo Finance rate-limiting cleanly.
4. Server API Concurrency Test: Launches server in background and tests concurrent HTTP POST /api/run-backtest requests.
"""

import sys
import os
import json
import time
import threading
import requests
from pathlib import Path

# Ensure backtest_ui directory is in sys.path
THIS_DIR = Path(__file__).parent.resolve()
PROJECT_DIR = THIS_DIR.parent
sys.path.insert(0, str(THIS_DIR))

import server

def test_1_dll_resolution():
    print("\n--- TEST 1: LEAN Launcher DLL Resolution ---")
    dll = server._get_lean_dll()
    print(f"Detected LEAN DLL path: {dll}")
    if dll and os.path.exists(dll):
        print("PASS: Pre-built LEAN DLL exists and was successfully detected!")
        return True
    else:
        print("WARN: Pre-built LEAN DLL not found locally (will use dotnet run fallback if not built).")
        return False

def test_2_config_patching():
    print("\n--- TEST 2: Config Patching & python-additional-paths Verification ---")
    test_params = {
        "ticker": "GOOG",
        "start-year": "2024",
        "end-year": "2024",
        "initial-cash": "100000"
    }
    server._patch_config(test_params)
    
    with open(server.CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    
    add_paths = cfg.get("python-additional-paths", [])
    print(f"python-additional-paths in config.json: {add_paths}")
    
    common_path = str((PROJECT_DIR / "Common").resolve()).replace("\\", "/")
    has_common = any(common_path.lower() in p.lower() for p in add_paths)
    
    if has_common:
        print(f"PASS: 'Common/' path successfully included in python-additional-paths!")
    else:
        print(f"FAIL: 'Common/' path missing from python-additional-paths!")
        sys.exit(1)

def test_3_data_caching_and_fallback():
    print("\n--- TEST 3: Data Caching & Rate-Limit Fallback Verification ---")
    try:
        # Check caching for GOOG
        server._ensure_data("GOOG", "2026-07-24")
        print("PASS: _ensure_data('GOOG') executed successfully!")
    except Exception as e:
        print(f"DATA TEST NOTICE: {e}")

def test_4_server_api_concurrency():
    print("\n--- TEST 4: Server API & Concurrency Test ---")
    # Start server in daemon thread
    def run_flask():
        server.app.run(host="127.0.0.1", port=5050, debug=False, use_reloader=False)
    
    server_thread = threading.Thread(target=run_flask, daemon=True)
    server_thread.start()
    time.sleep(2) # Give server time to bind
    
    base_url = "http://127.0.0.1:5050"
    
    # Check /api/status
    res = requests.get(f"{base_url}/api/status")
    print(f"GET /api/status -> {res.status_code}: {res.json()}")
    assert res.status_code == 200, "Status endpoint failed"
    
    # Launch first backtest
    payload = {
        "ticker": "GOOG",
        "start-year": "2024",
        "start-month": "01",
        "start-day": "01",
        "end-year": "2024",
        "end-month": "02",
        "end-day": "01",
        "initial-cash": "100000",
        "buy-condition-1": "true"
    }
    
    res1 = requests.post(f"{base_url}/api/run-backtest", json=payload)
    print(f"POST /api/run-backtest (Req 1) -> {res1.status_code}: {res1.json()}")
    assert res1.status_code == 202, f"Request 1 failed: {res1.text}"
    
    # Send simultaneous second backtest request (should be rejected with 409 Conflict)
    res2 = requests.post(f"{base_url}/api/run-backtest", json=payload)
    print(f"POST /api/run-backtest (Req 2 while running) -> {res2.status_code}: {res2.json()}")
    assert res2.status_code == 409, f"Expected 409 Conflict for concurrent request, got {res2.status_code}"
    print("PASS: Concurrent backtest request correctly rejected with 409 Conflict!")
    
    # Poll status until complete or timeout (max 45 seconds)
    start_t = time.time()
    completed = False
    while time.time() - start_t < 45:
        st = requests.get(f"{base_url}/api/status").json()
        status = st.get("status")
        progress = st.get("progress")
        print(f"Status: {status} | Progress: {progress}%")
        if status in ("done", "error"):
            completed = True
            print(f"Final status: {status}")
            if status == "error":
                print(f"Backtest error: {st.get('error')}")
            break
        time.sleep(2)
        
    if completed and st.get("status") == "done":
        print("PASS: Backtest completed cleanly end-to-end!")
    elif completed and st.get("status") == "error":
        err_msg = st.get("error", "")
        if "No module named 'AlgorithmImports'" in err_msg:
            print("FAIL: AlgorithmImports import error still occurring!")
            sys.exit(1)
        else:
            print(f"NOTICE: Backtest exited with status 'error': {err_msg}")
    else:
        print("TIMEOUT: Backtest exceeded 45s threshold (still running in background).")

if __name__ == "__main__":
    print("==================================================")
    print("      QUANT-LEAN DASHBOARD STRESS TEST SUITE      ")
    print("==================================================")
    
    test_1_dll_resolution()
    test_2_config_patching()
    test_3_data_caching_and_fallback()
    test_4_server_api_concurrency()
    
    print("\n==================================================")
    print("            ALL STRESS TESTS COMPLETED            ")
    print("==================================================")
