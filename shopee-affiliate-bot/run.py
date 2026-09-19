#!/usr/bin/env python3
"""主程式進入點。

用法（在這個資料夾底下開終端機/命令提示字元）：

    python run.py doctor          檢查環境有沒有裝好、設定對不對
    python run.py pick            只看這次會選到哪些商品
    python run.py run             完整執行：選品 → 做影片 → 發佈
    python run.py approve all     把待審核的影片發出去
    python run.py status          看最近的紀錄

第一次使用請先執行 doctor。
"""

import sys
from pathlib import Path

# 讓 Python 找得到 src/affiliate_bot，這樣使用者不用另外安裝套件。
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from affiliate_bot.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
