"""``python -m fulltext_fetcher`` 统一入口。

轻量首参分发:首个位置参数为 ``scholar`` 时,把其余参数转交谷歌学术子系统
(``fulltext_fetcher.scholar.cli.main``)并返回其退出码;否则原样走既有开放获取(OA)
主流程(``fulltext_fetcher.cli.main``)。既有用法逐字不变:

  - ``python -m fulltext_fetcher "10.xxx" --email you@uni.edu``   (OA 主流程)
  - ``python -m fulltext_fetcher scholar "标题/DOI" [选项]``       (Scholar 子命令,本次新增)
  - ``python -m fulltext_fetcher.scholar ...``                    (Scholar 独立入口,不受影响)
"""
from __future__ import annotations

import sys
from typing import List, Optional


def main(argv: Optional[List[str]] = None) -> int:
    args = list(sys.argv[1:]) if argv is None else list(argv)
    if args and args[0] == "scholar":
        # 子命令:仅把 'scholar' 之后的参数转交子系统;不打乱父 parser。
        from .scholar.cli import main as scholar_main
        return scholar_main(args[1:])
    # 非子命令:原样走既有 OA 主流程(argv 保持原值以逐字复现旧行为)。
    from .cli import main as oa_main
    return oa_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
