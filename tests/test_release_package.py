import os
from pathlib import Path
import subprocess
import tarfile
from tempfile import TemporaryDirectory
import unittest

from scripts.package_release import package_source


class ReleasePackageTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / "tmp" / "source.tar.gz"
        self.output.parent.mkdir()
        for arguments in (
            ("init", "--quiet"),
            ("config", "user.name", "Release Test"),
            ("config", "user.email", "release@example.invalid"),
            ("config", "core.autocrlf", "true"),
        ):
            subprocess.run(["git", *arguments], cwd=self.root, check=True)
        self.write(".gitignore", "tmp/\n.env\n*.xlsx\n")
        self.write("frontend/src/old.ts", "export const value = 1;\n")
        self.write("scripts/deleted.py", "old = True\n")
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(
            ["git", "commit", "--quiet", "-m", "fixture"], cwd=self.root, check=True
        )

    def write(self, name: str, content: str) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode())

    def contents(self) -> dict[str, bytes]:
        with tarfile.open(self.output) as archive:
            contents = {}
            for entry in archive.getmembers():
                stream = archive.extractfile(entry) if entry.isfile() else None
                if stream is not None:
                    contents[entry.name] = stream.read()
            return contents

    def test_candidate_includes_new_files_deletions_and_git_normalization(self) -> None:
        self.write("frontend/src/old.ts", "export const value = 2;\r\n")
        self.write("frontend/src/新增 Hook.tsx", "export const added = true;\r\n")
        self.write("scripts/new.py", "added = True\r\n")
        self.write("tests/new_test.py", "assert True\n")
        self.write("frontend/public/new.svg", "<svg/>\r\n")
        self.write("frontend/.env.production", "SECRET=private\n")
        self.write(".env", "SECRET=private\n")
        self.write("orders.xlsx", "业务数据")
        self.write("notes.txt", "本地笔记")
        (self.root / "scripts/deleted.py").unlink()
        index = (self.root / ".git/index").read_bytes()
        tree = package_source(self.root, self.output)
        self.assertEqual(len(tree), 40)
        self.assertEqual((self.root / ".git/index").read_bytes(), index)
        contents = self.contents()
        self.assertEqual(contents["frontend/src/old.ts"], b"export const value = 2;\n")
        self.assertEqual(
            contents["frontend/src/新增 Hook.tsx"], b"export const added = true;\n"
        )
        self.assertEqual(contents["scripts/new.py"], b"added = True\n")
        self.assertEqual(contents["tests/new_test.py"], b"assert True\n")
        self.assertEqual(contents["frontend/public/new.svg"], b"<svg/>\n")
        for excluded in (
            "scripts/deleted.py",
            ".env",
            "frontend/.env.production",
            "orders.xlsx",
            "notes.txt",
            "tmp/source.tar.gz",
        ):
            self.assertNotIn(excluded, contents)

    def test_committed_package_ignores_working_changes_and_new_files(self) -> None:
        revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=self.root, text=True
        ).strip()
        self.write("frontend/src/old.ts", "modified = true\n")
        self.write("scripts/new.py", "new = True\n")
        package_source(self.root, self.output, revision=revision)
        contents = self.contents()
        self.assertEqual(contents["frontend/src/old.ts"], b"export const value = 1;\n")
        self.assertIn("scripts/deleted.py", contents)
        self.assertNotIn("scripts/new.py", contents)

    def test_failed_archive_preserves_actual_index(self) -> None:
        index = (self.root / ".git/index").read_bytes()
        with self.assertRaises(subprocess.CalledProcessError):
            package_source(self.root, self.root / "missing/source.tar.gz")
        self.assertEqual((self.root / ".git/index").read_bytes(), index)

    @unittest.skipIf(os.name == "nt", "Windows 不提供 POSIX 可执行位和符号链接")
    def test_executable_and_symlink_are_preserved(self) -> None:
        self.write("scripts/executable.py", "print('运行')\n")
        (self.root / "scripts/executable.py").chmod(0o755)
        (self.root / "scripts/link.py").symlink_to("executable.py")
        package_source(self.root, self.output)
        with tarfile.open(self.output) as archive:
            self.assertTrue(archive.getmember("scripts/executable.py").mode & 0o111)
            link = archive.getmember("scripts/link.py")
            self.assertTrue(link.issym())
            self.assertEqual(link.linkname, "executable.py")
