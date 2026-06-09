# Plan: Cisco Fulfillment Optimization — Five-Agent AI Pipeline
_Locked via grill — by Claude + Nabeel Kahwash_

## Goal
Build a five-agent Python CLI pipeline (`file_validator → spa_parser → eligibility_engine → inventory_pricer → recommendation_writer`) that reads a Cisco SPA Deal ID Excel file, applies a four-gate eligibility engine with DNA/EA 3.0 auto-pass and a hard pricing ceiling, calls the TDS Inventory API (mocked until credentials confirmed), and produces a structured JSON fulfillment recommendation (Option A vs Option B per ship set). Option C is hard-suppressed for Phase 1. The pipeline lives in `src/pipeline/` alongside the existing Maple AI FastAPI service, which is not broken. Checkpoints are written after each agent to enable `--reset-from step{n}` recovery. Outcomes are logged to `OUTPUTS/outcomes.jsonl` for Power BI monitoring.

## Approach
1. **Scaffold `src/pipeline/`** with modules: `models.py`, `checkpoint.py`, `file_validator.py`, `spa_parser.py`, `eligibility_engine.py`, `inventory_pricer.py`, `recommendation_writer.py`, `pipeline.py` (CLI orchestrator).
2. **`file_validator`** — confirm `.xlsx`/`.xls` format; verify required columns present (`LINE#`, `INCLUDED ITEM`, `SPARE EQUIVALENT SKU NAME`, `UNIT NET PRICE`, `BpaBuyingProgram`). Fail fast with structured `ValidationError`. Write `OUTPUTS/checkpoints/step1.json`.
3. **`spa_parser`** — parse all line items via `pandas.read_excel()` (handles both `.xlsx` via `openpyxl` and `.xls` via `xlrd` automatically). Group lines by ship set: `ship_set_id = int(str(row["LINE#"]).split('.')[0])` (explicit stringify — openpyxl/pandas return numeric cells as float). Extract per-line fields. Write `OUTPUTS/checkpoints/step2.json`.
4. **`eligibility_engine`** — apply four gates per line in sequence; stop at first failure:
   - Gate 1: `INCLUDED ITEM != "Yes"`
   - Gate 2: `order_type not in {125, "XaaS-Annu"}`
   - Gate 3: `ship_complete_flag != True` (if column absent/undetectable → conservative pass, flag `gate3_unverifiable=True`)
   - Gate 4: `SPARE EQUIVALENT SKU NAME` is non-empty
   - DNA auto-pass: `BpaBuyingProgram == "EA 3.0"` AND `UNIT NET PRICE == 0` AND `SKU.endswith("=")` → eligible without API call, `dna_auto_pass=True`
   - Write `OUTPUTS/checkpoints/step3.json`.
