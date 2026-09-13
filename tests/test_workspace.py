import tempfile
import unittest
from pathlib import Path

from services.web import workspace


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name) / "workspace"
        self.root.mkdir()

    def test_writes_and_reads_back(self):
        written = workspace.write_file(self.root, "note.md", "bonjour")
        self.assertEqual((written["relative"], written["bytes"]), ("note.md", 7))
        self.assertEqual(workspace.read_file(self.root, "note.md"), "bonjour")
        self.assertEqual(workspace.read_bytes(self.root, "note.md"), b"bonjour")

    def test_allows_one_subdirectory(self):
        written = workspace.write_file(self.root, "notes/resume.md", "x")
        self.assertEqual(written["relative"], "notes/resume.md")
        self.assertTrue((self.root / "notes" / "resume.md").is_file())

    def test_refuses_traversal_and_absolute_paths(self):
        for bad in ["../escape.txt", "/etc/passwd", "notes/../../escape.txt", "a\\b.txt", "a/b/c.txt", "", "   "]:
            with self.subTest(bad=bad), self.assertRaises(workspace.WorkspaceError):
                workspace.write_file(self.root, bad, "x")

    def test_refuses_hidden_and_odd_names(self):
        for bad in [".ssh", ".", "..", "-x.txt"]:
            with self.subTest(bad=bad), self.assertRaises(workspace.WorkspaceError):
                workspace.write_file(self.root, bad, "x")

    def test_refuses_oversized_content(self):
        with self.assertRaises(workspace.WorkspaceError):
            workspace.write_file(self.root, "big.txt", "x" * (workspace.MAX_FILE_BYTES + 1))

    def test_lists_files(self):
        workspace.write_file(self.root, "a.txt", "1")
        workspace.write_file(self.root, "sub/b.txt", "22")
        names = {item["relative"] for item in workspace.list_files(self.root)}
        self.assertEqual(names, {"a.txt", "sub/b.txt"})

    def test_read_missing_file(self):
        with self.assertRaises(workspace.WorkspaceError):
            workspace.read_file(self.root, "absent.txt")


if __name__ == "__main__":
    unittest.main()
