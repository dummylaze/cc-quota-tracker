"""出圖腳本的假資料：只准是範例，不得帶真實帳號、email 或本機路徑。腳本的 Pillow 在渲染時才載入，所以這裡不需要它。"""
import importlib.util
import re
import unittest
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tools" / "render_screenshots.py"


def load():
    spec = importlib.util.spec_from_file_location("render_screenshots", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def strings(value):
    """巢狀資料裡所有的字串。"""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from strings(item)


class ScreenshotDataTest(unittest.TestCase):
    def test_fake_board_has_only_the_example_account_label(self):
        board = load().fake_board()
        self.assertEqual([card.account_key for card in board.cards], ["claude:work"])

    def test_fake_board_carries_no_email_or_local_path(self):
        board = load().fake_board()
        for value in strings(asdict(board)):
            self.assertNotIn("@", value)
            self.assertIsNone(re.search(r"[A-Za-z]:[\\/]|/Users/|/home/", value), value)

    def test_script_reads_no_real_file_or_settings(self):
        source = SCRIPT.read_text(encoding="utf-8")
        for forbidden in ("claude.json", "credentials", "settings.json", "Core(", "resolve_paths", "open("):
            self.assertNotIn(forbidden, source)

    def test_script_says_pillow_is_not_a_project_dependency(self):
        self.assertIn("只有這支腳本需要 Pillow", load().__doc__)

    def test_the_example_shows_a_near_limit_window(self):
        limits = {lim.kind: lim for lim in load().fake_board().cards[0].limits}
        self.assertGreaterEqual(limits["weekly_all"].percent, 85)
        self.assertLess(limits["session"].percent, 60)


if __name__ == "__main__":
    unittest.main()
