# -*- coding: utf-8 -*-
"""150～200 字并发阶梯。找出 RTF 仍全部小于 1 的最大客户数。"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from bench_three import TEXTS

URL = os.environ.get("TTS_URL", "http://127.0.0.1:8812/v1/tts")
# 单路大约十几秒。阶梯太高会把后面的客户堵在锁后面。
LEVELS = [1, 2, 3, 4, 6, 8]


def one(index: int, text: str) -> dict:
    body = json.dumps(
        {"text": text, "speaker_id": "monet", "format": "pcm", "stream": True},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    first = None
    nbytes = 0
    sr = 24000
    err = ""
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            sr = int(resp.headers.get("X-Sample-Rate") or 24000)
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                if first is None:
                    first = time.perf_counter() - t0
                nbytes += len(chunk)
    except Exception as exc:
        err = "%s: %s" % (type(exc).__name__, exc)
    wall = time.perf_counter() - t0
    audio = nbytes / 2.0 / float(sr) if sr and nbytes else 0.0
    return {
        "client": index,
        "chars": len(text),
        "first_s": None if first is None else round(first, 3),
        "audio_s": round(audio, 3),
        "wall_s": round(wall, 3),
        "rtf": round(wall / audio, 3) if audio else None,
        "error": err,
    }


def trial(n: int) -> list:
    jobs = [(i, TEXTS[i % len(TEXTS)]) for i in range(n)]
    rows = []
    with ThreadPoolExecutor(max_workers=n) as pool:
        futs = [pool.submit(one, i, text) for i, text in jobs]
        for fut in as_completed(futs):
            rows.append(fut.result())
    rows.sort(key=lambda r: r["client"])
    return rows


def ok(rows: list) -> bool:
    if any(r["error"] or not r["rtf"] for r in rows):
        return False
    return all(r["rtf"] < 1 for r in rows)


def main() -> int:
    for text in TEXTS:
        if not 150 <= len(text) <= 200:
            print("样例字数 %s 不在 150～200" % len(text))
            return 1
    print("目标 %s" % URL)
    print("判定：每一路都成功，且 RTF = 耗时/音频 < 1")
    best = 0
    last = []
    for n in LEVELS:
        print("并发 %s ..." % n)
        rows = trial(n)
        last = rows
        firsts = [r["first_s"] for r in rows if r["first_s"] is not None]
        rtfs = [r["rtf"] for r in rows if r["rtf"] is not None]
        errs = [r["error"] for r in rows if r["error"]]
        print("  首包 %s ~ %s  RTF %s ~ %s  失败 %s" % (
            min(firsts) if firsts else "-",
            max(firsts) if firsts else "-",
            min(rtfs) if rtfs else "-",
            max(rtfs) if rtfs else "-",
            len(errs),
        ))
        if not ok(rows):
            print("  这一档不达标")
            break
        best = n
    print()
    print("======== 并发报告 ========")
    print("最大同时客户数（全部 RTF<1）: %s" % best)
    if last and best and best != last[0]["client"] + len(last):
        pass
    if last:
        print("最后一档明细:")
        print("%-6s %-8s %-8s %-8s %-8s %s" % ("客户", "首包秒", "音频秒", "耗时秒", "RTF", "错误"))
        for r in last:
            print("%-6s %-8s %-8s %-8s %-8s %s" % (
                r["client"], r["first_s"], r["audio_s"], r["wall_s"], r["rtf"], r["error"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
