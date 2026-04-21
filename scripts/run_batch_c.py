#!/usr/bin/env python3
"""Auto-merge all Batch C groups (merge-all strategy: union into largest, delete others)."""
import json, subprocess, time
from pathlib import Path

bc = json.load(open("/tmp/batch_classification.json"))
groups = bc["batch_c"]

LOG = Path("/tmp/batch_c_run.log")
LOG.write_text("")
results = {"success": [], "failed": [], "skipped_qobuz_owned": []}

print(f"Processing {len(groups)} groups\n")

for i, g in enumerate(groups, 1):
    name = g["name"]
    print(f"[{i}/{len(groups)}] {name}")
    cmd = ["python3", "/Users/monty/dev/qobuz-mcp/scripts/merge_playlist.py", name.lower(), "--apply"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        out = proc.stdout
        ok = proc.returncode == 0 and ("All adds succeeded" in out or "Will fit in single playlist" in out)
    except subprocess.TimeoutExpired:
        proc = None
        out = ""
        ok = False

    with LOG.open("a") as f:
        f.write(f"\n\n{'='*80}\n[{i}/{len(groups)}] {name}\n{'='*80}\n")
        f.write(out if proc else "TIMEOUT")
        if proc and proc.stderr:
            f.write("\n--- stderr ---\n" + proc.stderr)

    if ok:
        results["success"].append(name)
        print(f"  OK")
    else:
        # Check if it's a Qobuz-owned playlist 401 (only fails on delete, but tracks still merged)
        if proc and "ERROR: HTTP Error 401" in out and "All adds succeeded" in out:
            results["skipped_qobuz_owned"].append(name)
            print(f"  PARTIAL — adds succeeded, delete blocked (Qobuz-owned copy)")
        else:
            results["failed"].append(name)
            print(f"  FAILED — see log")
    time.sleep(0.3)

print(f"\nDone. Success: {len(results['success'])}, Partial: {len(results['skipped_qobuz_owned'])}, Failed: {len(results['failed'])}")
Path("/tmp/batch_c_results.json").write_text(json.dumps(results, indent=2))
