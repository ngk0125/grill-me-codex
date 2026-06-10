# Plan: Easy Button — CTO Quote → Stock-Fulfillment Translation
_Round 4 — revised after Codex adversarial review_

## Goal
Adversarially review the Easy Button tool, which deterministically converts Cisco CTO quote workbooks (.xls) to orderable stock-fulfillment line sets using a 5-rule engine (R1–R5). The tool is validated against 3 answer-key deals and wraps a Claude Agent SDK layer for orchestration. The core invariant: the engine never invents a SKU — anything outside the rules becomes a FLAG for human review.

## Architecture (what exists)

### engine.py — deterministic R1–R5 rule engine
- `read_tables(sheet)`: splits XLS sheet into (original_quote, answer_key). **Gap R1-1 (sharpened R3):** column offsets are hardcoded — `sheet.ncols >= max(COL.values()) + 1` only prevents crashes; a shifted workbook still silently reads wrong fields. Fix: validate expected header text at each fixed offset (e.g. assert cell(0, COL["sku"]) == "SKU") or resolve all columns by header name. Fail closed on schema mismatch. **Gap R1-2:** returns `blocks[0]` even for empty/non-matching sheets, raising an uncontrolled IndexError. Fix: raise a controlled "no quote table found" error with sheet name.
- Line ID handling: **Gap R1-3 (sharpened R3):** line numbers parsed from `str(cell_value)` — Excel already coerced `1.10` to float `1.1` before we read it, so "require text cells" doesn't recover the coerced value. Fix: inspect `cell.ctype` at read time and reject any numeric-typed line cell with a clear error ("line ID is numeric — re-export with line column as text"). **Gap R1-4:** `float()` sort keys crash on blank/alphabetic/nonstandard line IDs. Fix: validate line IDs with `re.fullmatch(r'\d+(\.\d+)*', s)` and flag unsupported formats instead of crashing.
- `translate(lines, keep_zero_dollar_lines)`: **Gap R1-5:** value detection checks only `list` and `extlist` — a line with `list=0` but `net > 0` (fully discounted but orderable) is dropped by R3. Fix: treat a bundle as having value if ANY of `list`, `extlist`, `net`, or `extnet` is positive. **Gap R1-6 (sharpened R3):** any descendant in a paid bundle is kept as R2, not just service/term lines. `CON-*` prefix is a brittle classifier — Cisco service, software, and support lines may not all use that prefix. Fix: keep `CON-*` as the primary classifier but flag any non-`CON-*` descendant with `list=0` as UNKNOWN-DESCENDANT for human review rather than silently keeping or dropping it. **Gap R1-7:** missing bundle-head lines not detected — descendants can be kept with no R4 swap opportunity. Fix: require exactly one head line per non-parent bundle; flag if absent. **Gap R1-8:** `ln["spare"]` not stripped — whitespace can be emitted as a SKU. Fix: strip all string fields before rules run. **Gap R1-9:** missing-spare flags only fire when head `list > 0`, missing `extlist > 0` and descendant-value cases. Fix: flag any kept non-parent value-bearing bundle head with no spare SKU regardless of which pricing field carries the value.
- `_validate(kept, answer_key)`: **Gap R4-1 (sharpened):** extra generated groups emit WARN but the return dict still has `"pass": bool` — callers cannot distinguish a full pass from a partial one. Fix: make validation tri-state: `"pass"` (all groups validated, no issues), `"partial"` (some groups outside answer key scope — WARN emitted), `"fail"` (value-line mismatches or missing lines). Block any "PASS" reporting to the user when result is `"partial"`. **Gap R1-10:** maps by line number, silently collapsing duplicate line IDs. Fix: use ordered list or multimap keyed by (line, occurrence index).
- `export_csv(report, out_path)`: **Gap R1-11:** cells not sanitized — values beginning with `=`, `+`, `-`, `@`, tab, or CR are formula-injection vectors in Excel. Fix: prefix such cells with a single quote or strip the leading character with a warning.

