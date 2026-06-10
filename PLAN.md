# Plan: Easy Button — CTO Quote → Stock-Fulfillment Translation
_Round 0 — design review by Claude_

## Goal
Adversarially review the Easy Button tool, which deterministically converts Cisco CTO quote workbooks (.xls) to orderable stock-fulfillment line sets using a 5-rule engine (R1–R5). The tool is validated against 3 answer-key deals and wraps a Claude Agent SDK layer for orchestration. The core invariant: the engine never invents a SKU — anything outside the rules becomes a FLAG for human review.

## Architecture (what exists)

### engine.py — deterministic R1–R5 rule engine
- `read_tables(sheet)`: splits XLS sheet into (original_quote, answer_key) by detecting 2+ empty rows or repeated header. Column offsets are hardcoded (`COL` dict: line=5, sku=7, spare=32, etc.).
- `translate(lines, keep_zero_dollar_lines)`: groups lines by bundle head (first two dot-segments of line number, e.g. "1.2"), determines keep/swap/drop per bundle:
  - R1: bundle head ending in `.0` → parent hardware, KEEP, SKU unchanged
  - R2: service/term descendants in a kept bundle → KEEP unchanged
  - R3: bundle with no list price > 0 anywhere → DROP (ships in the box)
  - R4: kept non-parent bundle head → SWAP to spare '=' SKU (col 32) if present
  - R5: pricing columns preserved on every kept line
- `translate_workbook(path)`: iterates sheets, calls translate, optionally validates against answer key
- `_validate(kept, answer_key)`: diffs kept lines against answer key — value-bearing mismatches, missing lines, extra lines all flagged
- `export_csv(report, out_path)`: writes orderable lines to CSV

### agent.py — Claude Agent SDK wrapper
- Exposes two MCP tools: `translate_quote`, `export_quote`
- System prompt hard-locks the model: every SKU must come verbatim from tool output; model cannot invent, correct, or rename SKUs
- `disallowed_tools` blocks Bash, Write, Edit, WebSearch, WebFetch — model cannot touch filesystem directly
- `max_turns=6` caps runaway loops
- Auth via local Claude Code install, no API keys

### translate.py — original standalone validator (reference only)
- Older, simpler version of the engine — same R1–R5 logic but without flags, structured report, or CSV export
- Uses `int()` for sort key (fails on float line numbers like "1.10") vs engine.py which uses `float()`

## Key decisions & tradeoffs

1. **Column offsets hardcoded** (`COL` dict). Works for the 3 validated deals. Brittle if Cisco changes the XLS column layout — no header-name lookup, no guard.

2. **Bundle grouping by first two dot-segments** (`".".join(parts[:2])`). Correct for standard Cisco line numbering (x.0, x.N, x.N.M). Untested on non-standard formats (e.g. 3-level parents, alphabetic groups).

3. **`has_value` checks only `list` and `extlist`** — not `net` or `extnet`. A line with `list=0` but `net>0` (fully discounted but still orderable) would be dropped by R3. This may be wrong for deeply discounted deals.

4. **`keep_zero_dollar_lines` flag** — binary switch for tab-3 behavior. No per-bundle granularity. Steff has not confirmed which is canonical.

5. **No deduplication of flags** — the same flag string could appear multiple times if multiple lines in the same bundle lack a spare SKU.

6. **agent.py imports `claude_agent_sdk`** — non-standard package name (standard SDK is `anthropic`). Either a local package or a wrapper — not verifiable without the environment. If it doesn't exist, the agent silently fails with an ImportError.

7. **translate.py sort key uses `int()`** — fails on float line numbers (e.g. "1.10"). engine.py fixes this with `float()`. The old file is kept "for reference" but could cause confusion.

8. **No input validation on the XLS path** — `xlrd.open_workbook(path)` raises a raw exception on bad paths, password-protected files, or .xlsx (xlrd dropped .xlsx support in v2.0). No user-friendly error handling.

9. **`_validate` scope filtering** — `exp_groups` filters kept lines to only the groups appearing in the answer key. Extra kept groups (not in the answer key) are silently ignored in validation. A translation that adds spurious groups passes validation.

10. **CSV export re-runs the engine** — `export_quote` calls `translate_workbook` again rather than caching the result. Deterministic so correct, but wasteful and theoretically inconsistent if the XLS is modified between calls.

## Risks / open questions

- **xlrd .xlsx failure**: xlrd ≥ 2.0 does not support .xlsx. If a user passes an .xlsx file, it raises an opaque `xlrd.biffh.XLRDError`. No guard or user-facing message.
- **Column layout drift**: If Cisco changes their XLS template, all column offsets silently shift. No header-name validation to catch this.
- **`net > 0, list = 0` edge case**: Fully discounted but orderable lines dropped by R3 incorrectly.
- **Agent SDK availability**: `claude_agent_sdk` package must be present. No `requirements.txt` or `pyproject.toml` visible — installation path unclear.
- **Concurrent use**: No file locking on `/tmp/codex-verdict.txt` or the output CSV — concurrent runs could collide.
- **Float line sort in translate.py**: The old validator uses `int()` for sort, breaks on lines like "1.10". Should be removed or replaced, not kept as reference.

## Out of scope
- UI / web quote surface (next step per README)
- CIS inventory API integration (next step per README)
- Canada / non-U.S. quote formats
- .xlsx support
- Multi-user concurrency hardening
