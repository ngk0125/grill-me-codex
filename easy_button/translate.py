"""CTO-to-stock-fulfillment quote translator.

Deterministic rule set derived from Steff's answer-key tables in
'Translation Example 1.xls'. Each sheet holds the original CTO quote
(first table) and the expected stock-fulfillment translation (second
table). Rules:

  R1. Parent hardware line (x.0) -> KEEP, SKU unchanged.
  R2. Service lines (children like x.0.1 / x.N.0.1, CON-*) -> KEEP unchanged
      if their bundle is kept.
  R3. Child bundles (x.N plus descendants x.N.*): if NO line in the bundle
      has list price > 0, DROP the whole bundle (included in the spare box).
  R4. If the bundle has value: the head line swaps to its SPARE EQUIVALENT
      SKU (col 32, the '=' SKU) when one exists; descendants keep their SKUs.
  R5. Deal pricing is preserved on every kept line (SKU changes, price
      columns do not).
"""
import sys
import xlrd

COL = dict(line=5, sku=7, included=8, qty=9, dur=10, list=14, extlist=15,
           net=16, extnet=17, spare=32)


def read_tables(sheet):
    """Split a sheet into (original, answer_key) line lists."""
    blocks, cur, empties = [], [], 0
    for r in range(1, sheet.nrows):
        vals = [sheet.cell_value(r, c) for c in range(sheet.ncols)]
        if all(v in ('', None) for v in vals):
            empties += 1
            continue
        if vals[0] == 'AUTHORIZATION NUMBER' or empties >= 2:
            if cur:
                blocks.append(cur)
                cur = []
        empties = 0
        if vals[0] == 'AUTHORIZATION NUMBER':
            continue
        cur.append({k: vals[c] for k, c in COL.items()})
    if cur:
        blocks.append(cur)
    return blocks[0], (blocks[1] if len(blocks) > 1 else [])


def lp(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def translate(lines):
    """Apply rules R1-R5 to an original CTO quote."""
    out = []
    groups = {}
    for ln in lines:
        g = str(ln['line']).split('.')[0]
        groups.setdefault(g, []).append(ln)
    for g, glines in groups.items():
        bundles = {}
        for ln in glines:
            parts = str(ln['line']).split('.')
            head = '.'.join(parts[:2])
            bundles.setdefault(head, []).append(ln)
        for head, bl in sorted(bundles.items(), key=lambda kv: [int(x) for x in kv[0].split('.')]):
            is_parent = head.endswith('.0')
            has_value = any(lp(l['list']) > 0 or lp(l['extlist']) > 0 for l in bl)
            if not is_parent and not has_value:
                continue
            for ln in bl:
                new = dict(ln)
                if ln['line'] == head and not is_parent and ln['spare']:
                    new['sku'] = ln['spare']
                out.append(new)
    return out


def validate(path):
    wb = xlrd.open_workbook(path)
    all_pass = True
    for name in wb.sheet_names():
        orig, expected = read_tables(wb.sheet_by_name(name))
        mine = translate(orig)
        print(f"\n=== Sheet {name}: {len(orig)} CTO lines -> {len(mine)} translated ===")
        if not expected:
            for m in mine:
                print(f"  {m['line']:10} {m['sku']}")
            continue
        exp_groups = {str(e['line']).split('.')[0] for e in expected}
        mine_scoped = [m for m in mine if str(m['line']).split('.')[0] in exp_groups]
        exp_map = {str(e['line']): e for e in expected}
        my_map = {str(m['line']): m for m in mine_scoped}
        ok = True
        for k in sorted(set(exp_map) | set(my_map), key=lambda s: [float(x) for x in s.split('.')]):
            e, m = exp_map.get(k), my_map.get(k)
            if e and m:
                if e['sku'] != m['sku']:
                    print(f"  MISMATCH {k}: expected SKU {e['sku']}, got {m['sku']}")
                    ok = False
                elif e['qty'] not in ('', None) and lp(e['qty']) != lp(m['qty']):
                    print(f"  MISMATCH {k}: qty differs")
                    ok = False
                elif e['list'] not in ('', None) and round(lp(e['list']), 2) != round(lp(m['list']), 2):
                    print(f"  MISMATCH {k}: price differs")
                    ok = False
                else:
                    print(f"  MATCH    {k:10} {m['sku']}")
            elif e:
                tag = 'zero-dollar info line' if lp(e['list']) == 0 and lp(e['extlist']) == 0 else 'VALUE LINE'
                print(f"  EXP-ONLY {k:10} {e['sku']}  ({tag})")
                if tag == 'VALUE LINE':
                    ok = False
            else:
                print(f"  MINE-ONLY {k:10} {m['sku']}")
                ok = False
        print(f"  -> {'PASS' if ok else 'FAIL'} (all value-bearing lines)")
        all_pass &= ok
    return all_pass


if __name__ == '__main__':
    sys.exit(0 if validate(sys.argv[1]) else 1)
