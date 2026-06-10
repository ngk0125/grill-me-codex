"""Easy-button agent: CTO quote -> stock-fulfillment quote.

Wraps the deterministic translation engine (engine.py) in a Claude
Agent SDK agent. Division of labor, per Steff's requirements:

  - SKU decisions: 100% deterministic engine. The model NEVER picks,
    renames, or invents a SKU.
  - The agent: runs the tools, explains the result, surfaces flags for
    the human checkpoint, and writes the orderable CSV.

Auth comes from the local Claude Code install (~/.claude). No API keys.

Usage:
    python -m easy_button.agent <quote.xls> [--keep-zero-dollar-lines]
"""
import asyncio
import json
import sys
from pathlib import Path

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    CLINotFoundError,
    ProcessError,
    create_sdk_mcp_server,
    tool,
)

from .engine import export_csv, translate_workbook


@tool(
    "translate_quote",
    "Translate a Cisco CTO quote workbook (.xls) to its stock-fulfillment "
    "state using the validated deterministic rule set R1-R5. Returns per-line "
    "decisions (keep/swap/drop with reasons), human-review flags, and "
    "answer-key validation when the sheet contains one.",
    {"path": str, "keep_zero_dollar_lines": bool},
)
async def translate_quote(args):
    report = translate_workbook(
        args["path"], bool(args.get("keep_zero_dollar_lines", False))
    )
    return {"content": [{"type": "text", "text": json.dumps(report, indent=1)}]}


@tool(
    "export_quote",
    "Write the kept (orderable) lines of the most recent translation to a "
    "CSV file the sales team can load. Re-runs the engine on the same "
    "workbook to guarantee the CSV matches the deterministic output.",
    {"path": str, "out_path": str, "keep_zero_dollar_lines": bool},
)
async def export_quote(args):
    report = translate_workbook(
        args["path"], bool(args.get("keep_zero_dollar_lines", False))
    )
    out = export_csv(report, args["out_path"])
    return {"content": [{"type": "text", "text": f"written: {out}"}]}


SERVER = create_sdk_mcp_server(
    name="easy_button", version="1.0.0", tools=[translate_quote, export_quote]
)

SYSTEM_PROMPT = """You are the stock-fulfillment easy button for Cisco CTO quotes.

Hard rules:
- Every SKU you mention MUST come verbatim from translate_quote tool output.
  Never propose, correct, or invent a SKU under any circumstance.
- Always call translate_quote first, then export_quote.
- Your report for each deal (sheet) contains exactly:
  1. Line counts: input -> orderable output.
  2. SKU swaps performed (original -> spare '=' SKU).
  3. Dropped bundles, one line: count + 'ship inside the spare box'.
  4. FLAGS FOR HUMAN REVIEW: every flag from the tool, verbatim. If none, say so.
  5. Validation: PASS/FAIL if the sheet had an answer key, else 'not present'.
- Keep it terse. A salesperson reads this before clicking order."""


async def run(quote_path: str, out_csv: str, keep_zero: bool) -> int:
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
    prompt = (
        f"Translate the CTO quote workbook at {quote_path} to stock fulfillment "
        f"(keep_zero_dollar_lines={json.dumps(keep_zero)}), export the orderable "
        f"lines to {out_csv}, and give me the per-deal report."
    )
    try:
        async with ClaudeSDKClient(options=options) as client:
            await client.query(prompt)
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
    out_csv = str(quote.with_suffix("")) + "_stock_fulfillment.csv"
    keep_zero = "--keep-zero-dollar-lines" in sys.argv
    return asyncio.run(run(str(quote), out_csv, keep_zero))


if __name__ == "__main__":
    sys.exit(main())
