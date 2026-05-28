"""bcrypt 密码哈希工具:python -m web.tools.hashpw <password>"""

from __future__ import annotations

import sys

from web.auth import hash_password


def main() -> None:
    if len(sys.argv) < 2:
        print("用法: python -m web.tools.hashpw <password>")
        sys.exit(1)
    print(hash_password(sys.argv[1]))


if __name__ == "__main__":
    main()
