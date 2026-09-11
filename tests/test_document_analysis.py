import unittest

from services.knowledge import document_analysis as da


class FakeRuntime:
    def __init__(self) -> None:
        self.calls = []

    def generate(self, messages):
        self.calls.append(messages)
        system = messages[0]["content"]
        if system == da.REDUCE_SYSTEM:
            return "SYNTHESE FINALE"
        return "point " + messages[1]["content"][:6]


class DocumentAnalysisTests(unittest.TestCase):
    def test_map_reduce_over_chunks(self) -> None:
        chunks = [{"content": f"contenu {i}"} for i in range(3)]
        runtime = FakeRuntime()
        progress = []
        result = da.analyze(runtime.generate, chunks, on_progress=lambda done, total: progress.append((done, total)))
        self.assertEqual(result["analysis"], "SYNTHESE FINALE")
        self.assertEqual(result["analyzed_chunks"], 3)
        self.assertEqual(result["total_chunks"], 3)
        self.assertFalse(result["truncated"])
        self.assertEqual(progress, [(1, 3), (2, 3), (3, 3)])
        # 3 map calls + 1 reduce call
        self.assertEqual(len(runtime.calls), 4)

    def test_caps_the_number_of_chunks(self) -> None:
        chunks = [{"content": f"c{i}"} for i in range(da.MAX_ANALYZE_CHUNKS + 10)]
        result = da.analyze(FakeRuntime().generate, chunks)
        self.assertEqual(result["analyzed_chunks"], da.MAX_ANALYZE_CHUNKS)
        self.assertTrue(result["truncated"])

    def test_skips_empty_chunks(self) -> None:
        chunks = [{"content": "   "}, {"content": "réel"}]
        result = da.analyze(FakeRuntime().generate, chunks)
        self.assertEqual(result["analyzed_chunks"], 1)

    def test_refuses_no_chunks(self) -> None:
        with self.assertRaises(ValueError):
            da.analyze(FakeRuntime().generate, [])


if __name__ == "__main__":
    unittest.main()
