"""
Autonomous Ratchet Loop for the Hermes Ratchet Dashboard.
Runs ratchet_test.py, uses Claude Code to fix issues, commits if score improves.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_DIR = Path(__file__).parent.resolve()
TEST_SCRIPT = REPO_DIR / "ratchet_test.py"
SERVER_CMD = [sys.executable, "backend/ratchet.py"]
SERVER_ENV = os.environ.copy() | {"RATCHET_WORKSPACE": str(Path.home() / "auto-research")}
MAX_ITER = 10

def run_test():
    """Run ratchet_test.py against the running server. Returns (score, errors)."""
    result = subprocess.run(
        [sys.executable, str(TEST_SCRIPT)],
        cwd=str(REPO_DIR),
        capture_output=True,
        text=True,
        timeout=30,
    )
    lines = result.stdout.strip().splitlines()
    if not lines:
        return 999, ["Test produced no output"]
    score_line = lines[0]
    try:
        score_val = float(score_line.replace("SCORE:", "").strip())
    except ValueError:
        return 999, [f"Could not parse score: {score_line}"]
    errors = [line.replace("  ERROR:", "").strip() for line in lines[1:] if line.startswith("  ERROR:")]
    return score_val, errors

def claude_fix(errors: list[str]) -> bool:
    """Invoke Claude Code to fix the reported errors. Returns True if edits were made."""
    prompt = f"""The ratchet_test.py reported these validation errors:

{chr(10).join(f"- {e}" for e in errors)}

Fix the issues in dashboard.html and/or backend/ratchet.py.
Do NOT change the test script. Focus only on the source files.
Commit when done."""
    cmd = [
        "claude", "-p", prompt,
        "--allowedTools", "Read,Edit,Write,Bash",
        "--max-turns", "15",
    ]
    result = subprocess.run(cmd, cwd=str(REPO_DIR), capture_output=True, text=True, timeout=180)
    print("[CLAUDE] stdout:", result.stdout[-500:] if len(result.stdout) > 500 else result.stdout)
    if result.stderr:
        print("[CLAUDE] stderr:", result.stderr[-300:])
    return result.returncode == 0

def main():
    # Start server in background
    server_proc = subprocess.Popen(
        SERVER_CMD, cwd=str(REPO_DIR), env=SERVER_ENV,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    time.sleep(2)
    print(f"[SERVER] PID {server_proc.pid}")

    best_score, best_errors = run_test()
    print(f"[INIT] Score: {best_score}, Errors: {len(best_errors)}")

    for i in range(MAX_ITER):
        if best_score <= 0:
            print("[DONE] Score is 0. Ratchet complete.")
            break

        print(f"\n[ITER {i+1}/{MAX_ITER}] Best score: {best_score}")
        # Snapshot current state
        subprocess.run(["git", "stash", "push", "-m", f"ratchet-iter-{i}"], cwd=str(REPO_DIR))

        if claude_fix(best_errors):
            new_score, new_errors = run_test()
            print(f"[TEST] New score: {new_score}")
            if new_score <= best_score:
                print("[KEEP] Score improved or stayed same. Committing.")
                subprocess.run(["git", "add", "-A"], cwd=str(REPO_DIR))
                subprocess.run(["git", "commit", "-m", f"ratchet iter {i+1}: score {best_score} -> {new_score}"], cwd=str(REPO_DIR))
                best_score, best_errors = new_score, new_errors
            else:
                print("[REVERT] Score worsened. Resetting.")
                subprocess.run(["git", "reset", "--hard", "HEAD"], cwd=str(REPO_DIR))
                subprocess.run(["git", "stash", "pop"], cwd=str(REPO_DIR))
        else:
            print("[SKIP] Claude returned non-zero. Reverting stash.")
            subprocess.run(["git", "stash", "pop"], cwd=str(REPO_DIR))

    server_proc.terminate()
    server_proc.wait(timeout=5)
    print(f"\n[FINAL] Best score: {best_score}")
    print(f"[FINAL] Remaining errors: {best_errors}")

if __name__ == "__main__":
    main()
