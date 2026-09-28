import sys
from datetime import datetime, timezone
from pathlib import Path

from .core import Core
from .render_text import render


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args != ["list"]:
        print("用法：python -m cc_quota_tracker list", file=sys.stderr)
        return 2
    core = Core(Path.home(), lambda: datetime.now(timezone.utc))
    print(render(core.poll()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
