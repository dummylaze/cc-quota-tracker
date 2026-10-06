"""打包與發佈（ADR-0012）：發佈前的兩道檢查（tag 與版本一致、建好的命令列 exe 回報同一個版本）、建置相依鎖了 hash、
zip 的結構，以及發佈 workflow 的順序——任何一步失敗就不發佈。workflow 本身只能在 GitHub 上跑，這裡檢查它的檔案結構。"""
import hashlib
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from cc_quota_tracker import __version__
from cc_quota_tracker.autostart import GUI_EXE

ROOT = Path(__file__).resolve().parent.parent
PACKAGING = ROOT / "packaging"
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


def run_script(name, *args):
    return subprocess.run([sys.executable, str(PACKAGING / name), *args], capture_output=True, text=True,
                          cwd=str(ROOT))


def run_check(*args):
    return run_script("release_checks.py", *args)


class TagCheckTest(unittest.TestCase):
    def test_tag_that_is_v_plus_the_version_passes_and_prints_the_version(self):
        result = run_check("tag", f"v{__version__}")
        self.assertEqual((result.returncode, result.stdout.strip()), (0, __version__))  # workflow 拿輸出當版本號

    def test_a_different_version_fails_and_names_both(self):
        result = run_check("tag", "v999.0.0")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("v999.0.0", result.stderr)
        self.assertIn(__version__, result.stderr)

    def test_a_tag_without_the_v_prefix_or_with_a_suffix_fails(self):
        for tag in (__version__, f"v{__version__}-rc1", f"v{__version__}.1", "", "main"):
            with self.subTest(tag=tag):
                self.assertNotEqual(run_check("tag", tag).returncode, 0)

    def test_missing_arguments_are_a_usage_error(self):
        for args in ((), ("tag",), ("smoke",), ("nope", "x")):
            with self.subTest(args=args):
                self.assertEqual(run_check(*args).returncode, 2)


class SmokeCheckTest(unittest.TestCase):
    """建好的命令列 exe 要回報 __version__；這裡用原始碼版的同一條命令代替 exe。"""

    def test_a_command_that_prints_the_version_passes(self):
        result = run_check("smoke", sys.executable, "-m", "cc_quota_tracker", "--version")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_command_that_prints_another_version_fails(self):
        result = run_check("smoke", sys.executable, "-c", "print('cc-quota-tracker 0.0.1')")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(__version__, result.stderr)

    def test_output_with_anything_besides_the_version_line_fails(self):
        for printed in (f"cc-quota-tracker {__version__} extra", f"x cc-quota-tracker {__version__}",
                        f"cc-quota-tracker {__version__}0"):
            with self.subTest(printed=printed):
                self.assertNotEqual(run_check("smoke", sys.executable, "-c", f"print({printed!r})").returncode, 0)

    def test_a_command_that_fails_fails_even_if_it_printed_the_version(self):
        code = f"import sys; print('cc-quota-tracker {__version__}'); sys.exit(3)"
        self.assertNotEqual(run_check("smoke", sys.executable, "-c", code).returncode, 0)

    def test_a_command_that_cannot_start_fails(self):
        self.assertNotEqual(run_check("smoke", str(ROOT / "no-such-file.exe"), "--version").returncode, 0)


class BuildRequirementsTest(unittest.TestCase):
    def entries(self):
        text = (PACKAGING / "requirements-build.txt").read_text(encoding="utf-8")
        body = "\n".join(line for line in text.replace("\\\n", " ").splitlines() if not line.startswith("#"))
        return [line.split() for line in body.splitlines() if line.strip()]

    def test_every_package_is_pinned_exactly_and_carries_hashes(self):
        entries = self.entries()
        self.assertGreaterEqual(len(entries), 5)
        for entry in entries:
            with self.subTest(package=entry[0]):
                self.assertRegex(entry[0], r"^[A-Za-z0-9._-]+==[0-9][A-Za-z0-9.]*$")
                hashes = [part for part in entry[1:] if part.startswith("--hash=")]
                self.assertTrue(hashes)
                for h in hashes:
                    self.assertRegex(h, r"^--hash=sha256:[0-9a-f]{64}$")

    def test_pyinstaller_is_listed_here_and_nowhere_else(self):
        self.assertIn("pyinstaller", [e[0].split("==")[0] for e in self.entries()])
        self.assertEqual([p.name for p in ROOT.glob("requirements*.txt")], [])  # 執行期與測試不依賴任何 pip 套件（ADR-0004）


class SpecTest(unittest.TestCase):
    def test_two_executables_share_one_folder_and_only_the_window_one_has_no_console(self):
        spec = (PACKAGING / "cc-quota-tracker.spec").read_text(encoding="utf-8")
        self.assertIn('executable(gui, "cc-quota-tracker", console=False)', spec)
        self.assertIn('executable(cli, "cc-quota-tracker-cli", console=True)', spec)
        self.assertEqual(spec.count("COLLECT("), 1)  # 一個 COLLECT：兩個 exe 在同一個資料夾
        self.assertIn('name="cc-quota-tracker")', spec.split("COLLECT(", 1)[1])

    def test_the_window_exe_name_matches_what_autostart_registers(self):
        self.assertEqual(GUI_EXE, "cc-quota-tracker.exe")

    def test_only_the_window_exe_opens_the_window_when_given_no_arguments(self):
        gui = (PACKAGING / "gui_entry.py").read_text(encoding="utf-8")
        cli = (PACKAGING / "cli_entry.py").read_text(encoding="utf-8")
        self.assertIn('main(sys.argv[1:] or ["gui"])', gui)
        self.assertIn("main()", cli)
        self.assertNotIn('"gui"', cli)


