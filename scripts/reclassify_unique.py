#!/usr/bin/env python3
"""Re-classify Batch C using UNIQUE-set sizes as denominators (not reported track counts).
Many "curated" flags are false positives caused by internal-dup inflation."""
import json

d = json.load(open('/tmp/duplicates_report.json'))

# We need to identify which of the original needs_review groups are still in batch C
bc = json.load(open('/tmp/batch_classification.json'))
batch_c_names = {g['name'].lower().strip() for g in bc['batch_c']}

# Re-evaluate using unique-set sizes
truly_curated = []  # still has a curated subset by unique-set logic
mergeable_now = []  # was flagged but actually fine

for g in d['needs_review']:
    name = g['name']
    if name.lower().strip() not in batch_c_names:
        continue  # only re-check Batch C
    copies = g['copies']
    sorted_copies = sorted(copies, key=lambda c: -len(c['track_set']))  # sort by UNIQUE set size
    largest = sorted_copies[0]
    others = sorted_copies[1:]

    flags = []
    for c in others:
        unique_set_size = len(c['track_set'])
        if unique_set_size >= 10 and c['unique_count'] >= 0.30 * unique_set_size:
            flags.append(f"{c['id']} has {c['unique_count']}/{unique_set_size} unique-set ({100*c['unique_count']//unique_set_size}%)")

    if flags:
        truly_curated.append((name, sorted_copies, flags))
    else:
        mergeable_now.append((name, sorted_copies))

print(f"Truly curated (still skip): {len(truly_curated)}")
print(f"Now mergeable (false positive): {len(mergeable_now)}")
print()
print("=== TRULY CURATED ===")
for name, copies, flags in truly_curated:
    print(f"\n[{name}]")
    for f in flags:
        print(f"  - {f}")
    for c in copies:
        vis = "pub " if c['public'] else "priv"
        print(f"    {c['id']:>10}  rep:{c['tracks']:>4}t  uniq-IDs:{len(c['track_set']):>4}  uniq-to-this:{c['unique_count']}  {vis}")

print("\n=== NOW MERGEABLE (re-eval with unique-set denominators) ===")
for name, copies in mergeable_now:
    print(f"\n[{name}]")
    for c in copies:
        vis = "pub " if c['public'] else "priv"
        print(f"    {c['id']:>10}  rep:{c['tracks']:>4}t  uniq-IDs:{len(c['track_set']):>4}  uniq-to-this:{c['unique_count']}  {vis}")
