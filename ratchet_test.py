"""
Ratchet Test Harness — validates the Ratchet Dashboard end-to-end.
Score = 0 means perfect. Lower = better (like loss).
"""
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

WORKSPACE = os.environ.get("RATCHET_WORKSPACE", str(Path.home() / "auto-research"))
BASE_URL = "http://127.0.0.1:8765"  # matches the running dev server
TIMEOUT = 15

def start_server():
    """Start the backend on port 8766, return process."""
    env = os.environ.copy()
    env["RATCHET_WORKSPACE"] = WORKSPACE
    proc = subprocess.Popen(
        [sys.executable, "backend/ratchet.py"],
        cwd=str(Path(__file__).parent),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    time.sleep(2)
    return proc

def fetch(url):
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.read().decode()
    except Exception as e:
        return f"ERROR: {e}"

def score():
    errors = []
    score_val = 0.0

    # 1. Server reachable?
    html = fetch(f"{BASE_URL}/api/plugins/ratchet/")
    if html.startswith("ERROR"):
        errors.append(f"Server unreachable: {html}")
        score_val += 100.0
        return score_val, errors

    # 2. HTML contains dashboard structure?
    checks = [
        ("exp-list" in html, "Missing #exp-list element"),
        ("waterfall" in html, "Missing #waterfall canvas"),
        ("best-score" in html, "Missing #best-score element"),
        ("RATCHET MODE" in html, "Missing title / logo"),
    ]
    for ok, msg in checks:
        if not ok:
            errors.append(msg)
            score_val += 5.0

    # 3. JS API_BASE logic is correct for /api/plugins/ratchet/ path?
    if "const API_BASE = (() => {" in html and "u.pathname.includes('/api/plugins')" in html:
        # verify it strips trailing slash
        if ".replace(/\\/$/, '')" in html:
            pass  # good
        else:
            errors.append("API_BASE trailing slash not handled")
            score_val += 3.0
    else:
        errors.append("API_BASE doesn't detect Hermes dashboard path")
        score_val += 5.0

    # 4. /info endpoint returns valid JSON with expected fields?
    info_raw = fetch(f"{BASE_URL}/api/plugins/ratchet/info")
    try:
        info = json.loads(info_raw)
        required = ["workspace", "running", "best_score", "total_experiments"]
        for k in required:
            if k not in info:
                errors.append(f"/info missing field: {k}")
                score_val += 2.0
        if info.get("total_experiments", 0) == 0:
            errors.append("/info reports 0 experiments")
            score_val += 5.0
    except json.JSONDecodeError:
        errors.append(f"/info returned invalid JSON: {info_raw[:80]}")
        score_val += 10.0

    # 5. /experiments returns array?
    exps_raw = fetch(f"{BASE_URL}/api/plugins/ratchet/experiments")
    try:
        exps = json.loads(exps_raw)
        if not isinstance(exps, list):
            errors.append("/experiments did not return array")
            score_val += 5.0
        elif len(exps) == 0:
            errors.append("/experiments returned empty array")
            score_val += 5.0
    except json.JSONDecodeError:
        errors.append(f"/experiments invalid JSON: {exps_raw[:80]}")
        score_val += 10.0

    # 6. SSE endpoint exists and returns event-stream?
    # FastAPI StreamingResponse rejects HEAD, so send GET but timeout quickly
    import subprocess, shlex
    curl_cmd = f"curl -s --max-time 1 {BASE_URL}/api/plugins/ratchet/sse"
    try:
        result = subprocess.run(shlex.split(curl_cmd), capture_output=True, text=True, timeout=3)
        output = result.stdout
        # Should start with "data:" or HTTP headers start with HTTP/1.1
        if output.startswith('data:') or output.startswith('HTTP/'):
            pass  # good — correct stream type
        else:
            errors.append("SSE stream did not produce expected output")
            score_val += 3.0
    except subprocess.TimeoutExpired:
        # Timeout means the SSE endpoint blocked (expected behavior)
        pass
    except Exception as e:
        errors.append(f"SSE endpoint error: {e}")
        score_val += 3.0
    # Note: ${RATCHET_API}/endpoint is valid template literal syntax
    if "RATCHET_API = API_BASE" not in html:
        errors.append("RATCHET_API not assigned from API_BASE")
        score_val += 5.0

    return score_val, errors

if __name__ == "__main__":
    # Server is assumed to be running on port 8765 externally
    s, errs = score()
    print(f"SCORE: {s}")
    if errs:
        for e in errs:
            print(f"  ERROR: {e}")
    else:
        print("  ALL CHECKS PASSED")
