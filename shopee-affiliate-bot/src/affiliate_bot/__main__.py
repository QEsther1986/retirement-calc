"""讓 `python -m affiliate_bot` 可以直接執行。"""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
