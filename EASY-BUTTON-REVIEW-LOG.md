# Plan Review Log: Easy Button — CTO Quote → Stock-Fulfillment Translation
Started 2026-06-10. MAX_ROUNDS=5.

## Round 1 — Codex (read-only)
VERDICT: REVISE

Findings:
- [engine.py:52] `read_tables` indexes hardcoded columns without checking `sheet.ncols` — shifted/thinner workbook crashes or corrupts fields. Fix: validate column count upfront or resolve by header name.
- [engine.py:55] `read_tables` returns `blocks[0]` even for empty/nonmatching sheets. Fix: raise a controlled "no quote table found" error with sheet name.
- [engine.py:67] Line numbers parsed from `str(cell_value)` — Excel numeric `1.10` becomes `1.1`, grouping/sort wrong. Fix: read formatted text or require line-number cells to be typed as text.
- [engine.py:71] `float()` sort keys crash on blank/alphabetic/nonstandard line IDs. Fix: strict regex validator, flag unsupported formats.
- [engine.py:75] Value detection ignores `net`/`extnet` — fully discounted/list-zero but net-positive lines dropped. Fix: treat value as positive if any of list/extlist/net/extnet > 0.
- [engine.py:80] Any descendant in a paid bundle kept as R2, not just service/term lines — zero-dollar hardware/info children leak into output. Fix: classify by SKU prefix, drop or flag non-service zero-dollar children.
- [engine.py:81] Missing bundle-head lines not detected — descendants kept with no R4 swap opportunity. Fix: require exactly one head line per non-parent bundle.
- [engine.py:81] `ln["spare"]` not stripped — whitespace emitted as a SKU. Fix: normalize/strip all string fields before rules run.
- [engine.py:84] Missing-spare flags only fire when head `list > 0`, missing `extlist > 0` and descendant-value cases. Fix: flag any kept non-parent value-bearing bundle head with no spare SKU.
- [engine.py:118] Validation scopes to answer-key groups only — extra generated groups outside the key pass silently. Fix (disputed — see response).
- [engine.py:119] Validation maps by line number, collapsing duplicate line IDs silently. Fix: multimap keyed by (line, occurrence).
- [engine.py:124] Validation checks SKU only despite R5 requiring pricing preservation. Fix: compare qty/list/net/extnet fields (disputed — see response).
- [engine.py:135] CSV export formula-injection prone. Fix: escape cells beginning with `=`, `+`, `-`, `@`, tab, or CR.
- [agent.py:21] `claude_agent_sdk` absent from `requirements.txt` — ImportError before runtime error handling. Fix: add/pin dependency.
- [agent.py:94] File paths interpolated into prompt — path/newline prompt injection. Fix: structured tool arguments only.
- [agent.py:55] `export_quote` accepts arbitrary `out_path` from model. Fix: derive path deterministically, reject model-supplied paths outside approved directory.
- [translate.py:66] Divergent grouping/sorting behavior, can be run directly — two sources of truth. Fix: remove or make it delegate to engine.py.

### Claude's response — what changed, what was rejected, why

**Accepted (15 of 17):**
1. **`sheet.ncols` guard** — real crash path on non-standard XLS. Added to plan.
2. **Empty sheet IndexError** — controlled error with sheet name. Added.
3. **Excel float line ID truncation** — `1.10` → `1.1` is a silent correctness bug. Added.
4. **`float()` sort crash** — regex validator + flag. Added.
5. **`net`/`extnet` in value detection** — real bug for discounted deals. Added.
6. **Non-service zero-dollar descendants** — accepted as a flagging gap. Added.
7. **Missing bundle head not detected** — real R4 miss. Added.
8. **`ln["spare"]` whitespace** — simple correctness fix. Added.
9. **Missing-spare flag gap** — broader value detection needed. Added.
10. **Duplicate line IDs in validation** — multimap fix. Added.
11. **CSV formula injection** — real Excel security issue. Added.
12. **`claude_agent_sdk` missing from requirements** — real deployment gap. Added.
13. **Prompt injection via file path** — structured args fix. Added.
14. **`export_quote` arbitrary out_path** — path traversal risk. Added.
15. **translate.py two sources of truth** — must be removed or delegated. Added.

**Rejected (2 of 17):**
- **Validation scope to answer-key groups** — intentional design. Extra groups not in the answer key are by definition untested; scoping is the correct behavior for a regression harness. Logged as a known blind spot, not a bug.
- **Validation checks SKU only (not pricing)** — the answer key validates business correctness of the translation, not column parity. R5 pricing preservation is verified through the keep/swap/drop path, not the validation diff. Over-scope for this component.
