"""备用 Cron 入口:`python -m app.tick`

如果 Railway 的 Cron 容器里没有 curl(取决于构建方式),就把 Cron Job 的
命令从 curl 改成 `python -m app.tick`,效果相同。
"""

from .cron import fire_due_timers
from .db import init_db


def main() -> None:
    init_db()
    fired = fire_due_timers()
    print(f"fired {fired} wakeups")


if __name__ == "__main__":
    main()
