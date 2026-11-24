"""Готовые GTFS-Realtime потоки для внутреннего OTP updater."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response

from app.services.realtime import RealtimeService

router = APIRouter(prefix="/internal/gtfs-rt", include_in_schema=False)


@router.get("/{feed}")
async def gtfs_realtime(
    feed: Literal["all", "low-floor"], request: Request, version: str
) -> Response:
    service: RealtimeService | None = request.app.state.realtime
    snapshot = service.current if service is not None else None
    if snapshot is None:
        raise HTTPException(status_code=503, detail="Снимок GTFS-Realtime пока недоступен")
    if version != snapshot.low_access.graph_version:
        raise HTTPException(status_code=503, detail="Версия графа и GTFS-Realtime различаются")
    return Response(
        snapshot.all_payload if feed == "all" else snapshot.low_payload,
        media_type="application/x-protobuf",
        headers={
            "Cache-Control": "no-store",
            "X-GoPoint-Graph-Version": snapshot.low_access.graph_version,
        },
    )
