"""兩版 README 與 LICENSE：連結點下去對得到、兩版的章節與圖片逐項對應、授權與聲明都在。
只讀 repo 裡的文件，不碰網路；GitHub 產生錨點的規則（slug）在這裡實作一份，用來驗證錨點連結。"""
import re
import unicodedata
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = {"en": ROOT / "README.md", "zh": ROOT / "README.zh-TW.md"}
IMAGES = ROOT / "docs" / "images"
LAYOUT_SHOTS = ("cards", "table", "ring")

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)")
_IMAGE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)|<img\b[^>]*\bsrc=\"([^\"]+)\"")


def slug(heading):
    """GitHub 的標題錨點：小寫、只留字母數字底線連字號與空白、空白換成連字號。"""
    kept = "".join(ch for ch in heading.lower()
                   if unicodedata.category(ch)[0] in "LMN" or unicodedata.category(ch) == "Pc" or ch in "- ")
    return kept.replace(" ", "-")


def read(path):
    return path.read_text(encoding="utf-8")


def headings(markdown):
    """(層級, 標題文字)，略過程式碼區塊裡的 #。"""
    result, in_code = [], False
    for line in markdown.splitlines():
        if line.startswith("```"):
            in_code = not in_code
        elif not in_code and (m := _HEADING.match(line)):
            result.append((len(m.group(1)), m.group(2)))
    return result


def anchors(markdown):
    seen, result = {}, set()
    for _, title in headings(markdown):
        base = slug(title)
        n = seen.get(base, 0)
        seen[base] = n + 1
        result.add(base if n == 0 else f"{base}-{n}")
    return result


def prose(markdown):
    """去掉程式碼區塊與行內程式碼：裡面的 [..](..) 不是連結。"""
    return re.sub(r"`[^`\n]*`", "", re.sub(r"```.*?```", "", markdown, flags=re.S))


class ReadmeLinksTest(unittest.TestCase):
    def test_in_page_anchors_resolve(self):
        for lang, path in README.items():
            text = read(path)
            known = anchors(text)
            targets = [t for t in _LINK.findall(prose(text)) if t.startswith("#")]
            self.assertGreaterEqual(len(targets), 5, path.name)  # 抓不到連結時不能靜默通過
            for target in targets:
                self.assertIn(target[1:], known, f"{path.name}: {target}")

    def test_relative_links_and_images_exist(self):
        for path in README.values():
            text = read(path)
            targets = [t for t in _LINK.findall(prose(text)) if not t.startswith(("#", "http"))]
            targets += [a or b for a, b in _IMAGE.findall(text)]
            for target in targets:
                self.assertTrue((ROOT / target.split("#")[0]).exists(), f"{path.name}: {target}")

    def test_both_versions_have_the_same_outline(self):
        levels = {lang: [level for level, _ in headings(read(path))] for lang, path in README.items()}
        self.assertEqual(levels["en"], levels["zh"])


class ScreenshotsTest(unittest.TestCase):
    def test_each_readme_shows_its_own_language_screenshots(self):
        for lang, path in README.items():
            shown = [a or b for a, b in _IMAGE.findall(read(path))]
            self.assertEqual(sorted(Path(s).name for s in shown),
                             sorted(f"{shot}-{lang}.png" for shot in LAYOUT_SHOTS), path.name)

    def test_the_six_images_are_committed_png_files(self):
        for lang in README:
            for shot in LAYOUT_SHOTS:
                path = IMAGES / f"{shot}-{lang}.png"
                self.assertTrue(path.exists(), path.name)
                self.assertEqual(path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n", path.name)

    def test_images_have_alt_text(self):
        for path in README.values():
            text = read(path)
            alts = re.findall(r"!\[([^\]]*)\]\(", text) + re.findall(r"<img\b[^>]*\balt=\"([^\"]*)\"", text)
            self.assertEqual(len(alts), len(_IMAGE.findall(text)), path.name)
            for alt in alts:
                self.assertTrue(alt.strip(), path.name)


class ReadmeOpeningTest(unittest.TestCase):
    def test_disclaimer_line_is_right_below_the_intro_and_links_to_the_section(self):
        en, zh = read(README["en"]), read(README["zh"])
        self.assertIn("Unofficial; not affiliated with or endorsed by Anthropic. Use at your own risk — "
                      "see [Disclaimer](#disclaimer).", en)
        self.assertIn("非官方工具，與 Anthropic 無關。使用風險自負，見[免責聲明](#免責聲明)。", zh)
        self.assertLess(en.index("Unofficial;"), en.index("## Requirements"))
        self.assertLess(zh.index("非官方工具"), zh.index("## 環境需求"))

    def test_opening_states_deploy_from_source_and_the_old_requirements_line_is_gone(self):
        for path, requirements in ((README["en"], "## Requirements"), (README["zh"], "## 環境需求")):
            text = read(path)
            head = text[:text.index(requirements)]
            self.assertIn("3.9", head, path.name)
            self.assertNotIn("not packaged as an exe", text)
            self.assertNotIn("不打包成 exe", text)

    def test_disclaimer_and_license_are_the_last_two_sections_in_that_order(self):
        self.assertEqual([t for _, t in headings(read(README["en"]))][-2:], ["Disclaimer", "License"])
        self.assertEqual([t for _, t in headings(read(README["zh"]))][-2:], ["免責聲明", "授權"])

    def test_license_sections_link_to_the_license_file(self):
        for path in README.values():
            text = read(path)
            tail = text[text.rindex("\n## "):]
            self.assertIn("MIT", tail)
            self.assertIn("(LICENSE)", tail)

    def test_known_limitations_sit_between_requirements_and_setup(self):
        for path in README.values():
            titles = [t for level, t in headings(read(path)) if level == 2]
            i = next(n for n, t in enumerate(titles) if t.startswith(("Intended setup", "適用情境")))
            self.assertTrue(titles[i - 1].startswith(("Requirements", "環境需求")), path.name)
            self.assertTrue(titles[i + 1].startswith(("Setup", "部署三步")), path.name)

    def test_the_limitation_about_the_cache_field_links_to_for_hosts(self):
        en, zh = read(README["en"]), read(README["zh"])
        self.assertIn("(#for-hosts-what-the-tool-depends-on)", en[en.index("Known limitations"):en.index("## Setup")])
        zh_part = zh[zh.index("已知限制"):zh.index("## 部署三步")]
        self.assertIn("(#給架設者本工具依賴什麼)", zh_part)

    def test_setup_gives_the_clone_command_and_the_command_list_mentions_help(self):
        for path in README.values():
            text = read(path)
            self.assertIn("git clone https://github.com/dummylaze/cc-quota-tracker.git", text)
            self.assertIn("python -m cc_quota_tracker --help", text)


class LicenseTest(unittest.TestCase):
    def test_license_is_mit_with_the_agreed_copyright_line(self):
        text = read(ROOT / "LICENSE")
        self.assertTrue(text.startswith("MIT License"))
        self.assertIn("Copyright (c) 2026 dummylaze", text)
        self.assertIn('THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND', text)


if __name__ == "__main__":
    unittest.main()
