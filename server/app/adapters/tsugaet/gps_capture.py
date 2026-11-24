"""Чтение одного сырого GPS-ответа с ограничением объёма и времени."""

import asyncio
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class GpsReply:
    status: int | None
    body: bytes
    issue: str | None = None


async def capture_markers(
    client: httpx.AsyncClient, url: httpx.URL, *, max_bytes: int, timeout_s: float
) -> GpsReply:
    body = bytearray()
    status: int | None = None
    try:
        async with asyncio.timeout(timeout_s), client.stream("GET", url) as response:
            status = response.status_code
            length = response.headers.get("content-length", "")
            if length.isdecimal() and int(length) > max_bytes:
                return GpsReply(status, b"", "byte_limit")
            async for chunk in response.aiter_raw():
                remaining = max_bytes - len(body)
                body.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    return GpsReply(status, bytes(body), "byte_limit")
            if response.headers.get("content-encoding", "identity").lower() != "identity":
                return GpsReply(status, bytes(body), "content_encoding")
    except (TimeoutError, httpx.RequestError) as exc:
        return GpsReply(status, bytes(body), type(exc).__name__)
    return GpsReply(status, bytes(body), None if status == 200 else "http_status")
