import json
import unittest

from services.web import agent_tools as at


class FakeKnowledge:
    def search(self, query, *, query_embedding, limit):
        if query == "vide":
            return {"hits": []}
        return {"hits": [
            {"document_id": "upload:doc:000", "title": "Guide TCP", "provenance_id": "upload:doc", "summary": "TCP est fiable."},
        ][:limit]}

    def documents(self):
        return [{"provenance_id": "upload:doc", "title": "Guide TCP", "chunks": 3, "characters": 1200}]

    def chunks_for_provenance(self, provenance_id):
        if provenance_id != "upload:doc":
            return []
        return [{"document_id": "upload:doc:000", "title": "Guide TCP", "content": "Contenu du guide TCP."}]


class ExecuteToolTests(unittest.TestCase):
    def setUp(self):
        self.k = FakeKnowledge()

    def test_current_time(self):
        text, citations = at.execute_tool("current_time", "{}", knowledge=self.k)
        self.assertIn("heure du serveur", text)
        self.assertEqual(citations, [])

    def test_search_returns_hits_and_citations(self):
        text, citations = at.execute_tool("search_knowledge", {"query": "TCP"}, knowledge=self.k)
        self.assertIn("Guide TCP", text)
        self.assertEqual(citations[0]["provenance_id"], "upload:doc")

    def test_search_empty(self):
        text, citations = at.execute_tool("search_knowledge", {"query": "vide"}, knowledge=self.k)
        self.assertIn("Aucun extrait", text)
        self.assertEqual(citations, [])

    def test_search_rejects_short_query(self):
        with self.assertRaises(at.ToolError):
            at.execute_tool("search_knowledge", {"query": "x"}, knowledge=self.k)

    def test_search_accepts_json_string_arguments(self):
        text, _ = at.execute_tool("search_knowledge", json.dumps({"query": "TCP"}), knowledge=self.k)
        self.assertIn("Guide TCP", text)

    def test_list_documents(self):
        text, _ = at.execute_tool("list_documents", "{}", knowledge=self.k)
        self.assertIn("Guide TCP", text)

    def test_read_document(self):
        text, citations = at.execute_tool("read_document", {"provenance_id": "upload:doc"}, knowledge=self.k)
        self.assertIn("Contenu du guide TCP", text)
        self.assertEqual(citations[0]["provenance_id"], "upload:doc")

    def test_read_document_bad_provenance(self):
        with self.assertRaises(at.ToolError):
            at.execute_tool("read_document", {"provenance_id": "../etc/passwd"}, knowledge=self.k)

    def test_read_document_missing(self):
        with self.assertRaises(at.ToolError):
            at.execute_tool("read_document", {"provenance_id": "upload:absent"}, knowledge=self.k)

    def test_unknown_tool(self):
        with self.assertRaises(at.ToolError):
            at.execute_tool("run_shell", {"cmd": "rm -rf /"}, knowledge=self.k)

    def test_oversized_arguments_string(self):
        with self.assertRaises(at.ToolError):
            at.execute_tool("search_knowledge", "x" * (at.MAX_ARGUMENTS_BYTES + 1), knowledge=self.k)


