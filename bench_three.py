# -*- coding: utf-8 -*-
"""向 8812 连发三句 150～200 字口播，打印首包、音频时长和整段耗时。"""
from __future__ import annotations

import json
import statistics
import time
import urllib.error
import urllib.request

URL = "http://127.0.0.1:8812/v1/tts"
HEALTH = "http://127.0.0.1:8812/health"

TEXTS = [
    "我是克洛德·莫奈。我在勒阿弗尔长大，后来离开画室，走到河边和田野里直接作画。雾、日出、干草堆和水面的反光，都会随着钟点改变。晚年我定居吉维尼，在花园里修了睡莲池，一天里要看很多次同一处风景。若有人问我是谁，我只回答，我是莫奈，我画的是光线在一瞬间的样子。画室里的灯太稳，户外的光却不肯停，所以我把画架搬到风里。",
    "睡莲是我晚年最重要的作品。池塘上的桥被柳树挡住，水面一会儿亮，一会儿又沉进影子里。我不是把花一朵一朵画完，而是把整片水、天光和倒影一起留下来。观众站得近一点，会看见笔触还在动。站得远一点，那些颜色又合成一座安静的花园。同一座池塘，早晨和黄昏完全不是一幅画，我愿意为这个差别再画很多年。水声很轻，花影却一直在动。",
    "日出印象画在勒阿弗尔的港口。那天早上雾很厚，太阳只是一个橘色的点，桅杆和吊车都糊在水汽里。有人说它不像一张完成的画，我却觉得那正是我看见的早晨。光线来得很快，稍一犹豫，港口就会变成另外一个样子。我记下的不是船的名字，而是雾打开的那一小会儿，以及水面把太阳揉碎以后留下来的颜色。所以我画得很快，也不把轮廓描死。",
]


def _post(text: str):
    body = json.dumps(
        {"text": text, "speaker_id": "monet", "format": "pcm", "stream": True},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        URL, data=body, headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    first = None
    nbytes = 0
    sr = 24000
    with urllib.request.urlopen(req, timeout=180) as resp:
        sr = int(resp.headers.get("X-Sample-Rate") or 24000)
        while True:
            chunk = resp.read(4096)
            if not chunk:
                break
            if first is None:
                first = time.perf_counter() - t0
            nbytes += len(chunk)
    wall = time.perf_counter() - t0
    audio = nbytes / 2.0 / float(sr) if sr else 0.0
    return {
        "chars": len(text),
        "first_s": None if first is None else round(first, 3),
        "audio_s": round(audio, 3),
        "wall_s": round(wall, 3),
        "rtf": round(wall / audio, 3) if audio else None,
        "bytes": nbytes,
        "sample_rate": sr,
        "preview": text[:24],
    }


def main() -> int:
    for i, text in enumerate(TEXTS, 1):
        n = len(text)
        if not 150 <= n <= 200:
            print("第%s句字数是 %s，不在 150～200。" % (i, n))
            return 1
    try:
        health = json.load(urllib.request.urlopen(HEALTH, timeout=5))
    except Exception as exc:
        print("8812 健康检查失败: %s" % exc)
        return 1
    rows = []
    print("服务 %s  chunk=%s  xvec_only=%s  cuda_graph=%s" % (
        health.get("engine"), health.get("chunk_size"),
        health.get("xvec_only"), health.get("cuda_graph")))
    for i, text in enumerate(TEXTS, 1):
        print("发送第 %s 句，%s 字…" % (i, len(text)))
        try:
            row = _post(text)
        except urllib.error.HTTPError as exc:
            print("第%s句失败 HTTP %s %s" % (i, exc.code, exc.read()[:200]))
            return 1
        row["index"] = i
        rows.append(row)
        print("  首包 %ss  音频 %ss  耗时 %ss  RTF %s" % (
            row["first_s"], row["audio_s"], row["wall_s"], row["rtf"]))
    firsts = [r["first_s"] for r in rows]
    walls = [r["wall_s"] for r in rows]
    audios = [r["audio_s"] for r in rows]
    print()
    print("======== 8812 三句报告 ========")
    print("%-4s %-6s %-8s %-8s %-8s %-8s %s" % (
        "句", "字数", "首包秒", "音频秒", "耗时秒", "RTF", "开头"))
    for r in rows:
        print("%-4s %-6s %-8s %-8s %-8s %-8s %s" % (
            r["index"], r["chars"], r["first_s"], r["audio_s"],
            r["wall_s"], r["rtf"], r["preview"]))
    print("首包  最小 %s  最大 %s  平均 %s" % (
        min(firsts), max(firsts), round(statistics.mean(firsts), 3)))
    print("耗时  最小 %s  最大 %s  平均 %s" % (
        min(walls), max(walls), round(statistics.mean(walls), 3)))
    print("音频合计 %s 秒，墙钟合计 %s 秒" % (
        round(sum(audios), 3), round(sum(walls), 3)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
