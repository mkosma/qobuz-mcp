#!/usr/bin/env python3
"""Classify 162 remaining duplicate groups and propose batches.

Batch A: union ≤ 2000, no curated-subset smell. Safe to auto-merge.
Batch B: union > 2000 (needs split). Safe but creates multiple playlists.
Batch C: smaller copies have high % unique tracks (likely deliberate curation). Skip.

The curated-subset heuristic: if any non-largest copy has >= 30% of its tracks
unique to itself AND has >= 10 tracks, flag for manual review.
"""
import json, math, sys
from pathlib import Path

d = json.load(open('/tmp/duplicates_report.json'))

SOUNDIIZ_SYNCED = {"release radar", "bombetta"}  # already handled
# (discover weekly already handled too but may be in list)

batch_a = []  # single playlist, auto-merge
batch_b = []  # needs split, auto-merge
batch_c = []  # hand-pick

for g in d['needs_review']:
    name = g['name']
    name_low = name.lower().strip()
    copies = g['copies']
    sorted_copies = sorted(copies, key=lambda c: -c['tracks'])
    largest = sorted_copies[0]
    others = sorted_copies[1:]

    # Skip already-handled Soundiiz-synced
    if name_low in SOUNDIIZ_SYNCED or name_low.startswith("release radar") or name_low.startswith("discover weekly"):
        batch_c.append((name, sorted_copies, "soundiiz-handled"))
        continue

    # Compute union tracks needed
    largest_set = set(largest['track_set'])
    loser_unique = set()
    for o in others:
        loser_unique |= (set(o['track_set']) - largest_set)
    union_size = largest['tracks'] + len(loser_unique)

    # Curated-subset heuristic: any non-largest with >= 30% unique AND >= 10t
    curated = False
    curated_note = []
    for c in others:
        if c['tracks'] >= 10 and c['unique_count'] >= 0.30 * c['tracks']:
            curated = True
            curated_note.append(f"{c['id']} has {c['unique_count']}/{c['tracks']} unique ({100*c['unique_count']//c['tracks']}%)")

    if curated:
        batch_c.append((name, sorted_copies, "curated-subset: " + "; ".join(curated_note)))
    elif union_size <= 2000:
        batch_a.append((name, sorted_copies, union_size))
    else:
        n_parts = math.ceil(union_size / 2000)
        batch_b.append((name, sorted_copies, union_size, n_parts))

print(f"Batch A (single-playlist auto-merge, safe): {len(batch_a)}")
print(f"Batch B (split into N parts, safe): {len(batch_b)}")
print(f"Batch C (skip, hand-pick): {len(batch_c)}")

print(f"\n{'='*80}\nBATCH B — will split into parts\n{'='*80}")
for name, copies, union, n_parts in sorted(batch_b, key=lambda x: -x[2]):
    ids = [c['id'] for c in copies]
    print(f"  [{name}] union={union} → {n_parts} parts, copies: {len(copies)}")

print(f"\n{'='*80}\nBATCH C — skipping, needs human review\n{'='*80}")
for name, copies, reason in batch_c:
    print(f"\n  [{name}] — {reason}")
    for c in copies:
        vis = "pub " if c['public'] else "priv"
        print(f"    {c['id']:>10}  {c['tracks']:>5}t  {vis}  unique:{c['unique_count']}")

# Save classification
out = {
    "batch_a": [{"name": n, "union": u, "copies": c} for n, c, u in batch_a],
    "batch_b": [{"name": n, "union": u, "n_parts": np, "copies": c} for n, c, u, np in batch_b],
    "batch_c": [{"name": n, "reason": r, "copies": c} for n, c, r in batch_c],
}
Path("/tmp/batch_classification.json").write_text(json.dumps(out, indent=2, default=str))
print(f"\nSaved to /tmp/batch_classification.json")
