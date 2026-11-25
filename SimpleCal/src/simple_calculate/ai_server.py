"""Serve the SimpleCal page and its optional AI explanation endpoint on loopback."""

from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from http.client import HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from operator import add, floordiv, mul, sub
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .validate import eval_text


PAGE = Path(__file__).resolve().parents[2] / "口算练习.html"
HOST = "127.0.0.1"
DEFAULT_PORT = 8765
OPERATORS = {"+": ("+", add), "-": ("−", sub), "*": ("×", mul), "/": ("÷", floordiv)}


class ExplanationError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class ModelConfig:
    base_url: str
    model: str
    api_key: str

    @classmethod
    def from_environment(cls) -> ModelConfig:
        base = os.getenv("SIMPLECAL_API_BASE", "https://api.openai.com/v1").strip().rstrip("/")
        model = os.getenv("SIMPLECAL_MODEL", "gpt-4.1-mini").strip()
        key = os.getenv("SIMPLECAL_API_KEY", "").strip()
        try:
            url = urlsplit(base)
            port = url.port
        except ValueError:
            raise ValueError("SIMPLECAL_API_BASE 格式有误。") from None
        local_http = url.scheme == "http" and url.hostname in ("127.0.0.1", "localhost", "::1")
        if (
            not url.hostname or (url.scheme != "https" and not local_http)
            or url.username is not None or "?" in base or "#" in base
            or any(char.isspace() for char in base) or port == 0
            or url.path.endswith("/chat/completions")
        ):
            raise ValueError("SIMPLECAL_API_BASE 请填写接口基础地址，例如 https://api.openai.com/v1。")
        if not model:
            raise ValueError("请填写 SIMPLECAL_MODEL。")
        if key and (not key.isascii() or any(char.isspace() or not char.isprintable() for char in key)):
            raise ValueError("SIMPLECAL_API_KEY 格式有误。")
        return cls(base, model, key)


def worked_solution(expression: str) -> tuple[str, list[str]]:
    if not re.fullmatch(r"[0-9\s+＋*/×⋅·÷−–—－()-]{1,100}", expression):
        raise ValueError("算式含有不支持的字符或超出长度。")
    operations: list[tuple[str, int, int]] = []
    answer, values = eval_text(expression, operations=operations)
    if len(operations) not in (1, 2) or not all(0 <= value <= 100 for value in values):
        raise ValueError("只支持 100 以内的一步和两步口算题。")

    if len(operations) == 1:
        op, left, right = operations[0]
        if op == "+" and 1 <= left <= 9 and 1 <= right <= 9 and answer > 10:
            gap = 10 - left
            rest = right - gap
            return "凑十法", [f"{right} = {gap} + {rest}", f"{left} + {gap} = 10", f"10 + {rest} = {answer}"]
        if op == "-" and 11 <= left <= 19 and left - 10 < right <= 9:
            gap = left - 10
            rest = right - gap
            return "平十法", [f"{right} = {gap} + {rest}", f"{left} − {gap} = 10", f"10 − {rest} = {answer}"]

    equations = []
    for op, left, right in operations:
        symbol, calculate = OPERATORS[op]
        equations.append(f"{left} {symbol} {right} = {calculate(left, right)}")
    return "按算式顺序讲解", equations


