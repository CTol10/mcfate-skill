#!/usr/bin/env python3
"""麦门食运局 McFate 命令行入口。

只做三件事：定位内核包路径、修正 Windows 控制台编码、把参数交给 cli.main。
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

try:  # Windows 控制台默认 GBK，会导致中文 JSON 输出乱码
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):  # pragma: no cover - 非交互环境
    pass

from mcfate_core.cli import main  # noqa: E402  (需在 sys.path 调整之后导入)

if __name__ == "__main__":
    raise SystemExit(main())
