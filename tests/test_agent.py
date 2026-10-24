import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from io import BytesIO
from pypdf import PdfWriter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.sample = agent.ROOT / "data" / "sample.pdf"
        (self.folder / "sample.pdf").write_bytes(self.sample.read_bytes())

    def test_read_and_page_range(self):
        result = agent.read_pdf(self.folder, "sample.pdf", 2, 2)
        self.assertEqual(result["pages"][0]["page"], 2)
        self.assertIn("Function", result["pages"][0]["text"])
        with self.assertRaises(ValueError):
            agent.read_pdf(self.folder, "sample.pdf", 0, 2)

    def test_missing_empty_and_bad_arguments(self):
        writer = PdfWriter()
        writer.add_blank_page(width=300, height=400)
        writer.write(self.folder / "blank.pdf")
        for name, params in [
            ("read_pdf", '{"filename":"missing.pdf"}'),
            ("read_pdf", '{"filename":"blank.pdf"}'),
            ("read_pdf", '{"filename":"sample.pdf","start_page":true}'),
            ("read_pdf", 'not json'),
            ("unknown", '{}'),
        ]:
            with self.subTest(params=params):
                result = agent.execute_tool(name, params, self.folder, self.folder)
                self.assertFalse(result["ok"])

    def test_save_and_no_overwrite(self):
        result = agent.save_notes(self.folder, "notes.md", "# 笔记\n来源：第 1 页")
        self.assertTrue(result["ok"])
        with self.assertRaises(FileExistsError):
            agent.save_notes(self.folder, "notes.md", "replacement")
        self.assertIn("来源", (self.folder / "notes.md").read_text(encoding="utf-8"))

    def test_path_traversal(self):
        for name in ["../outside.md", "C:\\outside.md", "sub/notes.md", "notes.txt"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                agent.save_notes(self.folder, name, "content")

    def test_tool_loop(self):
        responses = iter([
            {"tool_calls": [{"id": "read1", "type": "function", "function": {
                "name": "read_pdf", "arguments": '{"filename":"sample.pdf"}'}}]},
            {"tool_calls": [{"id": "save1", "type": "function", "function": {
                "name": "save_notes", "arguments": json.dumps({
                    "filename": "summary.md", "content": "# Summary\nSource: sample.pdf, page 1"})}}]},
            {"content": "已保存笔记。"}
        ])
        def fake_model(messages, config, key):
            if messages[-1]["role"] == "tool":
                self.assertTrue(json.loads(messages[-1]["content"])["ok"])
            return next(responses)
        result = agent.run_agent("总结并保存", {}, "unused", self.folder,
                                 self.folder, model_call=fake_model)
        self.assertIn("已保存", result)
        self.assertTrue((self.folder / "summary.md").exists())

    def test_loop_limit(self):
        def repeat(messages, config, key):
            return {"tool_calls": [{"id": "repeat", "type": "function", "function": {
                "name": "read_pdf", "arguments": '{"filename":"missing.pdf"}'}}]}
        history = []
        with self.assertRaisesRegex(RuntimeError, "12"):
            agent.run_agent("任务", {}, "unused", self.folder, self.folder,
                            model_call=repeat, history=history)
        self.assertEqual(history, [])

    def test_followup_keeps_pdf_and_save_request(self):
        history = []
        responses = iter([
            {"tool_calls": [{"id": "read1", "type": "function", "function": {
                "name": "read_pdf", "arguments": '{"filename":"sample.pdf"}'}}]},
            {"content": "这是提纲，需要我保存为 demo-notes.md 吗？"}
        ])
        agent.run_agent("读取 sample.pdf 并保存为 demo-notes.md", {}, "unused",
                        self.folder, self.folder, model_call=lambda *args: next(responses),
                        history=history)
        self.assertEqual(history[-1]["role"], "assistant")
        followup = iter([
            {"tool_calls": [{"id": "save1", "type": "function", "function": {
                "name": "save_notes", "arguments": json.dumps({"filename": "demo-notes.md",
                    "content": "# Notes\nSource: sample.pdf, page 1"})}}]},
            {"content": "已保存。"}
        ])
        def resume(messages, config, key):
            self.assertIn("demo-notes.md", messages[1]["content"])
            self.assertTrue(any(m["role"] == "tool" and
                                "pages" in json.loads(m["content"]) for m in messages))
            self.assertTrue(any(m["role"] == "assistant" and
                                "需要我保存" in (m.get("content") or "") for m in messages))
            return next(followup)
        result = agent.run_agent("需要", {}, "unused", self.folder, self.folder,
                                 model_call=resume, history=history)
        self.assertEqual(result, "已保存。")
        self.assertTrue((self.folder / "demo-notes.md").exists())

    def test_deepseek_request(self):
        response = BytesIO(json.dumps({"choices": [{"message": {
            "role": "assistant", "content": "ok"}, "finish_reason": "stop"}]}).encode())
        with patch("agent.request.urlopen", return_value=response) as mocked:
            result = agent.call_model([], {"base_url": "https://api.deepseek.com",
                                          "model": "deepseek-flash"}, "test-only")
        req = mocked.call_args.args[0]
        self.assertEqual(req.full_url, "https://api.deepseek.com/chat/completions")
        body = json.loads(req.data)
        self.assertEqual(body["thinking"], {"type": "disabled"})
        self.assertEqual(len(body["tools"]), 2)
        self.assertEqual(result["content"], "ok")

    def test_key_environment_precedence(self):
        with patch.dict("agent.os.environ", {"LLM_API_KEY": " test-only "}), \
                patch("agent.key_dialog") as dialog:
            self.assertEqual(agent.read_api_key(True), "test-only")
            dialog.assert_not_called()

    def test_key_dialog_and_cancel(self):
        for value in [" test-only ", None, "   "]:
            with self.subTest(value=value), \
                    patch.dict("agent.os.environ", {}, clear=True), \
                    patch("agent.key_dialog", return_value=value):
                if value and value.strip():
                    self.assertEqual(agent.read_api_key(True), "test-only")
                else:
                    with self.assertRaises(ValueError):
                        agent.read_api_key(True)

    def test_key_terminal_input(self):
        with patch.dict("agent.os.environ", {}, clear=True), \
                patch("agent.getpass.getpass", return_value=" test-only "):
            self.assertEqual(agent.read_api_key(), "test-only")


if __name__ == "__main__":
    unittest.main()
