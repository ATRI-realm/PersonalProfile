"""Public HTTPS API for the SimpleCal page hosted on GitHub Pages."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from hashlib import sha256
from ipaddress import ip_address
from time import time
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .ai_server import ExplanationError, ModelConfig, explain


# Reserve both quotas atomically before making a potentially billable request.
RESERVE_QUOTA = """
local visitor = tonumber(redis.call('GET', KEYS[1]) or '0')
local total = tonumber(redis.call('GET', KEYS[2]) or '0')
if total >= tonumber(ARGV[2]) then return 2 end
if visitor >= tonumber(ARGV[1]) then return 1 end
redis.call('SET', KEYS[1], visitor + 1, 'EX', ARGV[3])
redis.call('SET', KEYS[2], total + 1, 'EX', ARGV[4])
return 0
"""


class QuotaExceeded(Exception):
    def __init__(self, message: str, retry_after: int) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class RedisQuota:
    def __init__(self, evaluate: Callable, per_ip: int, per_day: int) -> None:
        self.evaluate = evaluate
        self.per_ip = per_ip
        self.per_day = per_day

    def reserve(self, visitor: str) -> None:
        now = int(time())
        minute, minute_offset = divmod(now, 60)
        day, day_offset = divmod(now + 8 * 3600, 86400)  # Beijing time
        minute_left = 60 - minute_offset
        day_left = 86400 - day_offset
        fingerprint = sha256(visitor.encode()).hexdigest()
        result = self.evaluate(
            RESERVE_QUOTA, 2, f"simplecal:ai:minute:{minute}:{fingerprint}",
            f"simplecal:ai:day:{day}", self.per_ip, self.per_day, minute_left, day_left,
        )
        if result == 2:
            raise QuotaExceeded("今天的 AI 讲解次数已用完，请明天再试。", day_left)
        if result == 1:
            raise QuotaExceeded("AI 讲解请求过于频繁，请稍后再试。", minute_left)
        if result != 0:
            raise ExplanationError(503, "AI 讲解暂时无法核对剩余次数，请稍后再试。")

    @classmethod
    def from_environment(cls) -> RedisQuota:
        from redis import Redis
        from redis.exceptions import RedisError

        per_ip = int(os.getenv("SIMPLECAL_AI_PER_IP_PER_MINUTE", "4"))
        per_day = int(os.getenv("SIMPLECAL_AI_PER_DAY", "60"))
        if per_ip < 1 or per_day < 1:
            raise ValueError("AI 讲解的调用上限必须是正整数。")
        url = os.getenv("SIMPLECAL_REDIS_URL", "").strip()
        if not url:
            raise ValueError("请为云端讲解配置 SIMPLECAL_REDIS_URL。")
        client = Redis.from_url(url, socket_connect_timeout=2, socket_timeout=2, retry_on_timeout=False)

        def evaluate(*args):
            try:
                return client.eval(*args)
            except RedisError:
                raise ExplanationError(503, "AI 讲解暂时无法核对剩余次数，请稍后再试。") from None

        return cls(evaluate, per_ip, per_day)


def allowed_origins() -> list[str]:
    entries = os.getenv("SIMPLECAL_ALLOWED_ORIGINS", "https://atri-realm.github.io").split(",")
    origins = []
    for entry in entries:
        value = entry.strip().rstrip("/")
        url = urlsplit(value)
        if not url.hostname or url.username is not None or url.path or "?" in value or "#" in value:
            raise ValueError("SIMPLECAL_ALLOWED_ORIGINS 仅填写网页源，例如 https://atri-realm.github.io。")
        if url.scheme != "https" and not (url.scheme == "http" and url.hostname == "127.0.0.1"):
            raise ValueError("公开网页源必须使用 HTTPS。")
        origins.append(value)
    return origins


def visitor_address(request: Request, on_render: bool) -> str:
    # Render receives public traffic through Cloudflare. Ignore client-supplied forwarding headers elsewhere.
    if on_render:
        forwarded = request.headers.get("cf-connecting-ip", "")
        try:
            return str(ip_address(forwarded))
        except ValueError:
            pass
    return request.client.host if request.client else "unknown"


def create_app(*, quota: RedisQuota | None = None) -> FastAPI:
    model = ModelConfig.from_environment()
    origins = allowed_origins()
    quota = RedisQuota.from_environment() if quota is None else quota
    on_render = os.getenv("RENDER") == "true"
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

    @app.get("/healthz")
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok"}, headers={"Cache-Control": "no-store"})

    @app.post("/api/explain")
    async def cloud_explain(request: Request) -> JSONResponse:
        if request.headers.get("origin") not in origins:
            return JSONResponse({"error": "该网页来源未启用 AI 讲解。"}, status_code=403)
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            return JSONResponse({"error": "需要 JSON 格式的算式。"}, status_code=415)

        try:
            body = bytearray()
            async for chunk in request.stream():
                if len(body) + len(chunk) > 1024:
                    return JSONResponse({"error": "算式请求太大。"}, status_code=413)
                body.extend(chunk)
            data = json.loads(body)
            if not isinstance(data, dict) or set(data) != {"expression"} or not isinstance(data["expression"], str):
                raise ValueError
            if not model.api_key:
                return JSONResponse({"error": "云端 AI 讲解尚未配置。"}, status_code=503)
            address = visitor_address(request, on_render)
            steps = await run_in_threadpool(
                explain, model, data["expression"], before_model_call=lambda: quota.reserve(address),
            )
        except (ValueError, RecursionError):
            return JSONResponse({"error": "请提交当前练习中的有效口算题。"}, status_code=400)
        except QuotaExceeded as error:
            return JSONResponse({"error": str(error)}, status_code=429, headers={"Retry-After": str(error.retry_after)})
        except ExplanationError as error:
            return JSONResponse({"error": str(error)}, status_code=error.status)
        return JSONResponse({"steps": steps}, headers={"Cache-Control": "no-store"})

    return app
