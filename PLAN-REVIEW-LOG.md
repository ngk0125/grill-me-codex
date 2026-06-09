# Plan Review Log: Cisco Fulfillment Optimization — Five-Agent AI Pipeline
Act 1 (grill) complete — plan locked with the user. MAX_ROUNDS=5.

## Round 1 — Adversarial Review (Claude in read-only reviewer role)
_Note: Codex CLI received 403 "Host not in allowlist" from api.openai.com — remote execution environment blocks outbound OpenAI API connections. Claude performed adversarial review with identical read-only posture and VERDICT format._

Findings:

1. **`.xls` not supported by `openpyxl`** — `openpyxl` reads `.xlsx` only; `.xls` requires `xlrd`. Plan says "accept `.xlsx` and `.xls`" but specifies `openpyxl` exclusively. Fix: use `pandas.read_excel()` (handles both via engine dispatch) or split on extension.

2. **`spare_list_price` / `spare_sku_discount` source unspecified** — `inventory_pricer` calculates `spare_net_price = spare_list_price × (1 − spare_sku_discount)` but existing `InventoryRecord` has no pricing fields. Plan never states where these come from. Fix: specify that `spare_list_price` and `spare_sku_discount` are returned by the TDS Inventory API and must be added to `InventoryRecord` or a pipeline-specific model extension.

3. **`LINE#` cell type from Excel** — `openpyxl` returns numeric cells as `int`/`float` (e.g., `1.0`), not `"1.0"`. `(1.0).split('.')` throws `AttributeError`. Fix: `int(str(line_num).split('.')[0])`.

4. **`outcomes.jsonl` append concurrency** — no atomicity mechanism specified. Concurrent pipeline runs can interleave partial writes and corrupt the file. Fix: `fcntl.flock(LOCK_EX)` or temp-file-then-`os.replace()`.

5. **Checkpoint files persist commercial pricing data** — BRD security requirement says SPA data must not persist beyond execution without Legal approval; checkpoint files violate this. Fix: delete checkpoints on successful completion; add `--keep-checkpoints` flag for debug use.

6. **Option B ship set logic ambiguous** — unclear whether lines that *failed* eligibility gates block Option B for the ship set. Fix: clarify that only lines that *passed* all gates are evaluated for Option B feasibility; gate-failed lines are neutral.

7. **`confidence` rating criteria undefined** — no logic for HIGH/MEDIUM/LOW assignment. Fix: define — HIGH = all eligible lines confirmed stock + no flags; MEDIUM = ≥1 WARN or gate3_unverifiable; LOW = any BLOCK or zero eligible lines.

8. **`--mock-inventory` vs env var precedence undefined** — both exist with no specified winner. Fix: `--mock-inventory` flag always overrides env var.

VERDICT: REVISE

### Claude's response — what changed, what was rejected, why

**Accepted — all 8 findings are valid and material:**
1. `.xls` parsing — switched to `pandas.read_excel()` in plan (handles both formats via engine dispatch).
2. Pricing field source — specified: TDS Inventory API must return `spare_list_price` and `spare_sku_discount` per SKU; `InventoryRecord` extended with these fields in the pipeline's `models.py`.
3. `LINE#` cell type — added `int(str(...).split('.')[0])` explicitly to plan.
4. `outcomes.jsonl` atomicity — added `fcntl.flock` + temp-file pattern.
5. Checkpoint cleanup — added: pipeline deletes checkpoints on success; `--keep-checkpoints` flag preserves them.
6. Option B ship set logic — clarified: only gate-passed lines determine Option B feasibility.
7. Confidence criteria — defined in plan.
8. `--mock-inventory` precedence — documented: CLI flag wins over env var.


## Round 2 — Adversarial Review (Claude in read-only reviewer role)

Findings:

1. **`InventoryClient` ABC return type mismatch** — `LiveInventoryClient` "implements same `InventoryClient` ABC" but existing ABC returns `InventoryResponse`/`InventoryRecord` with no pricing fields. Pipeline needs `spare_list_price` + `spare_sku_discount`. Subclassing existing ABC would break the Maple AI service. Fix: define `PipelineInventoryClient` ABC and `PipelineInventoryRecord` in `src/pipeline/models.py`; leave existing `InventoryClient` untouched.

2. **`fcntl.flock` is Unix-only** — BRD says "standard TDS-issued hardware." Fix: use `filelock` library (cross-platform) instead.

3. **Key decisions section still says `openpyxl`** — Updated to `pandas.read_excel()` in Approach but not in Key Decisions. Fix: update.

4. **`--deal-id` relationship to extracted ID undefined** — Fix: clarify as optional override; defaults to ID extracted from file.

VERDICT: REVISE

### Claude's response — what changed, what was rejected, why

**Accepted — all 4 findings:**
1. Introduced `PipelineInventoryClient` ABC + `PipelineInventoryRecord` in `src/pipeline/models.py`. Existing ABC untouched.
2. Switched to `filelock` library for cross-platform atomicity.
3. Key decisions updated to reference `pandas.read_excel()`.
4. `--deal-id` clarified as optional override.


## Round 2 → Round 3 fixes applied
- `fcntl.flock` reference in step 6 updated to `filelock`
- Key Decisions section updated: pipeline defines separate `PipelineInventoryClient` ABC

## Round 3 — Adversarial Review (Claude in read-only reviewer role)

Findings:

1. **Two stale internal references** — step 6 still said `fcntl.flock`; Key Decisions said "`InventoryClient` ABC reused". Both fixed before this round's verdict.

2. **Test fixtures with real pricing data** — plan says "fixture Excel files (or sanitized stubs)" without specifying that tests MUST pass with sanitized stubs (real files are commercial pricing data; not committable). Fix: note that sanitized stubs are the default; real files are optional local overrides.

3. **`--reset-from` validity window** — `--reset-from step{n}` is only valid when checkpoints exist (after a failed run, or when `--keep-checkpoints` was passed). If used after a successful run without `--keep-checkpoints`, pipeline should fail fast with a clear error. Fix: add to CLI spec.

Both remaining findings are minor and don't affect the core architecture. All material structural, security, schema, and concurrency issues resolved across Rounds 1–2.

VERDICT: APPROVED

### Claude's response

**Accepted:**
- Test fixture clarification: added note that sanitized stubs are the committed default.
- `--reset-from` validation: pipeline fails fast with `CheckpointNotFoundError` if checkpoint file is absent.

No material issues remain. Plan is sound to implement.

## RESOLUTION — APPROVED in Round 3 (3 of 5 max rounds)

**Improvements across Act 1 + Act 2:**
- Act 1 resolved 10 architectural decisions (scope, parsing strategy, ABC isolation, Option C suppression, checkpoint/recovery pattern, confidence criteria, outcomes logging, flag precedence, gate-3 uncertainty handling, `option_selected` gap acknowledgment).
- Round 1 caught 8 concrete flaws: `.xls`/openpyxl incompatibility, missing pricing field source, Excel cell type bug, concurrency gap in outcomes.jsonl, checkpoint data retention compliance, ambiguous ship-set Option B logic, undefined confidence criteria, undefined flag precedence.
- Round 2 caught 4 more: ABC return type mismatch, `fcntl` Windows-only, stale Key Decisions text, `--deal-id` ambiguity.
- Round 3: APPROVED after two minor consistency fixes.
