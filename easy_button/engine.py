"""Deterministic CTO-to-stock-fulfillment translation engine.

Rule set validated against Steff's answer-key tables in
'Translation Example 1.xls' (deals 83737219, 84709746, 84251013):

  R1. Parent hardware line (x.0) -> KEEP, SKU unchanged.
  R2. Service lines (CON-*) -> KEEP unchanged when their bundle is kept.
  R3. A child bundle (x.N + descendants x.N.*) with no list price > 0
      anywhere -> DROP (contents ship inside the spare box).
  R4. A kept bundle's head line swaps to its SPARE EQUIVALENT SKU
      ('=' SKU) when one exists; descendants keep their SKUs.
  R5. Deal pricing is preserved on every kept line.

The engine never invents a SKU. Anything outside the rules raises a flag
for human review instead of guessing.
"""
import csv
import xlrd

COL = dict(line=5, sku=7, included=8, qty=9, dur=10, list=14, extlist=15,
           net=16, extnet=17, spare=32, sparelist=33, sparedisc=34)
OUT_FIELDS = ["line", "action", "sku", "original_sku", "qty", "list", "net",
              "extnet", "reason"]


def _num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def read_tables(sheet):
    """Split a sheet into (original, answer_key) line lists.

    A gap of 2+ empty rows or a repeated header row separates the original
    table from an answer key; a single empty row is a group separator.
    """
    blocks, cur, empties = [], [], 0
    for r in range(1, sheet.nrows):
        vals = [sheet.cell_value(r, c) for c in range(sheet.ncols)]
        if all(v in ("", None) for v in vals):
            empties += 1
            continue
        if vals[0] == "AUTHORIZATION NUMBER" or empties >= 2:
            if cur:
                blocks.append(cur)
                cur = []
        empties = 0
        if vals[0] == "AUTHORIZATION NUMBER":
            continue
        cur.append({k: vals[c] for k, c in COL.items()})
    if cur:
        blocks.append(cur)
    return blocks[0], (blocks[1] if len(blocks) > 1 else [])


def translate(lines, keep_zero_dollar_lines=False):
    """Apply rules R1-R5. Returns (decisions, flags).

    decisions: one dict per input line with action keep|swap|drop and reason.
    flags: human-review items the rules cannot decide.
    """
    decisions, flags = [], []
    bundles = {}
    for ln in lines:
        parts = str(ln["line"]).split(".")
        bundles.setdefault(".".join(parts[:2]), []).append(ln)

    def sort_key(item):
        return [float(x) for x in item[0].split(".")]

    for head, bl in sorted(bundles.items(), key=sort_key):
        is_parent = head.endswith(".0")
        has_value = any(_num(l["list"]) > 0 or _num(l["extlist"]) > 0 for l in bl)
        for ln in bl:
            d = dict(line=str(ln["line"]), original_sku=ln["sku"], sku=ln["sku"],
                     qty=_num(ln["qty"]), list=_num(ln["list"]), net=_num(ln["net"]),
                     extnet=_num(ln["extnet"]))
            if is_parent or has_value:
                if str(ln["line"]) == head and not is_parent and ln["spare"]:
                    d.update(action="swap", sku=ln["spare"],
                             reason="paid line -> spare '=' SKU (R4)")
                elif str(ln["line"]) == head and not is_parent and _num(ln["list"]) > 0:
                    d.update(action="keep", reason="paid line, no spare SKU on quote")
                    flags.append(f"line {ln['line']} ({ln['sku']}): value-bearing but no "
                                 "spare equivalent on the quote - confirm orderable from stock")
                else:
                    why = "parent hardware (R1)" if is_parent and str(ln["line"]) == head \
                        else "service/term in kept bundle (R2)"
                    d.update(action="keep", reason=why)
            else:
                d.update(action="keep" if keep_zero_dollar_lines else "drop",
                         reason="zero-dollar bundle, ships in the box (R3)")
            decisions.append(d)
    return decisions, flags


def translate_workbook(path, keep_zero_dollar_lines=False):
    """Translate every sheet. Returns a structured report dict."""
    wb = xlrd.open_workbook(path)
    report = {"file": path, "sheets": []}
    for name in wb.sheet_names():
        orig, answer_key = read_tables(wb.sheet_by_name(name))
        decisions, flags = translate(orig, keep_zero_dollar_lines)
        kept = [d for d in decisions if d["action"] != "drop"]
        sheet = {"deal": name, "input_lines": len(orig),
                 "output_lines": len(kept), "decisions": decisions,
                 "flags": flags, "validation": None}
        if answer_key:
            sheet["validation"] = _validate(kept, answer_key)
        report["sheets"].append(sheet)
    return report


def _validate(kept, answer_key):
    """Diff kept lines against an answer-key table (value lines must match)."""
    exp_groups = {str(e["line"]).split(".")[0] for e in answer_key}
    mine = {d["line"]: d for d in kept if d["line"].split(".")[0] in exp_groups}
    exp = {str(e["line"]): e for e in answer_key}
    issues = []
    for k in sorted(set(exp) | set(mine), key=lambda s: [float(x) for x in s.split(".")]):
        e, m = exp.get(k), mine.get(k)
        if e and m and e["sku"] != m["sku"]:
            issues.append(f"{k}: expected {e['sku']}, got {m['sku']}")
        elif e and not m and (_num(e["list"]) > 0 or _num(e["extlist"]) > 0):
            issues.append(f"{k}: value line {e['sku']} missing from output")
        elif m and not e:
            issues.append(f"{k}: extra line {m['sku']} not in answer key")
    return {"pass": not issues, "issues": issues}


def export_csv(report, out_path):
    """Write kept lines of every sheet to a CSV the sales team can use."""
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["DEAL"] + [x.upper() for x in OUT_FIELDS])
        for sheet in report["sheets"]:
            for d in sheet["decisions"]:
                if d["action"] != "drop":
                    w.writerow([sheet["deal"]] + [d[k] for k in OUT_FIELDS])
    return out_path
