"""發佈 workflow 在建置前後各跑一道檢查，任何一道不過就以非 0 結束，後面的步驟（含發佈）不會執行。

    python packaging/release_checks.py tag <tag>              tag 必須是 v 加上 __version__；通過時印出版本號
    python packaging/release_checks.py smoke <命令> [參數…]  執行建好的命令列 exe，結束代碼 0、輸出是 cc-quota-tracker <版本>

版本號只在這裡與 __version__ 比對，workflow 不自己比。"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cc_quota_tracker import __version__  # noqa: E402


def check_tag(tag: str) -> int:
    if tag != f"v{__version__}":
        print(f"tag {tag!r} 與套件版本不符：__version__ 是 {__version__}，tag 必須是 v{__version__}", file=sys.stderr)
        return 1
    print(__version__)
    return 0


def smoke(command: list) -> int:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"沒能執行 {command[0]}：{e}", file=sys.stderr)
        return 1
    expected = f"cc-quota-tracker {__version__}"
    if result.returncode != 0 or result.stdout.strip() != expected:
        print(f"煙霧測試失敗：結束代碼 {result.returncode}，輸出 {result.stdout.strip()!r}，預期 {expected!r}"
              f"\n{result.stderr}", file=sys.stderr)
        return 1
    print(result.stdout.strip())
    return 0


if __name__ == "__main__":
    action, rest = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else (None, [])
    if action == "tag" and len(rest) == 1:
        sys.exit(check_tag(rest[0]))
    if action == "smoke" and rest:
        sys.exit(smoke(rest))
    print(__doc__, file=sys.stderr)
    sys.exit(2)