class ToolLoopTests(unittest.TestCase):
    def setUp(self):
        self.k = FakeKnowledge()

    def _exec(self, name, arguments):
        return at.execute_tool(name, arguments, knowledge=self.k)

    def test_direct_answer_without_tools(self):
        def chat(messages, tools):
            return {"content": "Réponse directe.", "tool_calls": []}
        answer, citations = at.run_tool_loop(chat, [{"role": "user", "content": "salut"}], execute=self._exec)
        self.assertEqual(answer, "Réponse directe.")
        self.assertEqual(citations, [])

    def test_calls_tool_then_answers(self):
        calls = {"n": 0}
        tools_seen = []

        def chat(messages, tools):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"content": None, "tool_calls": [
                    {"id": "c1", "function": {"name": "search_knowledge", "arguments": json.dumps({"query": "TCP"})}},
                ]}
            # second call: the tool result must be present in the messages
            assert any(m.get("role") == "tool" for m in messages)
            return {"content": "TCP est fiable [1].", "tool_calls": []}

        answer, citations = at.run_tool_loop(
            chat, [{"role": "user", "content": "parle-moi de TCP"}],
            execute=self._exec, on_tool=lambda name, cid: tools_seen.append(name),
        )
        self.assertEqual(answer, "TCP est fiable [1].")
        self.assertEqual(citations[0]["provenance_id"], "upload:doc")
        self.assertEqual(tools_seen, ["search_knowledge"])

    def test_tool_error_is_fed_back_not_raised(self):
        calls = {"n": 0}

        def chat(messages, tools):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"content": None, "tool_calls": [
                    {"id": "c1", "function": {"name": "read_document", "arguments": json.dumps({"provenance_id": "bad"})}},
                ]}
            return {"content": "Je n'ai pas trouvé ce document.", "tool_calls": []}

        answer, _ = at.run_tool_loop(chat, [{"role": "user", "content": "lis bad"}], execute=self._exec)
        self.assertIn("pas trouvé", answer)

    def test_rounds_are_bounded(self):
        # Model always asks for a tool; the loop must stop and force a final answer.
        def chat(messages, tools):
            if not tools:  # final forced round
                return {"content": "Réponse finale forcée.", "tool_calls": []}
            return {"content": None, "tool_calls": [
                {"id": "c", "function": {"name": "current_time", "arguments": "{}"}},
            ]}

        answer, _ = at.run_tool_loop(chat, [{"role": "user", "content": "boucle"}], execute=self._exec, max_rounds=3)
        self.assertEqual(answer, "Réponse finale forcée.")


class DriveActionTests(unittest.TestCase):
    def setUp(self):
        self.k = FakeKnowledge()

    def _exec(self, name, arguments):
        return at.execute_tool(name, arguments, knowledge=self.k)

    def test_action_call_pauses_for_confirmation(self):
        def chat(work, tools):
            return {"content": None, "tool_calls": [
                {"id": "a1", "function": {"name": "run_python", "arguments": json.dumps({"code": "print(1)"})}}]}
        res = at.drive(chat, [{"role": "user", "content": "go"}], execute=self._exec, action_tools=at.ACTION_TOOL_NAMES)
        self.assertEqual(res["status"], "confirm")
        self.assertEqual(res["call"]["name"], "run_python")
        self.assertEqual(res["work"][-1]["role"], "assistant")  # tool result not appended yet

    def test_resume_after_action_reaches_final(self):
        calls = {"n": 0}

        def chat(work, tools):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"content": None, "tool_calls": [
                    {"id": "a1", "function": {"name": "run_python", "arguments": json.dumps({"code": "print(1)"})}}]}
            return {"content": "fini", "tool_calls": []}

        res = at.drive(chat, [{"role": "user", "content": "go"}], execute=self._exec, action_tools=at.ACTION_TOOL_NAMES)
        self.assertEqual(res["status"], "confirm")
        work = res["work"]
        work.append({"role": "tool", "tool_call_id": res["call"]["id"], "content": "OK"})
        res2 = at.drive(chat, work, execute=self._exec, action_tools=at.ACTION_TOOL_NAMES, citations=res["citations"])
        self.assertEqual((res2["status"], res2["answer"]), ("final", "fini"))

    def test_action_tool_ignored_when_not_enabled(self):
        seq = {"n": 0}

        def chat(work, tools):
            seq["n"] += 1
            if seq["n"] == 1:
                return {"content": None, "tool_calls": [
                    {"id": "a1", "function": {"name": "run_python", "arguments": "{}"}}]}
            return {"content": "répondu sans exécuter", "tool_calls": []}

        res = at.drive(chat, [{"role": "user", "content": "go"}], execute=self._exec)  # no action_tools
        self.assertEqual(res["status"], "final")  # run_python treated as unknown tool, error fed back


if __name__ == "__main__":
    unittest.main()