5. **`inventory_pricer`** — for each eligible non-DNA line call `InventoryClient.get_inventory([spare_sku])`. The TDS Inventory API must return `available_qty`, `spare_list_price`, and `spare_sku_discount` per SKU; these are added to the pipeline's extended `InventoryRecord` model. Calculate `spare_net_price = spare_list_price × (1 − spare_sku_discount)`. Ceiling: `spare_net_price > UNIT NET PRICE` → BLOCK (suppress Option B, log to review queue). `spare_net_price > 0.95 × UNIT NET PRICE` → WARN flag. Write `OUTPUTS/checkpoints/step4.json`.
6. **`recommendation_writer`** — per ship set emit structured JSON: Option A (always, ~4 weeks); Option B (warehouse, 1–3 days) if all *gate-passed* lines have confirmed stock and pass pricing ceiling (lines that failed eligibility gates are neutral — they don't block Option B); else Option B suppressed with reason. `review_queue` items; `confidence` rating: `HIGH` = all eligible lines confirmed stock + no WARN/BLOCK flags; `MEDIUM` = ≥1 WARN flag or `gate3_unverifiable`; `LOW` = any BLOCK flag or zero eligible lines. `option_c_suppressed: true` always. Write `OUTPUTS/recommendation_{deal_id}.json`. Atomically append record to `OUTPUTS/outcomes.jsonl` using `filelock` (cross-platform).
7. **`pipeline.py` CLI** — flags: `--file`, `--deal-id` (optional override for deal ID extracted from the file; used for output filenames and `outcomes.jsonl`; defaults to ID extracted by `spa_parser`), `--reset-from step{n}`, `--mock-inventory`, `--keep-checkpoints`. Client selection: `--mock-inventory` flag always wins over env var; otherwise `LiveInventoryClient` if `INVENTORY_API_URL` is set, else pipeline `MockInventoryClient`. `outcomes.jsonl` atomic append: use `filelock` library (cross-platform; handles both Linux Dart AI Labs and Windows environments). On successful completion, checkpoint files deleted unless `--keep-checkpoints` is passed.
8. **`PipelineInventoryClient` ABC + `LiveInventoryClient`** — defined in `src/pipeline/models.py`. `PipelineInventoryRecord` extends `InventoryRecord` with `spare_list_price: float` and `spare_sku_discount: float`. `PipelineInventoryClient` ABC returns `PipelineInventoryResponse`. `LiveInventoryClient` and pipeline's `MockInventoryClient` implement `PipelineInventoryClient`. The existing `InventoryClient` ABC and `InventoryResponse` model in `src/inventory/` are **not modified** — Maple AI service remains unaffected. `LiveInventoryClient` reads `INVENTORY_API_URL` + `INVENTORY_API_KEY` from env.
9. **Tests** — `tests/pipeline/` with fixture Excel files (or sanitized stubs) for Deal IDs 83737219, 84709746, 84251013. Assert zero false passes (SC-02). Assert pricing ceiling never violated (SC-03). Assert Option C never in output.

## Key decisions & tradeoffs
- **Direct Excel parsing vs LLM:** `pandas.read_excel()` (with `openpyxl` for `.xlsx`, `xlrd` for `.xls`). Cisco SPA columns are deterministic (confirmed on 3 Deal IDs). LLM adds latency, cost, nondeterminism for a structured problem. Existing `parse_quote_file` (LLM) left untouched for unstructured quote text.
- **New module vs refactor:** `src/pipeline/` added alongside existing `src/`. Existing Maple AI FastAPI service not broken. Pipeline defines its own `PipelineInventoryClient` ABC and `PipelineInventoryRecord` (adds `spare_list_price`, `spare_sku_discount`) — existing `InventoryClient` ABC is left unmodified.
- **Option C hard-suppression:** `OPTION_C_ENABLED = False` constant in `recommendation_writer.py`. Requires code change (not config) to unlock — deliberate friction requiring Nicko Roussos sign-off.
- **Gate 3 under uncertainty:** If `ship_complete_flag` column is absent in SPA file, line is passed conservatively with `gate3_unverifiable=True`. Avoids silently blocking legitimate warehouse fulfillment. Confirmed as acceptable interim stance per BRD R-03.
- **`option_selected` null at pipeline time:** Pipeline emits `option_selected: null` in `outcomes.jsonl`. Actual rep selection must be recorded via a separate mechanism (post-booking hook or API). This is a noted Phase 1 gap.
- **Checkpoint format:** Full agent output as JSON after each step. `--reset-from step{n}` loads checkpoint `n-1`, re-runs from agent `n` forward.

## Risks / open questions
- **R-01 (blocking):** TDS Inventory API mode unknown. `LiveInventoryClient` built but untested. If batch mode, `inventory_pricer` must add staleness warning.
- **R-02 (blocking):** WebQuote extensibility unconfirmed. Pipeline outputs JSON only; panel integration deferred. Fallback: HTML report from `recommendation_writer`.
- **R-03:** Gate 3 detectability unconfirmed. Conservative-pass strategy in place.
- **`option_selected` recording:** No mechanism yet to capture rep's final choice for Power BI KPI (SC-05).

## Out of scope
- Pre-WebQuote advisory panel UI (blocked by R-02)
- Power BI dashboard build (outcomes.jsonl format defined and ready)
- Option C / hybrid fulfillment
- Canada SPA data (Phase 2)
- Post-CIS order modification
- Non-Cisco vendor lines
- Refactoring existing Maple AI FastAPI service
