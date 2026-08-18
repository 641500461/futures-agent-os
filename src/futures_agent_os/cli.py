"""Local command-line entry point."""

import argparse
import json
from collections.abc import Sequence

from futures_agent_os.health import get_health_status


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="futures-agent-os")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("health", help="print the local health contract")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "health":
        print(json.dumps(get_health_status().as_dict(), ensure_ascii=False, sort_keys=True))
        return 0
    return 2
