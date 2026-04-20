#!/usr/bin/env python3
"""Run merge_playlist.py for every group in Batch A. Continue on failures.
Per-group: 5 min hard timeout. Failures logged and continued past."""
import json, subprocess, sys, time
from pathlib import Path

LOG_FILE = Path("/tmp/batch_a_run.log")
RESULT_FILE = Path("/tmp/batch_a_results.json")

bc = json.load(open("/tmp/batch_classification.json"))
groups = bc["batch_a"]

print(f"Will process {len(groups)} groups. Logging to {LOG_FILE}")
LOG_FILE.write_text("")

results = {"success": [], "failed": [], "skipped": []}
start = time.time()

for i, g in enumerate(groups, 1):
    name = g["name"]
    union = g["union"]
    n_copies = len(g["copies"])
    elapsed = int(time.time() - start)
    print(f"[{i}/{len(groups)}] ({elapsed}s) [{name}] union={union}, copies={n_copies}")

    # Run merge_playlist.py with --apply
    cmd = ["python3", "/tmp/merge_playlist.py", name.lower(), "--apply"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        out = proc.stdout
        err = proc.stderr
        ok = proc.returncode == 0 and "All adds succeeded" in out
        if "[DRY RUN]" in out:
            ok = False
            err = "DRY RUN — should not happen"
    except subprocess.TimeoutExpired:
        ok = False
        out = ""
        err = "TIMEOUT after 300s"

    # Append full output to log
    with LOG_FILE.open("a") as f:
        f.write(f"\n\n{'='*80}\n[{i}/{len(groups)}] {name}\n{'='*80}\n")
        f.write(out)
        if err:
            f.write(f"\n--- stderr ---\n{err}")

    if ok:
        results["success"].append({"name": name, "union": union, "copies": n_copies})
        print(f"  OK")
    else:
        results["failed"].append({"name": name, "stderr": err[:500] if err else "", "stdout_tail": out[-500:] if out else ""})
        print(f"  FAILED — see log")

    # Rate-limit a bit to be polite to Qobuz
    time.sleep(0.3)

elapsed = int(time.time() - start)
print(f"\n=== DONE in {elapsed}s ===")
print(f"Success: {len(results['success'])}")
print(f"Failed:  {len(results['failed'])}")
RESULT_FILE.write_text(json.dumps(results, indent=2))
print(f"Results saved to {RESULT_FILE}")

if results["failed"]:
    print("\nFailed groups:")
    for f in results["failed"]:
        print(f"  [{f['name']}] {f.get('stderr','')[:100]}")
