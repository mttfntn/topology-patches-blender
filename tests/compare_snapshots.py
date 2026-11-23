"""Compare two behaviour snapshots (plain Python, no Blender needed).

    python tests/compare_snapshots.py OLD.json NEW.json [--tol 1e-4]

Everything that is not a number (labels, messages, names, modifier stacks)
must match exactly. Numbers may differ by a relative tolerance (default 1e-4);
the snapshot already rounds them, and bmesh work is deterministic, so two runs
of the same version normally give 0 differences.
Prints every difference with its path and exits non-zero if there is any.
"""

import argparse
import json
import sys


def diff(a, b, path, tol, out):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append(f"{path}/{k}: only in {'new' if k not in a else 'old'}")
            else:
                diff(a[k], b[k], f"{path}/{k}", tol, out)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f"{path}: length {len(a)} -> {len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            diff(x, y, f"{path}[{i}]", tol, out)
    elif (isinstance(a, (int, float)) and isinstance(b, (int, float))
          and not isinstance(a, bool) and not isinstance(b, bool)):
        if abs(a - b) > tol * max(1.0, abs(a), abs(b)):
            out.append(f"{path}: {a} -> {b}")
    elif a != b:
        out.append(f"{path}: {a!r} -> {b!r}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("--tol", type=float, default=1e-4)
    args = ap.parse_args()
    with open(args.old) as f:
        old = json.load(f)
    with open(args.new) as f:
        new = json.load(f)
    out = []
    diff(old, new, "", args.tol, out)
    for line in out:
        print(line)
    print(f"COMPARE groups={len(old)} differences={len(out)}")
    sys.exit(1 if out else 0)


if __name__ == "__main__":
    main()
