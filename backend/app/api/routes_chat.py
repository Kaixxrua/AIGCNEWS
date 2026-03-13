from __future__ import annotations

import json
import traceback
from typing import AsyncGenerator, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from backend.app.repositories.graph_repo import GraphRepository
from backend.app.repositories.milvus_repo import MilvusRepository
from backend.app.services.rag.chat_service import ChatService
from backend.app.services.rag.retriever import HybridRetriever


router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    history: List[dict] = []
    temperature: Optional[float] = Field(default=0.7, ge=0.0, le=2.0)


async def _event_stream(
    message: str,
    history: List[dict],
    temperature: float,
) -> AsyncGenerator[str, None]:
    try:
        retriever = HybridRetriever(MilvusRepository(), GraphRepository())
        service = ChatService(retriever)

        async for payload in service.stream_chat(
            message,
            history=history,
            temperature=temperature,
        ):
            try:
                data = json.dumps(payload, ensure_ascii=False, default=str)
            except Exception:
                data = json.dumps({"type": "error", "data": "serialize_error"})
            yield f"data: {data}\n\n"

    except Exception as exc:
        traceback.print_exc()
        error_payload = json.dumps({"type": "error", "data": str(exc)})
        yield f"data: {error_payload}\n\n"

    finally:
        yield "data: [DONE]\n\n"


@router.post("/chat/stream")
async def stream_chat(request: ChatRequest) -> StreamingResponse:
    return StreamingResponse(
        _event_stream(
            request.message,
            request.history,
            request.temperature or 0.7,
        ),
        media_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Content-Encoding": "identity",
        },
    )
