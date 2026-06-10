"""Deterministic CTO-to-stock-fulfillment translation engine.

Rule set validated against Steff's answer-key tables in
'Translation Example 1.xls' (deals 83737219, 84709746, 84251013):

  R1. Parent hardware line (x.0) -> KEEP, SKU unchanged.
  R2. Service/term lines (CON-*) -> KEEP unchanged when their bundle is kept.
      Non-CON-* zero-dollar descendants -> UNKNOWN-DESCENDANT flag for human review.
  R3. A child bundle (x.N + descendants x.N.*) with no value anywhere
      (list, extlist, net, extnet all <= 0) -> DROP (ships inside the spare box).
  R4. A kept bundle's head line swaps to its SPARE EQUIVALENT SKU
      ('=' SKU, col 32) when one exists; descendants keep their SKUs.
  R5. list price, net price, extended net, and quantity are preserved on every
      kept line. (extlist, dur, included, sparelist, sparedisc not in CSV export.)

The engine never invents a SKU. Anything outside the rules raises a flag
for human review instead of guessing.

Negative pricing: lines with any negative price field are flagged for human
review — they may represent credits or adjustments not covered by R1-R5.
"""
import csv
import os
import re
import tempfile
import xlrd

COL = dict(line=5, sku=7, included=8, qty=9, dur=10, list=14, extlist=15,
           net=16, extnet=17, spare=32, sparelist=33, sparedisc=34)
OUT_FIELDS = ["line", "action", "sku", "original_sku", "qty", "list", "net",
              "extnet", "reason"]

_MIN_NCOLS = max(COL.values()) + 1
_SERVICE_PREFIX = "CON-"
_LINE_ID_RE = re.compile(r'^\d+(\.\d+)*$')
_FORMULA_CHARS = frozenset(('=', '+', '-', '@', '\t', '\r'))
_PRICE_COLS = ('list', 'extlist', 'net', 'extnet', 'sparelist', 'sparedisc', 'qty', 'dur')


def _num(v):
    if v is None or v == '':
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _strip(v):
    if v is None:
        return ''
    return str(v).strip()


def _sanitize_csv(v):
    s = str(v) if v is not None else ''
    if s and s[0] in _FORMULA_CHARS:
        return "'" + s
    return s


def _safe_sort_key(s):
    parts = []
    for x in s.split("."):
        try:
            parts.append(float(x))
        except ValueError:
            parts.append(0.0)
    return parts


def read_tables(sheet):
    """Split a sheet into (original, answer_key) line lists.

    Raises ValueError on schema violations or empty sheets.
    Any numeric line-ID cell or unparseable pricing cell is a blocking error —
    the row is skipped and the error is recorded in the returned flags list
    attached to a sentinel row so callers can surface it.
    """
    if sheet.ncols < _MIN_NCOLS:
        raise ValueError(
            f"Sheet '{sheet.name}': expected >= {_MIN_NCOLS} columns, "
            f"got {sheet.ncols}. Workbook may use a different column layout."
        )

    blocks, cur, empties = [], [], 0
    parse_errors = []

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

        row = {}
        row_flags = []
        skip_row = False

        for k, c in COL.items():
            cell = sheet.cell(r, c)
            if k == 'line':
                if cell.ctype == xlrd.XL_CELL_NUMBER:
                    msg = (
                        f"row {r}: line ID is numeric in Excel "
                        f"(value={cell.value!r}) — original value unrecoverable; "
                        "re-export with line column as text; row skipped"
                    )
                    row_flags.append(msg)
                    parse_errors.append(msg)
                    skip_row = True
                    break
                row[k] = _strip(cell.value)
            elif k in _PRICE_COLS:
                raw = cell.value
                if raw in (None, ''):
                    row[k] = 0.0
                else:
                    try:
                        row[k] = float(raw)
                    except (TypeError, ValueError):
                        msg = (
                            f"row {r}, col '{k}': unparseable value {raw!r} — "
                            "cannot safely determine value; row skipped"
                        )
                        row_flags.append(msg)
                        parse_errors.append(msg)
                        skip_row = True
                        break
            else:
                row[k] = _strip(cell.value)

        if skip_row:
            cur.append({'_flags': row_flags, 'line': '', '_skip': True})
            continue

        row['_flags'] = row_flags
        cur.append(row)

    if cur:
        blocks.append(cur)

    if not blocks:
        raise ValueError(f"Sheet '{sheet.name}': no quote table found.")

    return blocks[0], (blocks[1] if len(blocks) > 1 else [])


