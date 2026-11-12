"""Generate a portable stdio client example for the current checkout; no client settings are changed."""
import argparse
import json
import os
from pathlib import Path


def configuration(root: Path) -> dict:
    python = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return {"mcpServers": {"blow-ai": {
        "command": str(python.resolve()),
        "args": ["-u", "-B", str((root / "mcp_entry.py").resolve())],
        "env": {"BLOWAI_UI_URL": "http://127.0.0.1:8000"},
    }}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Write generated example; default prints JSON only")
    args = parser.parse_args()
    content = json.dumps(configuration(Path(__file__).resolve().parent.parent), indent=2) + "\n"
    if args.output:
        args.output.write_text(content, encoding="utf-8")
        print(f"Saved client example: {args.output}")
    else:
        print(content, end="")


if __name__ == "__main__":
    main()
