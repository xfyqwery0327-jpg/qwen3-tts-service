# -*- coding: utf-8 -*-
"""按 API.md 检查 8812：健康检查、模式、三个人物和 WebSocket。"""
from __future__ import annotations

import asyncio
import base64
import json
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8812"
SPEAKERS = ["kumarajiva", "monet", "fuhao"]
LINES = {
    "monet": "我是克洛德·莫奈。",
    "fuhao": "我是妇好。",
    "kumarajiva": "我是鸠摩罗什。",
}


def req(method, path, body=None, timeout=120):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, dict(resp.headers), raw
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def expect(ok, message):
    print(("通过  " if ok else "失败  ") + message)
    return ok


def pcm_stats(raw, sr):
    if len(raw) < 2:
        return 0.0, 0
    import array
    samples = array.array("h")
    samples.frombytes(raw[: len(raw) - (len(raw) % 2)])
    peak = max((abs(n) for n in samples), default=0)
    audio = len(samples) / float(sr or 24000)
    return audio, peak


def main() -> int:
    failed = 0
    status, _headers, raw = req("GET", "/health", timeout=5)
    health = json.loads(raw.decode("utf-8"))
    failed += not expect(status == 200 and health.get("ok") is True, "GET /health 200")
    failed += not expect(health.get("speakers") == SPEAKERS, "speakers=%s" % health.get("speakers"))
    failed += not expect(health.get("voices_cached") == SPEAKERS, "voices_cached=%s" % health.get("voices_cached"))
    failed += not expect(health.get("xvec_only") is True and health.get("prefill") is False, "默认 xvec_only")
    failed += not expect(health.get("dtype") == "bfloat16", "dtype=%s" % health.get("dtype"))
    failed += not expect(health.get("chunk_size") == 8, "chunk_size=%s" % health.get("chunk_size"))
    failed += not expect(health.get("sample_rate") == 24000, "sample_rate=%s" % health.get("sample_rate"))
    failed += not expect(health.get("model_loads") == 1, "model_loads=%s" % health.get("model_loads"))
    failed += not expect(health.get("reload_each_sentence") is False, "句间不重新加载")

    status, _headers, raw = req("GET", "/v1/mode")
    mode = json.loads(raw.decode("utf-8"))
    failed += not expect(status == 200 and mode == {"xvec_only": True, "prefill": False}, "GET /v1/mode")

    status, _headers, raw = req("POST", "/v1/mode", {})
    failed += not expect(status == 400 and "需要" in raw.decode("utf-8"), "模式字段都空返回 400")
    status, _headers, raw = req("POST", "/v1/mode", {"xvec_only": True, "prefill": True})
    failed += not expect(status == 400 and "不能同为" in raw.decode("utf-8"), "模式冲突返回 400")

    status, _headers, raw = req("POST", "/v1/tts", {"text": "  ", "speaker_id": "monet"})
    failed += not expect(status == 400 and "text 为空" in raw.decode("utf-8"), "空文本返回 400")
    status, _headers, raw = req("POST", "/v1/tts", {"text": "你好。", "speaker_id": "nobody"})
    failed += not expect(status == 400 and "未知 speaker_id" in raw.decode("utf-8"), "未知人物返回 400")
    status, _headers, raw = req("POST", "/v1/tts", {
        "text": "你好。", "speaker_id": "monet", "xvec_only": False, "prefill": False,
    })
    failed += not expect(status == 400 and "不能同为" in raw.decode("utf-8"), "单句模式冲突返回 400")

    for speaker, text in LINES.items():
        t0 = time.perf_counter()
        status, headers, raw = req("POST", "/v1/tts", {
            "text": text, "speaker_id": speaker, "format": "pcm", "stream": True,
        })
        wall = time.perf_counter() - t0
        sr = int(headers.get("X-Sample-Rate") or headers.get("x-sample-rate") or 0)
        xvec = headers.get("X-Xvec-Only") or headers.get("x-xvec-only")
        audio, peak = pcm_stats(raw, sr)
        ok = status == 200 and xvec == "1" and sr == 24000 and audio > 0.3 and peak > 800
        failed += not expect(ok, "%s xvec 首包已收齐 wall=%.2fs audio=%.2fs peak=%s xvec=%s" % (
            speaker, wall, audio, peak, xvec))

    status, headers, raw = req("POST", "/v1/tts", {
        "text": "印象派的魅力。", "speaker_id": "monet", "prefill": True,
    })
    xvec = headers.get("X-Xvec-Only") or headers.get("x-xvec-only")
    audio, peak = pcm_stats(raw, 24000)
    failed += not expect(
        status == 200 and xvec == "0" and audio > 0.3 and peak > 800,
        "单句 prefill 不改服务模式 header=%s audio=%.2fs peak=%s" % (xvec, audio, peak),
    )
    status, _headers, raw = req("GET", "/v1/mode")
    mode = json.loads(raw.decode("utf-8"))
    failed += not expect(mode.get("xvec_only") is True, "单句 prefill 后服务仍是 xvec_only")

    status, _headers, raw = req("POST", "/v1/mode", {"prefill": True})
    mode = json.loads(raw.decode("utf-8"))
    failed += not expect(status == 200 and mode == {"xvec_only": False, "prefill": True}, "切换到 prefill")
    status, headers, raw = req("POST", "/v1/tts", {"text": "今天由我陪你看这场展。", "speaker_id": "fuhao"})
    xvec = headers.get("X-Xvec-Only") or headers.get("x-xvec-only")
    audio, peak = pcm_stats(raw, 24000)
    failed += not expect(
        status == 200 and xvec == "0" and audio > 0.3 and peak > 800,
        "跟随服务 prefill header=%s audio=%.2fs peak=%s" % (xvec, audio, peak),
    )
    status, _headers, raw = req("POST", "/v1/mode", {"xvec_only": True})
    mode = json.loads(raw.decode("utf-8"))
    failed += not expect(status == 200 and mode.get("xvec_only") is True, "切回 xvec_only")

    failed += asyncio.run(ws_once())
    print("失败 %s 项" % failed)
    return 1 if failed else 0


async def ws_once() -> int:
    import websockets
    uri = "ws://127.0.0.1:8812/ws/kumarajiva/tts"
    async with websockets.connect(uri) as ws:
        ready = json.loads(await ws.recv())
        ok = ready.get("type") == "ready" and ready.get("speaker") == "kumarajiva" and ready.get("xvec_only") is True
        if not expect(ok, "WebSocket ready %s" % ready.get("speaker")):
            return 1
        await ws.send(json.dumps({"type": "tts", "text": "我出生在龟兹。"}, ensure_ascii=False))
        start = json.loads(await ws.recv())
        if start.get("type") != "tts_start" or start.get("xvec_only") is not True:
            expect(False, "WebSocket tts_start %s" % start)
            return 1
        seqs = []
        pcm = bytearray()
        while True:
            msg = json.loads(await ws.recv())
            if msg.get("type") == "tts_chunk":
                seqs.append(msg.get("seq"))
                pcm.extend(base64.b64decode(msg["data"]))
            elif msg.get("type") == "tts_end":
                audio, peak = pcm_stats(bytes(pcm), 24000)
                ok = msg.get("seq_count") == len(seqs) and seqs == list(range(len(seqs))) and audio > 0.3 and peak > 800
                return 0 if expect(ok, "WebSocket 鸠摩罗什 audio=%.2fs peak=%s chunks=%s" % (audio, peak, len(seqs))) else 1
            else:
                expect(False, "WebSocket 意外消息 %s" % msg.get("type"))
                return 1


if __name__ == "__main__":
    raise SystemExit(main())
