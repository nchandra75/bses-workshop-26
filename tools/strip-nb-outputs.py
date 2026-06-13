#!/usr/bin/env python3
"""Strip outputs/execution counts from a Jupyter notebook on stdin -> stdout.

Used as a git 'clean' filter (see .gitattributes + the setup in this repo's
docs/README) so notebooks commit with code only - no embedded outputs, no
execution counters, no transient widget state. The working copy keeps its
outputs untouched; only what git stores is stripped. Pure stdlib so it runs
anywhere python3 does (laptop or board), no extra packages.
"""
import json
import sys

nb = json.load(sys.stdin)

for cell in nb.get("cells", []):
    if cell.get("cell_type") == "code":
        cell["outputs"] = []
        cell["execution_count"] = None
    # drop per-cell transient metadata that churns without being a code change
    cell.get("metadata", {}).pop("execution", None)

# notebook-level widget state is output, not source
nb.get("metadata", {}).pop("widgets", None)

json.dump(nb, sys.stdout, indent=1, ensure_ascii=False, sort_keys=True)
sys.stdout.write("\n")
