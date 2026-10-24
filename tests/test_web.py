from http.client import HTTPConnection
import json
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent
import web_app


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        (root / "data").mkdir()
        shutil.copy(agent.ROOT / "data/sample.pdf", root / "data/sample.pdf")
        shutil.copytree(agent.ROOT / "web", root / "web")
        self.calls = 0
        def model(messages, config, key):
            self.calls += 1
            if messages[-1]["role"] == "user":
                return {"tool_calls": [{"id": "read", "type": "function", "function": {
                    "name": "read_pdf", "arguments": '{"filename":"sample.pdf"}'}}]}
            if messages[-1].get("tool_call_id") == "read":
                return {"tool_calls": [{"id": "save", "type": "function", "function": {
                    "name": "save_notes", "arguments": json.dumps({"filename": "web-notes.md",
                        "content": "# 测试笔记\n来源：sample.pdf，第 1 页。"})}}]}
            return {"content": "笔记已保存。"}
        self.server = web_app.make_server(0, root, model)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.host = f"127.0.0.1:{self.server.server_port}"
        self.cookie = ""
        status, headers, body = self.request("GET", "/api/state")
        self.assertEqual(status, 200)
        self.cookie = headers["Set-Cookie"].split(";")[0]

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, method, path, body=None, headers=None):
        client = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        hdr = {"Host": self.host, "Cookie": self.cookie}
        if method == "POST":
            hdr["Origin"] = "http://" + self.host
        if isinstance(body, dict):
            body = json.dumps(body).encode()
            hdr["Content-Type"] = "application/json"
        hdr.update(headers or {})
        client.request(method, path, body, hdr)
        response = client.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        client.close()
        return result

    def test_static_state_and_no_config_exposure(self):
        status, headers, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        status, _, body = self.request("GET", "/api/state")
        data = json.loads(body)
        self.assertEqual(data["files"][0]["pages"], 2)
        self.assertNotIn("api_key", data["config"])
        self.assertEqual(self.request("GET", "/config.json")[0], 404)
        self.assertEqual(self.request("GET", "/../agent.py")[0], 404)

    def test_upload_validation_and_no_overwrite(self):
        pdf = (agent.ROOT / "data/sample.pdf").read_bytes()
        self.assertEqual(self.request("POST", "/api/upload", pdf, {"X-Filename": "new.pdf"})[0], 200)
        self.assertEqual(self.request("POST", "/api/upload", pdf, {"X-Filename": "new.pdf"})[0], 409)
        self.assertEqual(self.request("POST", "/api/upload", b"not-pdf", {"X-Filename": "bad.pdf"})[0], 400)
        self.assertEqual(self.request("POST", "/api/upload", pdf, {"X-Filename": "..%2Foutside.pdf"})[0], 400)

    def test_reject_cross_origin_and_untrusted_host(self):
        self.assertEqual(self.request("POST", "/api/reset", {}, {"Origin": "https://external.example"})[0], 403)
        self.assertEqual(self.request("GET", "/api/state", headers={"Host": "external.example"})[0], 403)

    def test_real_tool_execution_stream_and_download(self):
        status, headers, body = self.request("POST", "/api/run", {
            "task": "读取并保存", "api_key": "test-only-secret", "base_url": "https://api.deepseek.com", "model": "test"})
        self.assertEqual(status, 200)
        events = [json.loads(line) for line in body.splitlines()]
        self.assertEqual(events[-1]["type"], "done")
        tools = [e for e in events if e["type"] == "tool_result"]
        self.assertEqual([e["name"] for e in tools], ["read_pdf", "save_notes"])
        self.assertTrue(all(e["ok"] for e in tools))
        self.assertNotIn(b"test-only-secret", body)
        self.assertNotIn("pages", tools[0])
        status, _, body = self.request("GET", "/api/note?name=web-notes.md")
        self.assertEqual(status, 200)
        self.assertIn("第 1 页", json.loads(body)["content"])
        status, headers, body = self.request("GET", "/api/download?name=web-notes.md")
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertIn("测试笔记", body.decode())
        self.assertEqual(self.request("GET", "/api/note?name=..%2Fagent.py")[0], 400)
        self.assertEqual(self.request("GET", "/api/state")[0], 200)
        _, _, body = self.request("GET", "/api/state")
        self.assertTrue(json.loads(body)["has_history"])
        self.assertEqual(self.request("POST", "/api/reset", {})[0], 200)
        _, _, body = self.request("GET", "/api/state")
        self.assertFalse(json.loads(body)["has_history"])

    def test_reject_invalid_api_parameters(self):
        self.assertEqual(self.request("POST", "/api/run", {"task": "test"})[0], 400)
        self.assertEqual(self.request("POST", "/api/run", {"task": "test", "api_key": "test-only",
            "base_url": "http://example.com", "model": "test"})[0], 400)
        self.assertEqual(self.calls, 0)

    def test_model_error_is_visible_and_session_can_retry(self):
        def failed(*args):
            raise RuntimeError("API HTTP 401；请检查密钥")
        self.server.app.model_call = failed
        _, _, body = self.request("POST", "/api/run", {"task": "读取", "api_key": "test-only-secret",
            "base_url": "https://api.deepseek.com", "model": "test"})
        events = [json.loads(line) for line in body.splitlines()]
        self.assertEqual(events[-1]["type"], "error")
        self.assertIn("401", events[-1]["text"])
        self.assertNotIn(b"test-only-secret", body)
        self.assertEqual(self.request("POST", "/api/reset", {})[0], 200)


if __name__ == "__main__":
    unittest.main()