def explain(
    config: ModelConfig, expression: str, *, before_model_call: Callable[[], None] | None = None,
) -> list[dict[str, str]]:
    method, equations = worked_solution(expression)
    if not config.api_key:
        raise ExplanationError(503, "请先配置 SIMPLECAL_API_KEY，再重启本地服务。")
    if before_model_call is not None:
        before_model_call()

    messages = [
        {"role": "system", "content": (
            "你是小学口算老师。根据给出的题面、教学方法和已算好的等式，"
            "按原顺序为每条等式写一句简短的中文解释，说明怎么想或为什么先做这一步。"
            "加减可讲凑十、平十或拆分，乘除可用口诀或平均分，两步题说明运算优先级。"
            "沿用给出的步骤，不增删、改写或重复等式，不输出阿拉伯数字或运算符。"
            '只返回形如 {"steps":["说明文字"]} 的 JSON 对象，steps 条数与等式条数相同。'
        )},
        {"role": "user", "content": json.dumps(
            {"题面": expression, "教学方法": method, "已核算等式": equations}, ensure_ascii=False,
        )},
    ]
    host = urlsplit(config.base_url).hostname
    token_field = "max_completion_tokens" if host == "api.openai.com" else "max_tokens"
    payload = {"model": config.model, "messages": messages, token_field: 500}
    if host in ("api.openai.com", "api.deepseek.com"):
        payload["response_format"] = {"type": "json_object"}
    if host == "api.deepseek.com":
        payload["thinking"] = {"type": "disabled"}
    request = Request(
        config.base_url + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"},
    )
    try:
        with build_opener(NoRedirect()).open(request, timeout=12) as response:
            body = response.read(65537)
    except HTTPError as error:
        if error.code in (401, 403):
            message = "模型服务拒绝了请求，请检查 API Key 与模型访问权限。"
        elif error.code == 402:
            message = "模型服务余额不足，请检查 API 账户。"
        elif error.code == 429:
            message = "模型服务暂时超出调用限额，请稍后重试或检查 API 额度。"
        elif error.code in (400, 404):
            message = "模型服务无法处理请求，请检查接口基础地址和模型名称。"
        else:
            message = "模型服务暂时无法响应，请稍后重试。"
        error.close()
        raise ExplanationError(502, message) from None
    except (URLError, OSError, HTTPException):
        raise ExplanationError(502, "连接模型服务失败或超时，请检查网络后重试。") from None

    try:
        if len(body) > 65536:
            raise ValueError
        choice = json.loads(body)["choices"][0]
        if choice.get("finish_reason") not in ("stop", None):
            raise ValueError
        content = choice["message"]["content"].strip()
        fenced = re.fullmatch(r"```(?:json)?[ \t]*\r?\n(.*?)\s*```", content, re.IGNORECASE | re.DOTALL)
        if fenced:
            content = fenced.group(1)
        descriptions = json.loads(content)["steps"]
        if not isinstance(descriptions, list) or len(descriptions) != len(equations):
            raise ValueError
        if any(
            not isinstance(text, str) or not 1 <= len(text.strip()) <= 120
            or re.search(r"[\d=＝+×÷−*/<>]", text)
            for text in descriptions
        ):
            raise ValueError
    except (AttributeError, IndexError, KeyError, RecursionError, TypeError, ValueError):
        raise ExplanationError(502, "模型返回的讲解格式有误，可以再试一次。") from None
    return [{"text": text.strip(), "equation": equation} for text, equation in zip(descriptions, equations)]


class SimpleCalServer(ThreadingHTTPServer):
    def __init__(self, port: int, config: ModelConfig) -> None:
        self.config = config
        self.page = PAGE.read_bytes()
        super().__init__((HOST, port), SimpleCalHandler)
        self.authority = f"{HOST}:{self.server_port}"


class SimpleCalHandler(BaseHTTPRequestHandler):
    server: SimpleCalServer
    timeout = 20

    def send_body(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass  # The user may have moved to the next question.

    def send_json(self, status: int, data: dict) -> None:
        self.send_body(status, "application/json; charset=utf-8", json.dumps(data, ensure_ascii=False).encode())

    def do_GET(self) -> None:
        if self.headers.get("Host") != self.server.authority:
            self.send_error(403)
        elif self.path != "/":
            self.send_error(404)
        else:
            self.send_body(200, "text/html; charset=utf-8", self.server.page)

    def do_POST(self) -> None:
        if (
            self.headers.get("Host") != self.server.authority
            or self.headers.get("Origin") != f"http://{self.server.authority}"
        ):
            self.send_error(403)
            return
        if self.path != "/api/explain":
            self.send_error(404)
            return
        if self.headers.get_content_type() != "application/json":
            self.send_json(415, {"error": "需要 JSON 格式的算式。"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1024 or self.headers.get("Transfer-Encoding"):
                raise ValueError
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict) or set(data) != {"expression"} or not isinstance(data["expression"], str):
                raise ValueError
            steps = explain(self.server.config, data["expression"])
        except (ValueError, RecursionError):
            self.send_json(400, {"error": "请提交当前练习中的有效口算题。"})
        except ExplanationError as error:
            self.send_json(error.status, {"error": str(error)})
        else:
            self.send_json(200, {"steps": steps})


def main() -> None:
    parser = argparse.ArgumentParser(description="启动 SimpleCal 本地 AI 讲解服务")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"本地端口，默认 {DEFAULT_PORT}")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("端口需在 1 至 65535 之间。")
    try:
        config = ModelConfig.from_environment()
        server = SimpleCalServer(args.port, config)
    except (OSError, ValueError) as error:
        parser.exit(1, f"无法启动 SimpleCal：{error}\n")
    with server:
        print(f"打开 http://{server.authority}/ 进入 SimpleCal。按 Ctrl+C 退出。")
        if not config.api_key:
            print("当前未配置 SIMPLECAL_API_KEY，内置练习和提示仍可用。")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
