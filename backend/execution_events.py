"""Read durable per-worker timelines without losing actions between UI polls."""
import base64
import json
from pathlib import Path

from .safety import redact


def read_events(root: Path, after: str = "", limit: int = 150) -> dict:
    try:
        offsets = json.loads(base64.urlsafe_b64decode(after.encode()).decode()) if after else {}
        if not isinstance(offsets, dict) or any(not isinstance(v, int) or v < 0 for v in offsets.values()):
            raise ValueError("Invalid event cursor")
    except (ValueError, UnicodeError, TypeError) as exc:
        raise ValueError("Invalid event cursor") from exc
    events = []
    # Per-file offsets avoid skipping a late event from another worker.
    for path in sorted(root.glob("events.*.jsonl")):
        offset = offsets.get(path.name, 0)
        try:
            with path.open("rb") as stream:
                stream.seek(offset)
                while len(events) < limit:
                    line = stream.readline()
                    if not line or not line.endswith(b"\n"):
                        break  # do not consume a worker's partially written line
                    offset = stream.tell()
                    try:
                        value = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(value, dict):
                        events.append(json.loads(redact(json.dumps(value))))
        except OSError:
            continue
        offsets[path.name] = offset
        if len(events) >= limit:
            break
    cursor = base64.urlsafe_b64encode(json.dumps(offsets, sort_keys=True).encode()).decode()
    from .excel import case_hits
    from .finalization import read_json
    cases = read_json(root / "test_cases.json", [])
    for event in events:
        node = event.get("nodeid", "")
        result = {"nodeid": node, "file": node.split("::")[0], "test": event.get("test", "")}
        case = next((case for case in cases if case_hits(case, [result])), None)
        if case:
            event["case_title"], event["expected"] = redact(case.get("title", "")), redact(case.get("expected", ""))
    return {"events": sorted(events, key=lambda e: (e.get("timestamp", 0), e.get("id", ""))), "cursor": cursor}
