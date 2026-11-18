"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    import math

    problems: list[str] = []

    # 1. Any metric value is NaN or inf
    for k, v in pr.get("metrics", {}).items():
        if isinstance(v, (int, float)) and (math.isnan(v) or math.isinf(v)):
            problems.append(f"metric {k} has invalid value {v}")

    # 2. Row count check
    expected_rows = pr.get("manifest", {}).get("items", 0) * len(pr.get("manifest", {}).get("seeds", []))
    if len(pr.get("rows", [])) != expected_rows:
        problems.append(f"row count {len(pr.get('rows', []))} != expected {expected_rows}")

    # 3. (item_id, seed) set comparison with baseline
    pr_keys = {(r.get("item_id"), r.get("seed")) for r in pr.get("rows", [])}
    base_keys = {(r.get("item_id"), r.get("seed")) for r in base.get("rows", [])}
    if pr_keys != base_keys:
        problems.append("PR (item_id, seed) set differs from baseline")

    # 4. Evaluator failures or missing graded values
    if pr.get("evaluator_failures"):
        problems.append(f"evaluator failures reported: {pr['evaluator_failures']}")
    for r in pr.get("rows", []):
        for m in spec.get("metrics", []):
            mid = m.get("id")
            if mid in r and r[mid] is None:
                problems.append(f"row {r.get('item_id')}@{r.get('seed')} has None for metric {mid}")
                break

    # 5. Ratchet against base_spec
    if base_spec and spec.get("eval_set_version") == base_spec.get("eval_set_version"):
        base_metrics = {m["id"]: m for m in base_spec.get("metrics", [])}
        for b_id, b_m in base_metrics.items():
            if b_id not in {m["id"] for m in spec.get("metrics", [])}:
                problems.append(f"ratchet: metric {b_id} was removed from spec")
                continue
            cur_m = next(m for m in spec.get("metrics", []) if m["id"] == b_id)
            if b_m.get("blocking") and not cur_m.get("blocking"):
                problems.append(f"ratchet: blocking metric {b_id} became non-blocking")
            b_th = b_m.get("threshold", {})
            c_th = cur_m.get("threshold", {})
            if "max" in b_th and c_th.get("max", b_th["max"]) > b_th["max"]:
                problems.append(f"ratchet: threshold max for {b_id} increased")
            if "min" in b_th and c_th.get("min", b_th["min"]) < b_th["min"]:
                problems.append(f"ratchet: threshold min for {b_id} decreased")
            if b_th.get("no_significant_drop") and not c_th.get("no_significant_drop"):
                problems.append(f"ratchet: no_significant_drop dropped for {b_id}")

        base_slices = {s["name"]: s for s in base_spec.get("slices", [])}
        for b_sname, b_s in base_slices.items():
            if b_sname not in {s["name"] for s in spec.get("slices", [])}:
                problems.append(f"ratchet: slice {b_sname} was removed from spec")
                continue
            cur_s = next(s for s in spec.get("slices", []) if s["name"] == b_sname)
            if b_s.get("blocking") and not cur_s.get("blocking"):
                problems.append(f"ratchet: blocking slice {b_sname} became non-blocking")
            if "min" in b_s and cur_s.get("min", b_s["min"]) < b_s["min"]:
                problems.append(f"ratchet: slice min for {b_sname} decreased")
            if b_s.get("no_significant_drop") and not cur_s.get("no_significant_drop"):
                problems.append(f"ratchet: slice no_significant_drop dropped for {b_sname}")

    # 6. Slice tags match baseline
    pr_row_slices = {(r.get("item_id"), r.get("seed")): tuple(sorted(r.get("slices") or [])) for r in pr.get("rows", [])}
    base_row_slices = {(r.get("item_id"), r.get("seed")): tuple(sorted(r.get("slices") or [])) for r in base.get("rows", [])}
    if pr_row_slices != base_row_slices:
        problems.append("PR slice tags differ from baseline")

    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked: list[str] = []
    lines: list[str] = []
    bs = spec.get("bootstrap", {})

    for s in spec.get("slices", []):
        sname = s.get("name")
        metric_id = s.get("metric", "pass_rate")
        pr_items = per_item(pr, metric_id, slice_name=sname)
        if not pr_items:
            continue

        val = float(sum(pr_items.values()) / len(pr_items))
        verdict = "ok"
        note = ""

        # Check floor min
        if "min" in s and val < s["min"]:
            verdict = "fail"

        # Check no_significant_drop
        if s.get("no_significant_drop"):
            base_items = per_item(base, metric_id, slice_name=sname)
            common_keys = sorted(set(pr_items.keys()) & set(base_items.keys()))
            if common_keys:
                d, lo, hi = stats.paired_bootstrap(
                    [pr_items[k] for k in common_keys],
                    [base_items[k] for k in common_keys],
                    n_resamples=bs.get("n_resamples", 1000),
                    rng=bs.get("rng", 2027),
                )
                note = f" Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    verdict = "fail"

        slice_id = f"slice:{sname}/{metric_id}"
        lines.append(f"  {slice_id:<32} {val:<8.4f} min={s.get('min', '-')}{note} {verdict}")
        if verdict != "ok" and s.get("blocking", True):
            blocked.append(slice_id)

    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
