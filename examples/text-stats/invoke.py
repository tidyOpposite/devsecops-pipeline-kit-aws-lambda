"""Exercise the real handler locally, without AWS or a simulated HTTP server."""

import argparse
import json
from pathlib import Path

from app import handler


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("event", type=Path)
    args = parser.parse_args()
    event = json.loads(args.event.read_text(encoding="utf-8"))
    result = handler(event, None)
    result["body"] = json.loads(result["body"])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if 200 <= result["statusCode"] < 300 else 1)
