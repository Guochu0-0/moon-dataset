"""让 `python -m moondata` 与装好的 `moondata` 命令等价。"""

from moondata.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
