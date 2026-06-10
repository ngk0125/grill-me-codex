# Plan: Easy Button — CTO Quote → Stock-Fulfillment Translation
_Round 1 — revised after Codex adversarial review_

## Goal
Adversarially review the Easy Button tool, which deterministically converts Cisco CTO quote workbooks (.xls) to orderable stock-fulfillment line sets using a 5-rule engine (R1–R5). The tool is validated against 3 answer-key deals and wraps a Claude Agent SDK layer for orchestration. The core invariant: the engine never invents a SKU — anything outside the rules becomes a FLAG for human review.

## Architecture (what exists)

### engine.py — deterministic R1–R5 rule engine
- `read_tables(sheet)`: splits XLS sheet into (original_quote, answer_key). **Gap R1-1:** column offsets are hardcoded with no `sheet.ncols` guard — a shifted/thinner workbook silently corrupts fields or crashes. Fix: validate `sheet.ncols >= max(COL.values()) + 1` upfront, or resolve columns by header name. **Gap R1-2:** returns `blocks[0]` even for empty/non-matching sheets, raising an uncontrolled IndexError. Fix: raise a controlled "no quote table found" error with sheet name.
- Line ID handling: **Gap R1-3:** line numbers are parsed from `str(cell_value)`, so Excel stores `1.10` as float `1.1` — grouping and sort are silently wrong. Fix: read formatted cell text or require line-number cells to be typed as text. **Gap R1-4:** `float()` sort keys crash on blank/alphabetic/nonstandard line IDs. Fix: validate line IDs with `re.fullmatch(r'\d+(\.\d+)*', s)` and flag unsupported formats instead of crashing.
- `translate(lines, keep_zero_dollar_lines)`: **Gap R1-5:** value detection checks only `list` and `extlist` — a line with `list=0` but `net > 0` (fully discounted but orderable) is dropped by R3. Fix: treat a bundle as having value if ANY of `list`, `extlist`, `net`, or `extnet` is positive. **Gap R1-6:** any descendant in a paid bundle is kept as R2, not just service/term lines — zero-dollar hardware/info children leak into output. Fix: classify descendants by SKU prefix (`CON-*` = service/term) and drop or flag non-service zero-dollar children. **Gap R1-7:** missing bundle-head lines are not detected — descendants can be kept with no R4 swap opportunity. Fix: require exactly one head line per non-parent bundle; flag if absent. **Gap R1-8:** `ln["spare"]` is not stripped — whitespace can be emitted as a SKU. Fix: strip all string fields before rules run. **Gap R1-9:** missing-spare flags only fire when head `list > 0`, missing `extlist > 0` and descendant-value cases. Fix: flag any kept non-parent value-bearing bundle head with no spare SKU regardless of which pricing field carries the value.
- `_validate(kept, answer_key)`: **Known limitation (intentional):** scopes to answer-key groups only — extra generated groups outside the key are not checked. Documented blind spot. **Gap R1-10:** maps by line number, silently collapsing duplicate line IDs. Fix: use ordered list or multimap keyed by (line, occurrence index).
- `export_csv(report, out_path)`: **Gap R1-11:** cells not sanitized — values beginning with `=`, `+`, `-`, `@`, tab, or CR are formula-injection vectors in Excel. Fix: prefix such cells with a single quote or strip the leading character with a warning.

### agent.py — Claude Agent SDK wrapper
- **Gap R1-12:** `claude_agent_sdk` is imported at module top but absent from `requirements.txt` — ImportError fires before any runtime error handling. Fix: add/pin `claude-agent-sdk` to requirements.txt and guard the import with a clear install message.
- **Gap R1-13:** file paths interpolated directly into the prompt string — path containing newlines or special tokens can inject into tool argument parsing. Fix: pass file paths as structured tool arguments, not interpolated strings.
- **Gap R1-14:** `export_quote` accepts arbitrary `out_path` from the model and writes directly — no path validation, no symlink check. Fix: derive output path deterministically from input path and reject any model-supplied path outside the approved output directory.
- System prompt hard-locks SKU sourcing and blocks filesystem tools — correct.
- `disallowed_tools` blocks Bash, Write, Edit, WebSearch, WebFetch — correct.
- `max_turns=6` caps runaway loops — correct.

### translate.py — original standalone validator
- **Gap R1-15:** has divergent grouping/sorting behavior (uses `int()` not `float()` for sort keys) and can be run directly as `__main__` — two sources of truth with different outputs on float line IDs. Fix: remove as a runnable entry point, or make it a thin wrapper delegating entirely to `engine.py`.

## Key decisions & tradeoffs

1. **Column offsets hardcoded** — must be guarded with `sheet.ncols` check before shipping. Header-name resolution is the robust fix but requires knowing Cisco's canonical column headers.
2. **Value detection expanded** — must include `net`/`extnet` to correctly handle fully-discounted-but-orderable lines (Gap R1-5).
3. **Line ID parsing** — Excel float truncation (`1.10` → `1.1`) is a silent correctness bug that must be fixed before validating new deals.
4. **translate.py two-source-of-truth** — must be resolved (remove or delegate) before any further validation.
5. **Agent path injection and out_path** — structured args and path derivation must be enforced in the tools themselves, not just in `main()`.
6. **CSV formula injection** — sanitize cells before writing.
7. **`keep_zero_dollar_lines` flag** — Steff has not confirmed which behavior is canonical. Open config question.

## Risks / open questions

- **`sheet.ncols` guard**: if Cisco changes their XLS template, all column offsets silently shift.
- **`net > 0, list = 0` edge case**: unknown how many deals this affected in the 3 validated examples.
- **Agent SDK availability**: `claude-agent-sdk` must be in requirements. Installation path unclear.
- **Formula injection in CSV**: SKU or description containing `=`, `+`, `-`, `@` is an Excel vector.
- **`out_path` in export_quote**: model could be coerced into writing to arbitrary paths; derivation must be enforced in the tool itself.
- **Validation blind spot**: extra generated groups not in the answer key pass silently — noted as known limitation.

## Out of scope
- UI / web quote surface (next step per README)
- CIS inventory API integration (next step per README)
- Canada / non-U.S. quote formats
- .xlsx support (xlrd ≥ 2.0 does not support .xlsx)
- Multi-user concurrency hardening
- Pricing field comparison in `_validate` (answer key validates business correctness, not column parity)