def translate(lines, keep_zero_dollar_lines=False):
    """Apply rules R1-R5. Returns (decisions, flags)."""
    decisions, flags = [], []

    for ln in lines:
        flags.extend(ln.get('_flags', []))

    # Skip sentinel rows produced by read_tables for blocking parse errors
    valid_lines = [ln for ln in lines if not ln.get('_skip')]

    bundles = {}
    for ln in valid_lines:
        line_id = ln["line"]
        parts = line_id.split(".")
        bundles.setdefault(".".join(parts[:2]), []).append(ln)

    for head, bl in sorted(bundles.items(), key=lambda item: _safe_sort_key(item[0])):
        is_parent = head.endswith(".0")
        head_lines = [ln for ln in bl if ln["line"] == head]

        if not is_parent:
            if not head_lines:
                flags.append(
                    f"bundle '{head}': no head line found — "
                    "descendants kept without R4 swap opportunity"
                )
            elif len(head_lines) > 1:
                flags.append(
                    f"bundle '{head}': {len(head_lines)} duplicate head lines found — "
                    "expected exactly one; using first occurrence"
                )

        has_value = any(
            _num(l.get("list")) > 0
            or _num(l.get("extlist")) > 0
            or _num(l.get("net")) > 0
            or _num(l.get("extnet")) > 0
            for l in bl
        )

        for ln in bl:
            line_id = ln["line"]
            if not _LINE_ID_RE.match(line_id):
                flags.append(
                    f"line ID '{line_id}' is not a valid dotted-integer — row skipped"
                )
                continue

            # Negative pricing: flag for human review — may be credit/adjustment
            has_negative = any(
                _num(ln.get(f)) < 0
                for f in ('list', 'extlist', 'net', 'extnet')
            )
            if has_negative:
                flags.append(
                    f"line {line_id} ({ln['sku']}): negative pricing detected — "
                    "may be a credit or adjustment line; human review required"
                )

            spare = _strip(ln.get("spare", ""))

            d = dict(
                line=line_id,
                original_sku=ln["sku"],
                sku=ln["sku"],
                qty=_num(ln.get("qty")),
                list=_num(ln.get("list")),
                net=_num(ln.get("net")),
                extnet=_num(ln.get("extnet")),
            )

            if is_parent or has_value:
                if line_id == head and not is_parent and spare:
                    d.update(action="swap", sku=spare,
                             reason="paid line -> spare '=' SKU (R4)")
                elif line_id == head and not is_parent:
                    d.update(action="keep", reason="paid line, no spare SKU on quote")
                    flags.append(
                        f"line {line_id} ({ln['sku']}): value-bearing but no "
                        "spare equivalent — confirm orderable from stock"
                    )
                elif line_id == head and is_parent:
                    d.update(action="keep", reason="parent hardware (R1)")
                else:
                    sku = ln["sku"]
                    is_service = sku.upper().startswith(_SERVICE_PREFIX)
                    line_has_value = (
                        _num(ln.get("list")) > 0
                        or _num(ln.get("extlist")) > 0
                        or _num(ln.get("net")) > 0
                        or _num(ln.get("extnet")) > 0
                    )
                    if is_service:
                        d.update(action="keep", reason="service/term in kept bundle (R2)")
                    elif line_has_value:
                        d.update(action="keep",
                                 reason="value-bearing descendant in kept bundle")
                    else:
                        d.update(
                            action="flag",
                            reason=(
                                "UNKNOWN-DESCENDANT: non-CON-* zero-dollar child "
                                "in kept bundle — classify as keep or drop before export"
                            ),
                        )
                        flags.append(
                            f"line {line_id} ({sku}): UNKNOWN-DESCENDANT — "
                            "human classification required before export"
                        )
            else:
                d.update(
                    action="keep" if keep_zero_dollar_lines else "drop",
                    reason="zero-dollar bundle, ships in the box (R3)",
                )
            decisions.append(d)

    return decisions, flags


