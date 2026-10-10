"""Human-only local identity intake. Never register this command as an AI tool."""

import argparse
import json
import sys
from pathlib import Path

from okama_planner.storage import PlannerStore


def main(argv: list[str] | None = None) -> int:
    """Import identity files locally, returning only the assigned client code."""
    parser = argparse.ArgumentParser(
        description='Private local client intake; keep identity JSON outside AI tools'
    )
    parser.add_argument('operation', choices=('create', 'update', 'save-plan'))
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--code')
    arguments = parser.parse_args(argv)
    try:
        data = json.loads(arguments.input.read_text(encoding='utf-8'))
        with PlannerStore.open(arguments.database) as store:
            if arguments.operation == 'create':
                code = store.create_client(data)['code']
            else:
                if not arguments.code:
                    raise ValueError('A client code is required')
                if arguments.operation == 'update':
                    code = store.update_client(arguments.code, data)['code']
                else:
                    store.save_plan(arguments.code, data)
                    code = arguments.code
        print(code)
        return 0
    except Exception:
        print('Private intake rejected. Check the local file and database without sending them to an AI.',
              file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
