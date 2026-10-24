"""本地网页入口，复用 agent.py 的真实工具与模型循环。"""
import argparse
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import secrets
import threading
from urllib.parse import parse_qs, quote, unquote, urlsplit
import webbrowser

from pypdf import PdfReader
import agent

MAX_PDF = 20 * 1024 * 1024


class StudyApp:
    def __init__(self, root=agent.ROOT, model_call=None):
        self.root = Path(root)
        self.data = self.root / "data"
        self.notes = self.root / "notes"
        self.data.mkdir(exist_ok=True)
        self.notes.mkdir(exist_ok=True)
        self.model_call = model_call or agent.call_model
        self.sessions = {}
        self.session_lock = threading.Lock()

    def session(self, header):
        jar = cookies.SimpleCookie()
        try:
            jar.load(header or "")
        except cookies.CookieError:
            pass
        sid = jar["study_session"].value if "study_session" in jar else ""
        with self.session_lock:
            if sid not in self.sessions:
                if len(self.sessions) >= 64:
                    raise ValueError("页面会话过多，请重启本地服务")
                sid = secrets.token_urlsafe(32)
                self.sessions[sid] = {"history": [], "lock": threading.Lock()}
            return sid, self.sessions[sid]

    def config(self):
        path = self.root / "config.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            data = {}
        return {"base_url": data.get("base_url", "https://api.deepseek.com"),
                "model": data.get("model", "deepseek-flash")}

    def files(self):
        files = []
        for path in sorted(self.data.glob("*")):
            if path.suffix.lower() != ".pdf" or path.is_symlink() or not path.is_file():
                continue
            try:
                pages = len(PdfReader(path).pages)
            except Exception:
                pages = None
            files.append({"name": path.name, "size": path.stat().st_size, "pages": pages})
        return files

    def saved_notes(self):
        paths = [p for p in self.notes.glob("*.md") if p.is_file() and not p.is_symlink()]
        return [{"name": p.name, "size": p.stat().st_size}
                for p in sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)]


