# -*- coding: utf-8 -*-
"""独立 Qwen3-TTS 服务。不占用讲解员 8848。

HTTP 与讲解进程的 remote TTS 客户端对齐：POST /v1/tts 流式 PCM。
WebSocket /ws/{speaker}/tts 只做口播，不调用大模型。
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from engine import CHUNK_SIZE, SPEAKERS, engine, normalize_speaker, resolve_mode

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("qwen-tts-service")
PORT = int(os.environ.get("QWEN_TTS_PORT", "8812"))


class TtsBody(BaseModel):
    text: str = ""
    speaker_id: str = "monet"
    format: str = "pcm"
    stream: bool = True
    xvec_only: bool | None = None
    prefill: bool | None = None


class ModeBody(BaseModel):
    xvec_only: bool | None = None
    prefill: bool | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        await asyncio.to_thread(engine.load)
    except Exception as exc:
        engine.error = "%s: %s" % (type(exc).__name__, exc)
        log.exception("模型加载失败")
    yield


app = FastAPI(title="qwen-tts-service", lifespan=lifespan)


def _health() -> dict:
    return {
        "ok": engine.ready,
        "engine": "faster-qwen3-tts",
        "tts": engine.ready,
        "tts_engine": "faster-qwen3-tts",
        "tts_error": engine.error,
        "dtype": engine.dtype,
        "cuda_graph": engine.cuda_graph,
        "capture_graph": engine.cuda_graph,
        "xvec_only": engine.xvec_only,
        "prefill": not engine.xvec_only,
        "speakers": list(SPEAKERS),
        "voices_cached": list(engine.voices),
        "chunk_size": CHUNK_SIZE,
        "sample_rate": engine.sample_rate,
        "model_loads": engine._loads,
        "reload_each_sentence": False,
    }


@app.get("/health")
def health():
    body = _health()
    if not engine.ready:
        return JSONResponse(body, status_code=503)
    return body


@app.get("/v1/mode")
def get_mode():
    return {"xvec_only": engine.xvec_only, "prefill": not engine.xvec_only}


@app.post("/v1/mode")
def set_mode(body: ModeBody):
    if body.xvec_only is None and body.prefill is None:
        return JSONResponse({"error": "需要 xvec_only 或 prefill"}, status_code=400)
    try:
        enabled = resolve_mode(body.xvec_only, body.prefill, engine.xvec_only)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    engine.set_xvec_only(enabled)
    return {"xvec_only": engine.xvec_only, "prefill": not engine.xvec_only}


@app.post("/v1/tts")
async def tts(body: TtsBody):
    if not engine.ready:
        return JSONResponse({"error": engine.error or "模型未加载"}, status_code=503)
    text = (body.text or "").strip()
    if not text:
        return JSONResponse({"error": "text 为空"}, status_code=400)
    try:
        speaker = normalize_speaker(body.speaker_id)
        use_xvec = resolve_mode(body.xvec_only, body.prefill, engine.xvec_only)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    async def gen():
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def run():
            try:
                for pcm in engine.iter_pcm(text, speaker, use_xvec):
                    loop.call_soon_threadsafe(queue.put_nowait, pcm)
            except Exception as exc:
                loop.call_soon_threadsafe(queue.put_nowait, exc)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        task = asyncio.create_task(asyncio.to_thread(run))
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                if isinstance(item, Exception):
                    raise item
                yield item
        finally:
            await task

    return StreamingResponse(
        gen(),
        media_type="application/octet-stream",
        headers={
            "X-Sample-Rate": str(engine.sample_rate),
            "X-Xvec-Only": "1" if use_xvec else "0",
        },
    )


@app.websocket("/ws/{speaker}/tts")
async def ws_tts(websocket: WebSocket, speaker: str):
    await websocket.accept()
    try:
        speaker = normalize_speaker(speaker)
    except ValueError as exc:
        await websocket.send_json({"type": "error", "message": str(exc)})
        await websocket.close()
        return
    await websocket.send_json({
        "type": "ready",
        "service": "qwen-tts-service",
        "speaker": speaker,
        "speakers": list(SPEAKERS),
        "xvec_only": engine.xvec_only,
        "prefill": not engine.xvec_only,
        "sample_rate": engine.sample_rate,
        "chunk_size": CHUNK_SIZE,
    })
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "不是 JSON"})
                continue
            if msg.get("type") not in (None, "tts"):
                continue
            text = (msg.get("text") or "").strip()
            if not text:
                await websocket.send_json({"type": "error", "message": "text 为空"})
                continue
            if not engine.ready:
                await websocket.send_json({"type": "error", "message": engine.error or "模型未加载"})
                continue
            try:
                use_xvec = resolve_mode(
                    msg.get("xvec_only"), msg.get("prefill"), engine.xvec_only)
            except ValueError as exc:
                await websocket.send_json({"type": "error", "message": str(exc)})
                continue
            await websocket.send_json({
                "type": "tts_start",
                "format": "pcm",
                "sample_rate": engine.sample_rate,
                "channels": 1,
                "sample_width": 2,
                "xvec_only": use_xvec,
                "prefill": not use_xvec,
            })
            seq = 0
            loop = asyncio.get_running_loop()
            queue: asyncio.Queue = asyncio.Queue()

            def run():
                try:
                    for pcm in engine.iter_pcm(text, speaker, use_xvec):
                        loop.call_soon_threadsafe(queue.put_nowait, pcm)
                except Exception as exc:
                    loop.call_soon_threadsafe(queue.put_nowait, exc)
                finally:
                    loop.call_soon_threadsafe(queue.put_nowait, None)

            task = asyncio.create_task(asyncio.to_thread(run))
            try:
                while True:
                    item = await queue.get()
                    if item is None:
                        break
                    if isinstance(item, Exception):
                        raise item
                    await websocket.send_json({
                        "type": "tts_chunk",
                        "seq": seq,
                        "data": base64.b64encode(item).decode("ascii"),
                    })
                    seq += 1
            finally:
                await task
            await websocket.send_json({
                "type": "tts_end",
                "seq_count": seq,
                "cancelled": False,
            })
    except WebSocketDisconnect:
        return
