import os
import tempfile
import unittest
from pathlib import Path

from services.knowledge import corpus_paths


class CorpusPathsTests(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in (corpus_paths.RAW_ARENA_ENV, corpus_paths.VALIDATED_ARENA_ENV)}
        for key in self._saved:
            os.environ.pop(key, None)

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_defaults_are_container_paths(self):
        # The host path /mnt/sovereign-ai is a decoy inside the container.
        self.assertEqual(corpus_paths.raw_arena_root(), Path("/mnt/sovereign-memory/raw/corpus/arena"))
        self.assertEqual(corpus_paths.validated_arena_root(), Path("/mnt/sovereign-memory/validated/corpus/arena-increments"))

    def test_environment_overrides(self):
        os.environ[corpus_paths.RAW_ARENA_ENV] = "/ailleurs/raw/corpus/arena"
        os.environ[corpus_paths.VALIDATED_ARENA_ENV] = "/ailleurs/validated/corpus/arena-increments"
        self.assertEqual(corpus_paths.raw_arena_root(), Path("/ailleurs/raw/corpus/arena"))
        self.assertEqual(corpus_paths.validated_arena_root(), Path("/ailleurs/validated/corpus/arena-increments"))

    def test_require_share_accepts_a_mounted_tree(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "raw" / "corpus" / "arena"
            (Path(temporary) / "raw").mkdir()
            self.assertEqual(corpus_paths.require_share(root), root)

    def test_require_share_refuses_an_unmounted_tree(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "absent" / "corpus" / "arena"
            with self.assertRaises(corpus_paths.ShareNotMounted):
                corpus_paths.require_share(root)


if __name__ == "__main__":
    unittest.main()
