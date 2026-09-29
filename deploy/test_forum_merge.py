"""Checks the deployment's three-way merge without touching a server."""
import shutil
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from enable_forum import enable_forum
import ast
import io
import tarfile


ROOT = Path(__file__).resolve().parent.parent
DIFF3 = shutil.which("diff3") or "C:/Program Files/Git/usr/bin/diff3.exe"
SHARED = (
    "config/settings.py", "config/urls.py", "core/context_processors.py",
    "templates/base.html", "templates/partials/navigation_links.html",
)


class ForumMergeTests(unittest.TestCase):
    def test_windows_git_archives_merge_with_linux_server_files(self):
        archives = []
        for revision in ("337c194", "feature/forum"):
            data = subprocess.check_output([
                "git", "-c", "core.autocrlf=true", "archive", "--format=tar", revision, "--", *SHARED
            ], cwd=ROOT)
            with tarfile.open(fileobj=io.BytesIO(data)) as archive:
                archives.append({name: archive.extractfile(name).read() for name in SHARED})
        bash = shutil.which("bash") if os.name != "nt" else "C:/Program Files/Git/bin/bash.exe"
        for name in SHARED:
            with self.subTest(file=name), tempfile.TemporaryDirectory() as directory:
                baseline, new = archives[0][name], archives[1][name]
                self.assertIn(b"\r\n", baseline)
                self.assertIn(b"\r\n", new)
                Path(directory, "current").write_bytes(baseline.replace(b"\r\n", b"\n"))
                Path(directory, "baseline").write_bytes(baseline)
                Path(directory, "new").write_bytes(new)
                # Exact normalization and merge used by the Linux installer.
                result = subprocess.run([bash, "-c", "set -eu\nsed -i 's/\\r$//' baseline new\ndiff3 --merge --show-overlap -- current baseline new"], cwd=directory, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
                self.assertEqual(result.stdout, new.replace(b"\r\n", b"\n"))

    def merge(self, current, baseline, new):
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory, name) for name in ("current", "baseline", "new")]
            for path, text in zip(paths, (current, baseline, new)):
                path.write_bytes(text.replace("\r\n", "\n").encode("utf-8"))
            env = dict(os.environ)
            env["PATH"] = str(Path(DIFF3).parent) + os.pathsep + env.get("PATH", "")
            return subprocess.run([DIFF3, "--merge", "--show-overlap", "--", *map(str, paths)], capture_output=True, env=env)

    def versions(self, file):
        baseline = subprocess.check_output(["git", "show", f"337c194:{file}"], cwd=ROOT).decode("utf-8")
        new = (ROOT / file).read_text(encoding="utf-8")
        return baseline, new

    def test_pristine_and_already_installed_files(self):
        for file in SHARED:
            baseline, new = self.versions(file)
            for current in (baseline, new):
                with self.subTest(file=file, already_installed=current == new):
                    result = self.merge(current, baseline, new)
                    self.assertEqual(result.returncode, 0)
                    self.assertEqual(result.stdout.decode(), new)

    def test_server_settings_and_crlf_are_preserved(self):
        baseline, new = self.versions("config/settings.py")
        marker = '\n# Independent server configuration\nSERVER_LOCAL_VALUE = "keep-this-setting"\n'
        current = (baseline + marker).replace("\n", "\r\n")
        result = self.merge(current, baseline, new)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.decode(), new + marker)

    def test_independent_changes_in_every_shared_file(self):
        for file in SHARED:
            baseline, new = self.versions(file)
            marker = "\n# Server-only setting\n" if file.endswith(".py") else "\n<!-- Server-only customization -->\n"
            with self.subTest(file=file):
                result = self.merge(baseline + marker, baseline, new)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stdout.decode(), new + marker)

    def test_conflict_blocks_installation(self):
        result = self.merge("setting = 'server'\n", "setting = 'before'\n", "setting = 'new'\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"<<<<<<<", result.stdout)


class ForumSettingsTests(unittest.TestCase):
    def test_preserves_custom_settings_comments_and_app_order(self):
        source = '# Eigene Konfiguration\nSECRET_KEY = "test-only"\nINSTALLED_APPS = [\n    "custom.app", # behalten\n    "accounts",\n]\nEMAIL_HOST = "mail.example.test"\n'
        expected = source.replace('INSTALLED_APPS = [', 'INSTALLED_APPS = [\n    "forum",')
        self.assertEqual(enable_forum(source), expected)
        self.assertEqual(enable_forum(expected), expected)

    def test_single_line_lists_tuples_empty_lists_and_unicode_offsets(self):
        for literal in ('[]', '()', '["accounts"]', '("accounts",)', '["accounts", ]'):
            source = f'"Grüezi"; INSTALLED_APPS = {literal}\n'
            result = enable_forum(source)
            value = ast.parse(result).body[1].value
            self.assertEqual(list(ast.literal_eval(value)), ["forum", *ast.literal_eval(literal)])

    def test_existing_app_config_is_not_duplicated(self):
        source = 'INSTALLED_APPS = ["accounts", "forum.apps.ForumConfig"]\n'
        self.assertEqual(enable_forum(source), source)

    def test_dynamic_or_repeated_assignment_stops(self):
        for source in ('INSTALLED_APPS = get_apps()', 'INSTALLED_APPS = []\nINSTALLED_APPS += ["accounts"]', 'if True:\n    INSTALLED_APPS = []'):
            with self.assertRaises(ValueError):
                enable_forum(source)


if __name__ == "__main__":
    unittest.main()