class PackageReleaseTest(unittest.TestCase):
    def test_zip_unpacks_to_one_folder_and_the_sha256_file_matches_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            folder = tmp / "dist" / "cc-quota-tracker"
            (folder / "_internal").mkdir(parents=True)
            for name in ("cc-quota-tracker.exe", "cc-quota-tracker-cli.exe", "_internal/base_library.zip"):
                (folder / name).write_bytes(b"x")
            (tmp / "dist" / "leftover.txt").write_bytes(b"x")  # 與資料夾同層的東西不能被打進 zip
            result = run_script("package_release.py", str(folder), "1.2.3", str(tmp / "out"))
            self.assertEqual(result.returncode, 0, result.stderr)
            archive = tmp / "out" / "cc-quota-tracker-1.2.3-win64.zip"
            with zipfile.ZipFile(archive) as z:
                names = z.namelist()
            for expected in ("cc-quota-tracker.exe", "cc-quota-tracker-cli.exe", "_internal/base_library.zip"):
                self.assertIn(f"cc-quota-tracker/{expected}", names)
            self.assertTrue(all(n.startswith("cc-quota-tracker/") for n in names), names)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            self.assertEqual((tmp / "out" / f"{archive.name}.sha256").read_bytes(),  # 位元組：換行必須是 \n，不是 \r\n
                             f"{digest}  {archive.name}\n".encode())

    def test_a_folder_missing_either_exe_is_not_packaged(self):
        for missing in ("cc-quota-tracker.exe", "cc-quota-tracker-cli.exe"):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp) / "cc-quota-tracker"
                folder.mkdir()
                for name in {"cc-quota-tracker.exe", "cc-quota-tracker-cli.exe"} - {missing}:
                    (folder / name).write_bytes(b"x")
                result = run_script("package_release.py", str(folder), "1.2.3", str(Path(tmp) / "out"))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(missing, result.stderr)
                self.assertEqual(list((Path(tmp) / "out").glob("*")), [])

    def test_wrong_arguments_are_a_usage_error(self):
        self.assertEqual(run_script("package_release.py").returncode, 2)


class WorkflowTest(unittest.TestCase):
    """發佈 workflow 的結構。步驟順序就是失敗時擋下發佈的機制：發佈是最後一步，前面任何一步失敗都到不了它。"""

    def setUp(self):
        self.text = WORKFLOW.read_text(encoding="utf-8")

    def position(self, needle):
        self.assertEqual(self.text.count(needle), 1, needle)
        return self.text.index(needle)

    def test_runs_only_for_version_tags_on_a_windows_runner_with_python_3_12(self):
        self.assertRegex(self.text, r"(?m)^on:\n  push:\n    tags:\n      - 'v\*'\n")
        self.assertNotIn("pull_request", self.text)
        self.assertNotIn("branches", self.text)
        self.assertIn("runs-on: windows-latest", self.text)
        self.assertIn("python-version: '3.12'", self.text)

    def test_steps_run_in_the_agreed_order_and_publishing_is_last(self):
        order = ["python -m unittest", "release_checks.py tag", "pip install --require-hashes",
                 "PyInstaller packaging/cc-quota-tracker.spec", "release_checks.py smoke", "package_release.py",
                 "gh release create"]
        positions = [self.position(step) for step in order]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(len(re.findall(r"(?m)^  \S+:\n    runs-on:", self.text)), 1)  # 只有一個 job，沒有平行的發佈路徑

    def test_the_test_step_runs_the_whole_suite_and_the_smoke_test_targets_the_cli_exe(self):
        self.assertRegex(self.text, r"(?m)^        run: python -m unittest$")  # 不加模組名：跑完整測試
        self.assertRegex(self.text, r"(?m)^        run: python packaging/release_checks\.py smoke "
                                    r"dist/cc-quota-tracker/cc-quota-tracker-cli\.exe --version$")

    def test_no_step_swallows_a_failure(self):
        for needle in ("continue-on-error", "|| true", "if: always()", "if: failure()"):
            self.assertNotIn(needle, self.text)

    def test_actions_are_pinned_to_a_commit_and_steps_run_in_bash(self):
        uses = re.findall(r"uses: (\S+)", self.text)
        self.assertTrue(uses)
        for use in uses:
            self.assertRegex(use, r"^[\w-]+/[\w-]+@[0-9a-f]{40}$", use)
        self.assertIn("shell: bash", self.text)  # bash -e：多行的步驟中途失敗會中止；pwsh 對原生指令的失敗不會

    def test_the_tag_name_reaches_scripts_through_the_environment_not_the_command_text(self):
        for line in self.text.splitlines():
            if line.strip().startswith(("run:", "version=", "gh ")):
                self.assertNotIn("${{", line)  # tag 名稱可以是任意字串，直接內插進指令會被當成程式碼

    def test_the_zip_is_named_after_the_version_and_ships_with_its_sha256(self):
        self.assertIn("cc-quota-tracker-${VERSION}-win64.zip", self.text)
        self.assertIn('"$zip" "$zip.sha256"', self.text)


if __name__ == "__main__":
    unittest.main()