def translate_workbook(path, keep_zero_dollar_lines=False):
    """Translate every sheet. Returns a structured report dict."""
    wb = xlrd.open_workbook(path)
    report = {"file": path, "sheets": []}
    for name in wb.sheet_names():
        sheet = wb.sheet_by_name(name)
        try:
            orig, answer_key = read_tables(sheet)
        except ValueError as e:
            report["sheets"].append({
                "deal": name, "error": str(e),
                "input_lines": 0, "output_lines": 0,
                "decisions": [], "flags": [str(e)], "validation": None,
                "has_unknown_descendants": False,
            })
            continue

        decisions, flags = translate(orig, keep_zero_dollar_lines)
        has_unknown = any(d["action"] == "flag" for d in decisions)
        kept = [d for d in decisions if d["action"] not in ("drop", "flag")]

        sheet_result = {
            "deal": name,
            "input_lines": len([ln for ln in orig if not ln.get('_skip')]),
            "output_lines": len(kept),
            "decisions": decisions,
            "flags": flags,
            "validation": None,
            "has_unknown_descendants": has_unknown,
        }
        if answer_key:
            sheet_result["validation"] = _validate(kept, answer_key)
        report["sheets"].append(sheet_result)
    return report


def _validate(kept, answer_key):
    """Diff kept lines against answer key. Returns tri-state: pass/partial/fail."""
    exp_groups = {str(e["line"]).split(".")[0] for e in answer_key}
    all_kept_groups = {d["line"].split(".")[0] for d in kept}
    extra_groups = all_kept_groups - exp_groups

    exp_by_line: dict = {}
    for e in answer_key:
        k = str(e["line"])
        if not _LINE_ID_RE.match(k):
            continue  # malformed answer-key line — skip rather than crash
        exp_by_line.setdefault(k, []).append(e)

    my_by_line: dict = {}
    for d in kept:
        if d["line"].split(".")[0] in exp_groups:
            my_by_line.setdefault(d["line"], []).append(d)

    issues, warnings = [], []

    all_keys = sorted(
        set(exp_by_line) | set(my_by_line),
        key=_safe_sort_key,
    )
    for k in all_keys:
        exp_entries = exp_by_line.get(k, [])
        my_entries = my_by_line.get(k, [])
        for i, (e, m) in enumerate(zip(exp_entries, my_entries)):
            if e["sku"] != m["sku"]:
                issues.append(f"{k}[{i}]: expected {e['sku']}, got {m['sku']}")
        for e in exp_entries[len(my_entries):]:
            if _num(e.get("list")) > 0 or _num(e.get("extlist")) > 0:
                issues.append(f"{k}: value line {e['sku']} missing from output")
        for m in my_entries[len(exp_entries):]:
            issues.append(f"{k}: extra line {m['sku']} not in answer key")

    for g in sorted(extra_groups):
        warnings.append(
            f"group {g}: kept in output but not in answer key — validation partial"
        )

    result = "fail" if issues else ("partial" if warnings else "pass")
    return {"result": result, "issues": issues, "warnings": warnings}


def export_csv(report, out_path):
    """Write orderable lines to CSV.

    Raises ValueError if any sheet has unresolved UNKNOWN-DESCENDANTs —
    the caller must resolve all flags before export.
    Sanitizes all cells against Excel formula injection.
    Uses atomic write (temp file + rename) to avoid partial output.
    """
    blocked = [s["deal"] for s in report["sheets"] if s.get("has_unknown_descendants")]
    if blocked:
        raise ValueError(
            f"Export blocked: sheets {blocked} have unresolved UNKNOWN-DESCENDANT flags. "
            "Classify each flagged line as keep or drop before exporting."
        )

    out_dir = os.path.dirname(os.path.abspath(out_path))
    fd, tmp_path = tempfile.mkstemp(dir=out_dir, suffix=".csv.tmp")
    try:
        with os.fdopen(fd, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["DEAL"] + [x.upper() for x in OUT_FIELDS])
            for sheet in report["sheets"]:
                if "error" in sheet:
                    continue
                for d in sheet["decisions"]:
                    if d["action"] not in ("drop", "flag"):
                        w.writerow(
                            [_sanitize_csv(sheet["deal"])]
                            + [_sanitize_csv(d.get(k, "")) for k in OUT_FIELDS]
                        )
        os.replace(tmp_path, out_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return out_path