### agent.py — Claude Agent SDK wrapper
- **Gap R1-12:** `claude_agent_sdk` absent from `requirements.txt` — ImportError fires before runtime error handling. Fix: add/pin `claude-agent-sdk` to requirements.txt and guard the import with a clear install message.
- **Gap R1-13:** file paths interpolated into prompt string — path/newline injection. Fix: pass file paths as structured tool arguments only.
- **Gap R1-14:** `export_quote` accepts arbitrary `out_path` from model — no path validation or symlink check. Fix: derive output path deterministically from input path inside the tool; reject anything else.
- **Trust boundary clarification (R4-2):** "blocks filesystem tools" is misleading — `export_quote` itself IS a filesystem write primitive exposed to the model. The actual trust boundary is: the model cannot pick arbitrary tool names (locked to `translate_quote` and `export_quote`), and within `export_quote` the output path must be derived from the input path, not model-supplied. State this explicitly rather than claiming "filesystem is blocked."
- System prompt hard-locks SKU sourcing — correct.
- `disallowed_tools` blocks Bash, Write, Edit, WebSearch, WebFetch — correct.
- `max_turns=6` caps runaway loops — correct.

### translate.py — original standalone validator
- **Gap R1-15:** divergent grouping/sorting behavior (`int()` not `float()` for sort keys), runnable as `__main__` — two sources of truth. Fix: remove runnable entry point or make it a thin wrapper delegating entirely to `engine.py`.

## Key decisions & tradeoffs

1. **Column schema validation** — `sheet.ncols` count is insufficient. Must validate header text at fixed offsets (or resolve by name) and fail closed on mismatch. Cisco's canonical column headers must be documented before this can be implemented.
2. **Line ID `cell_type` check** — Excel coercion is irreversible at read time; the fix must happen at `cell.ctype` inspection, not post-read string parsing.
3. **Descendant classifier** — `CON-*` is kept as primary classifier; unknown non-`CON-*` zero-dollar descendants become UNKNOWN-DESCENDANT flags. **Gap R4-3:** UNKNOWN-DESCENDANT flags have no resolution path — a rep cannot export until every flag is resolved or acknowledged. Fix: require either (a) an explicit allowlist of non-`CON-*` service/software prefixes sourced from real Cisco exports, or (b) a human-classification gate: the tool blocks export until every UNKNOWN-DESCENDANT is classified by the rep as "keep" or "drop." Option (b) is the safe default until the allowlist is built.
4. **Validation extra-group warning** — extra groups not in the answer key emit a WARN (not hard fail). Validation is explicitly partial when this fires.
5. **Value detection expanded** — must include `net`/`extnet` (Gap R1-5).
6. **translate.py two-source-of-truth** — must be resolved before any further validation.
7. **Agent path injection and out_path** — structured args and path derivation enforced in the tools.
8. **CSV formula injection** — sanitize cells before writing.
9. **`keep_zero_dollar_lines` flag** — Steff has not confirmed which behavior is canonical. Open config question.

## Risks / open questions

- **Cisco canonical column headers**: header-name resolution requires knowing Cisco's exact header strings. Must be confirmed before the schema validation fix can be implemented.
- **`cell.ctype` line ID check**: xlrd cell type constants must be confirmed (`xlrd.XL_CELL_NUMBER = 2`) before implementation.
- **`CON-*` completeness**: if Cisco uses non-`CON-*` prefixes for service/software lines, UNKNOWN-DESCENDANT flags will fire on legitimate lines. Requires a sample of real Cisco XLS exports to calibrate.
- **`net > 0, list = 0` edge case**: unknown how many of the 3 validated deals have fully-discounted orderable lines.
- **Agent SDK package name**: `claude-agent-sdk` vs `claude_agent_sdk` — must confirm exact PyPI name before adding to requirements.
- **Formula injection in CSV**: any SKU or description containing `=`, `+`, `-`, `@` is an Excel vector.
- **Validation partial coverage**: extra generated groups not in the answer key now emit WARN — callers must handle this.

## Out of scope
- UI / web quote surface (next step per README)
- CIS inventory API integration (next step per README)
- Canada / non-U.S. quote formats
- .xlsx support (xlrd ≥ 2.0 does not support .xlsx)
- Multi-user concurrency hardening
- Pricing field column-parity comparison in `_validate` — `_validate` is a SKU-correctness diff, not a column audit. **However, the claim "R5 is validated" is corrected:** R5 pricing preservation is enforced by the keep/swap/drop path copying the price dict, but it is NOT verified by `_validate`. This is a known gap — `_validate` does not catch pricing corruption bugs. Callers must not interpret a `_validate` pass as evidence that pricing is correct.
