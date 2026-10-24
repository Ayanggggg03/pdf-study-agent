# 研读 PDF 学习助手

一个用于课程资料阅读的 AI Agent：读取本地 PDF，生成带页码的中文复习提纲，并将笔记保存为 Markdown。支持本地网页与命令行两种入口，通过 Function Calling 接入真实文件工具。

> 核心提示词见 [PROMPT.md](PROMPT.md)，实际定义位于 [agent.py](agent.py) 的 `SYSTEM`。仓库仅包含项目源码、自动测试、人工测试 PDF 和使用说明，不包含密钥、个人报告、私人资料或运行截图。

## 功能

- PDF 上传与选择，按页码范围阅读。
- 复习提纲、复习问答、核心概念解释与连续追问。
- 展示实际 read_pdf / save_notes 工具执行记录。
- 保存 Markdown 笔记，网页预览及下载。
- 当前页面填写 API 配置，密钥不落盘、不写入浏览器存储。

## 快速开始

需要 Python 3.10 或更新版本。模型 API 必须支持 Chat Completions 的 Function Calling。

下载仓库并进入项目目录，然后执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 网页方式

```powershell
.\.venv\Scripts\python.exe web_app.py --open
```

打开 `http://127.0.0.1:8765`，在右上角“模型设置”填写 API Base URL、模型名称及密钥。默认配置为 DeepSeek；请以账户当前可用的模型名称为准。

选择自带的 `sample.pdf` 或上传自己的文字型 PDF，输入任务并开始研读。右侧可查看工具记录、预览或下载笔记。程序仅监听本机，不需要公网部署；运行期间保留终端，结束时按 Ctrl+C。

Windows 也可运行 `./start-web.ps1`；端口被占用时加 `-Port 8767`。如果系统执行策略不允许运行脚本，直接使用上面的 Python 命令，无需更改安全设置。

### 命令行方式

```powershell
Copy-Item config.example.json config.json
.\.venv\Scripts\python.exe agent.py --key-dialog
```

在 config.json 中填写 Base URL 和模型名称。程序提示时输入密钥，或使用本机 `LLM_API_KEY` 环境变量；不要将密钥写入源码或提交到仓库。

`--key-dialog` 需要 Python 的 Tkinter。没有图形环境时，去掉该参数即可使用终端隐藏输入。

## 运行案例

选择 sample.pdf 的第 1 至 2 页，输入：

> 读取 sample.pdf 的第 1 至 2 页，生成带页码的中文复习提纲，并调用 save_notes 保存为 demo-notes.md。

确认执行记录中两个工具均成功，再检查 `notes/demo-notes.md` 是否实际生成。内容应包含资料来源、页码、核心概念和复习问题。重复运行请换一个笔记名，已有文件不会覆盖。

网页中可勾选“同时保存笔记”并填写文件名；如果模型未完成保存，界面会显示本轮未保存。点击“开启新对话”清空上下文；资料和笔记文件保留。命令行可输入 clear 清空、exit 退出。

## Agent 架构

```text
用户任务 → 模型请求工具 → 本地程序验证并执行 → 工具结果回传模型
          ↑                                        ↓
          └──────── 继续执行或给出最终答复 ──────────┘
```

模型负责理解任务和选择工具，本地程序执行 PDF 读取和文件写入。`TOOLS` 声明工具的 JSON 参数，`run_agent` 实现最多 12 轮的编排循环。PDF 文字、页码、文件列表及会话历史共同构成外部上下文。

| 文件 | 用途 |
|---|---|
| agent.py | 系统提示词、工具、API 请求及调用循环 |
| PROMPT.md | 核心 prompt 与上下文集成说明 |
| web_app.py | 本地网页服务、上传、流式事件和下载接口 |
| web/ | HTML、CSS 与 JavaScript 界面 |
| config.example.json | 不含密钥的接口配置示例 |
| tests/ | 模型模拟响应下的自动测试 |
| data/sample.pdf | 人工创建的两页测试资料 |

## 测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

测试覆盖页码处理、错误输入、禁止覆盖、路径限制、轮数上限、连续追问、密钥输入、请求构造，以及网页的上传、事件、下载和来源验证。模型响应与网络请求使用模拟对象，文件工具真实执行；自动测试不代表真实 API 验收。

## 范围与限制

- 仅支持可提取文字的 PDF，不含 OCR，不处理加密文件。
- PDF 最大 20 MB；每次工具调用最多 10 页、30000 字符；长文档需要分批阅读。
- 模型输出和页码需要人工核对，不能仅凭答复认定文件保存成功。
- 程序在本地运行，生成摘要仍需联网调用配置的模型平台，资料文字会发送给该平台。
- 网页密钥和消息显示刷新后清除，服务端对话暂存于进程内；“开启新对话”或停止服务可清空上下文。
- 数据目录和笔记目录为本机共用，按单人课程作业使用，不作为多用户公网服务。

## 参考

- [DeepSeek 工具调用文档](https://api-docs.deepseek.com/guides/tool_calls/)
- [Function Calling 协议说明](https://developers.openai.com/api/docs/guides/function-calling)
