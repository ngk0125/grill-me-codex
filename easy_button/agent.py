"""Easy-button agent: CTO quote -> stock-fulfillment quote.

Wraps the deterministic translation engine (engine.py) in a Claude
Agent SDK agent. Division of labor, per Steff's requirements:

  - SKU decisions: 100% deterministic engine. The model NEVER picks,
    renames, or invents a SKU.
  - The agent: runs the tools, explains the result, surfaces flags for
    the human checkpoint, and writes the orderable CSV.

Trust boundary: the model is locked to translate_quote and export_quote.
export_quote derives its output path from the input path — the model
cannot supply an arbitrary out_path.

Auth comes from the local Claude Code install (~/.claude). No API keys.

Usage:
    python -m easy_button.agent <quote.xls> [--keep-zero-dollar-lines]
"""
import asyncio
import json
import os
import sys
from pathlib import Path

try:
    from claude_agent_sdk import (
        ClaudeAgentOptions,
        ClaudeSDKClient,
        CLINotFoundError,
        ProcessError,
        create_sdk_mcp_server,
        tool,
    )
except ImportError as e:
    print(
        f"error: claude-agent-sdk is not installed ({e}). "
        "Run: pip install claude-agent-sdk",
        file=sys.stderr,
    )
    sys.exit(2)

from .engine import export_csv, translate_workbook

_APPROVED_OUTPUT_DIR = None  # set at runtime to the input file's parent


def _safe_output_path(input_path: str) -> str:
    """Derive a safe output CSV path from the input path."""
    p = Path(input_path).expanduser().resolve()
    return str(p.with_suffix("")) + "_stock_fulfillment.csv"


def _validate_output_path(out_path: str, input_path: str) -> str:
    """Ensure out_path is the expected sibling CSV. Reject anything else."""
    expected = _safe_output_path(input_path)
    resolved = str(Path(out_path).expanduser().resolve())
    if resolved != expected:
        raise ValueError(
            f"output path '{out_path}' is not the expected sibling CSV "
            f"'{expected}' — rejected"
        )
    # Reject symlinks
    if Path(resolved).is_symlink():
        raise ValueError(f"output path '{resolved}' is a symlink — rejected")
    return resolved


@tool(
    "translate_quote",
    "Translate a Cisco CTO quote workbook (.xls) to its stock-fulfillment "
    "state using the validated deterministic rule set R1-R5. Returns per-line "
    "decisions (keep/swap/drop/flag with reasons), human-review flags, and "
    "answer-key validation when the sheet contains one.",
    {"path": str, "keep_zero_dollar_lines": bool},
)
async def translate_quote(args):
    path = str(Path(args["path"]).expanduser().resolve())
    if not Path(path).exists():
        return {"content": [{"type": "text", "text": f"error: file not found: {path}"}]}
    report = translate_workbook(path, bool(args.get("keep_zero_dollar_lines", False)))
    return {"content": [{"type": "text", "text": json.dumps(report, indent=1)}]}


@tool(
    "export_quote",
    "Write the kept (orderable) lines of the most recent translation to a "
    "CSV file the sales team can load. Output path is derived from the input "
    "path — the model cannot override it.",
    {"path": str, "keep_zero_dollar_lines": bool},
)
async def export_quote(args):
    path = str(Path(args["path"]).expanduser().resolve())
    if not Path(path).exists():
        return {"content": [{"type": "text", "text": f"error: file not found: {path}"}]}
    out = _safe_output_path(path)
    # Reject symlinks on the output path
    if Path(out).is_symlink():
        return {"content": [{"type": "text",
                              "text": f"error: output path is a symlink — rejected"}]}
    report = translate_workbook(path, bool(args.get("keep_zero_dollar_lines", False)))
    export_csv(report, out)
    return {"content": [{"type": "text", "text": f"written: {out}"}]}


SERVER = create_sdk_mcp_server(
    name="easy_button", version="1.0.0", tools=[translate_quote, export_quote]
)

SYSTEM_PROMPT = """You are the stock-fulfillment easy button for Cisco CTO quotes.

Hard rules:
- Every SKU you mention MUST come verbatim from translate_quote tool output.
  Never propose, correct, or invent a SKU under any circumstance.
- Always call translate_quote first, then export_quote.
- The export_quote tool derives its output path from the input path automatically.
  Do not attempt to specify or override the output path.
- Your report for each deal (sheet) contains exactly:
  1. Line counts: input -> orderable output.
  2. SKU swaps performed (original -> spare '=' SKU).
  3. Dropped bundles, one line: count + 'ship inside the spare box'.
  4. UNKNOWN-DESCENDANT flags: every flagged line, verbatim. If none, say so.
  5. FLAGS FOR HUMAN REVIEW: every other flag from the tool, verbatim. If none, say so.
  6. Validation: pass/partial/fail if the sheet had an answer key, else 'not present'.
- Keep it terse. A salesperson reads this before clicking order."""


async def run(quote_path: str, keep_zero: bool) -> int:
    options = ClaudeAgentOptions(
        mcp_servers={"easy_button": SERVER},
        allowed_tools=[
            "mcp__easy_button__translate_quote",
            "mcp__easy_button__export_quote",
        ],
        disallowed_tools=["Bash", "Write", "Edit", "WebSearch", "WebFetch"],
        system_prompt=SYSTEM_PROMPT,
        setting_sources=[],
        max_turns=6,
    )
    # Pass path as a JSON-encoded value in a structured prompt — not raw interpolation
    prompt = json.dumps({
        "action": "translate_and_export",
        "path": quote_path,
        "keep_zero_dollar_lines": keep_zero,
    })
    try:
        async with ClaudeSDKClient(options=options) as client:
            await client.query(
                f"Process this translation request: {prompt}"
            )
            async for message in client.receive_response():
                for block in getattr(message, "content", []) or []:
                    text = getattr(block, "text", None)
                    if text:
                        print(text)
    except CLINotFoundError:
        print("error: Claude Code CLI not found - install and log in first",
              file=sys.stderr)
        return 2
    except ProcessError as e:
        print(f"error: agent process failed (exit {e.exit_code})", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    quote = Path(args[0]).expanduser()
    if not quote.exists():
        print(f"error: {quote} not found", file=sys.stderr)
        return 2
    keep_zero = "--keep-zero-dollar-lines" in sys.argv
    return asyncio.run(run(str(quote.resolve()), keep_zero))


if __name__ == "__main__":
    sys.exit(main())