class Handler(BaseHTTPRequestHandler):
    server_version = "StudyDesk/1.0"

    def log_message(self, *args):
        pass  # 密钥和用户任务不写入请求日志。

    @property
    def app(self):
        return self.server.app

    def headers_for(self, status, content_type, size=None, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; "
                         "connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if size is not None:
            self.send_header("Content-Length", str(size))
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()

    def json(self, value, status=200, extra=None):
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.headers_for(status, "application/json; charset=utf-8", len(body), extra)
        self.wfile.write(body)

    def guard(self, post=False):
        port = self.server.server_port
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.headers.get("Host") not in hosts:
            self.json({"error": "只允许本机访问"}, 403)
            return False
        if post and self.headers.get("Origin") not in {"http://" + host for host in hosts}:
            self.json({"error": "请求来源不匹配，请从本地页面操作"}, 403)
            return False
        return True

    def body(self, limit):
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 < size <= limit:
            raise ValueError("请求为空或超过大小限制")
        return self.rfile.read(size)

    def do_GET(self):
        if not self.guard():
            return
        parsed = urlsplit(self.path)
        try:
            if parsed.path == "/api/state":
                sid, session = self.app.session(self.headers.get("Cookie"))
                return self.json({"config": self.app.config(), "files": self.app.files(),
                                  "notes": self.app.saved_notes(), "has_history": bool(session["history"])},
                                 extra={"Set-Cookie": f"study_session={sid}; HttpOnly; SameSite=Strict; Path=/"})
            if parsed.path in ("/api/note", "/api/download"):
                name = parse_qs(parsed.query).get("name", [""])[0]
                path = agent.safe_path(self.app.notes, name, ".md")
                content = path.read_text(encoding="utf-8")
                if parsed.path == "/api/note":
                    return self.json({"name": name, "content": content})
                body = content.encode("utf-8")
                self.headers_for(200, "text/markdown; charset=utf-8", len(body),
                                 {"Content-Disposition": "attachment; filename*=UTF-8''" + quote(name)})
                self.wfile.write(body)
                return
            static = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
                      "/style.css": ("style.css", "text/css"), "/favicon.svg": ("favicon.svg", "image/svg+xml")}
            if parsed.path not in static:
                return self.json({"error": "页面不存在"}, 404)
            name, mime = static[parsed.path]
            body = (self.app.root / "web" / name).read_bytes()
            self.headers_for(200, mime + "; charset=utf-8", len(body))
            self.wfile.write(body)
        except FileNotFoundError:
            self.json({"error": "文件不存在"}, 404)
        except (ValueError, OSError):
            self.json({"error": "文件参数无效或无法读取"}, 400)

    def do_POST(self):
        if not self.guard(post=True):
            return
        try:
            sid, session = self.app.session(self.headers.get("Cookie"))
            if self.path == "/api/upload":
                return self.upload()
            if self.headers.get_content_type() != "application/json":
                return self.json({"error": "请使用 JSON 请求"}, 415)
            data = json.loads(self.body(128 * 1024))
            if not isinstance(data, dict):
                raise ValueError("请求格式无效")
            if self.path == "/api/reset":
                if not session["lock"].acquire(blocking=False):
                    return self.json({"error": "任务执行中，请稍后重置"}, 409)
                try:
                    session["history"].clear()
                finally:
                    session["lock"].release()
                return self.json({"ok": True})
            if self.path != "/api/run":
                return self.json({"error": "接口不存在"}, 404)
            task = data.get("task", "")
            key = data.get("api_key", "")
            base = data.get("base_url", "")
            model = data.get("model", "")
            if not all(isinstance(v, str) and v.strip() for v in (task, key, base, model)):
                raise ValueError("请填写任务、API 密钥、接口地址和模型名称")
            if len(task) > 16000 or len(key) > 1024 or len(model) > 200:
                raise ValueError("任务或配置过长")
            url = urlsplit(base.strip())
            if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
                raise ValueError("接口地址须为有效 HTTPS Base URL")
            if not session["lock"].acquire(blocking=False):
                return self.json({"error": "本会话已有任务执行中"}, 409)
            self.headers_for(200, "application/x-ndjson; charset=utf-8", extra={"Connection": "close"})
            self.close_connection = True
            def emit(event):
                self.wfile.write((json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8"))
                self.wfile.flush()
            try:
                emit({"type": "status", "text": "正在请求模型，等待工具调用…"})
                answer = agent.run_agent(task.strip(), {"base_url": base.strip(), "model": model.strip()},
                    key.strip(), self.app.data, self.app.notes, model_call=self.app.model_call,
                    history=session["history"], on_event=emit)
                emit({"type": "done", "answer": answer, "notes": self.app.saved_notes()})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as exc:
                try:
                    text = str(exc) if isinstance(exc, RuntimeError) else "请核对 API 配置、余额和网络，或缩小页码范围后重试。"
                    emit({"type": "error", "text": "任务未完成：" + text})
                except (BrokenPipeError, ConnectionResetError):
                    pass
            finally:
                session["lock"].release()
        except (ValueError, TypeError, OSError):
            self.json({"error": "请求无效，请检查必填项、文件名及大小"}, 400)

    def upload(self):
        name = unquote(self.headers.get("X-Filename", ""))
        path = agent.safe_path(self.app.data, name, ".pdf")
        body = self.body(MAX_PDF)
        if not body.startswith(b"%PDF-"):
            raise ValueError("不是 PDF")
        try:
            pdf = PdfReader(BytesIO(body))
            if pdf.is_encrypted or not len(pdf.pages):
                raise ValueError("PDF 加密或无页面")
        except Exception:
            return self.json({"error": "PDF 无法解析或已加密，请换一份文字型 PDF"}, 400)
        try:
            with path.open("xb") as stream:
                stream.write(body)
        except FileExistsError:
            return self.json({"error": "已有同名资料，请选择列表中的文件或改名后上传"}, 409)
        self.json({"ok": True, "name": name, "files": self.app.files()})


def make_server(port=8765, root=agent.ROOT, model_call=None):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.app = StudyApp(root, model_call)
    server.daemon_threads = True
    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PDF 学习助手本地网页")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="启动后打开默认浏览器")
    args = parser.parse_args()
    try:
        server = make_server(args.port)
    except OSError:
        raise SystemExit("端口已被占用。请关闭之前的服务，或用 --port 指定其他端口。")
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"PDF Study Desk is running: {url}\nPress Ctrl+C to stop.", flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
