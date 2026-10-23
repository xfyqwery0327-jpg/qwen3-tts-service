# -*- coding: utf-8 -*-
"""三个人物各三句 150 字以上，记录句间，并把 PCM 存成 wav。"""
from __future__ import annotations

import json
import time
import urllib.request
import wave
from array import array
from pathlib import Path

from tts_text import split_by_marks

BASE = "http://127.0.0.1:8812"
OUT = Path(__file__).resolve().parent / "out"

TEXTS = {
    "monet": [
        "我是克洛德·莫奈。我在勒阿弗尔长大，后来离开画室，走到河边和田野里直接作画。雾、日出、干草堆和水面的反光，都会随着钟点改变。晚年我定居吉维尼，在花园里修了睡莲池，一天里要看很多次同一处风景。若有人问我是谁，我只回答，我是莫奈，我画的是光线在一瞬间的样子。画室里的灯太稳，户外的光却不肯停，所以我把画架搬到风里。",
        "睡莲是我晚年最重要的作品。池塘上的桥被柳树挡住，水面一会儿亮，一会儿又沉进影子里。我不是把花一朵一朵画完，而是把整片水、天光和倒影一起留下来。观众站得近一点，会看见笔触还在动。站得远一点，那些颜色又合成一座安静的花园。同一座池塘，早晨和黄昏完全不是一幅画，我愿意为这个差别再画很多年。水声很轻，花影却一直在动。",
        "日出印象画在勒阿弗尔的港口。那天早上雾很厚，太阳只是一个橘色的点，桅杆和吊车都糊在水汽里。有人说它不像一张完成的画，我却觉得那正是我看见的早晨。光线来得很快，稍一犹豫，港口就会变成另外一个样子。我记下的不是船的名字，而是雾打开的那一小会儿，以及水面把太阳揉碎以后留下来的颜色。所以我画得很快，也不把轮廓描死。",
    ],
    "fuhao": [
        "我是妇好。我是商王武丁的王后，也是统兵征战的女将军。甲骨上刻着我的名字，出征、祭祀、生育，这些事都留在字里。我打过土方，也打过羌方。王把青铜钺交给我，那不是摆设，是让我统兵的凭据。今天这场展，我只讲我自己的墓、我用过的器物，还有殷墟里挖出来的那些字。你们看见的偶方彝和鸮尊，都是放在我身边的东西。你们可以走近看。",
        "这座墓是我的。墓室很深，里面陪着我的有青铜器、玉器，还有我的兵器。偶方彝像两座房子合在一起，酒从上面倒进去。鸮尊做成猫头鹰的样子，眼睛圆，翅膀收着。这些不是后来人仿的样子，是我活着的时候就放在身边的礼器。你们今天看见的，是从殷墟我的墓里起出来的。我只讲这座墓里的东西，别的展我不管。我把这些器物留在身边。",
        "甲骨上的字很碎，可每一片都记着一件实事。有一片说我带着人去打羌方，王在宫里占卜，问这一仗能不能赢。还有的字记我主持祭祀，用什么牺牲，哪一天。你们不必把每片都读完。我站在这里，是把这些字说成白话。我是妇好，这些仗是我打的，这些礼是我主持的，不是别人替我做的。字少，事情却是真的，我一件一件说给你们听。请你们听仔细。",
    ],
    "kumarajiva": [
        "我是鸠摩罗什，也叫罗什，意为童寿。我出生在龟兹，母亲是龟兹人，父亲从天竺来。小时候母亲带我去罽宾、疏勒学法，后来我又回到龟兹讲经。我做的事是把梵文里的意思说成汉语，让长安的人听得懂。今天这场展就在龟兹，我只讲这里的石窟、舍利盒，还有我走过的路。别的人的故事，我不多讲。我从这里出发，也愿意从这里讲起。",
        "我在凉州住了很多年，才被迎进长安。进了长安以后，我住在逍遥园，带着弟子译经。金刚经、法华经、维摩诘经、阿弥陀经，都是那几年译出来的。我译的时候不是一个字一个字硬搬，而是先把意思讲通，再写成汉语。所以你们现在念到的句子，是我口里说过一遍的。这场展若问我的生平，我就从龟兹讲到长安。我只把译过的经说清楚。",
        "龟兹的石窟里画着佛、菩萨，也画着供养人。克孜尔的壁画颜色还在，库木吐喇、苏巴什也能看见当年的窟。舍利盒上的人在跳舞，那是龟兹的样子，不是长安的样子。我年少时在这里出家、学法、讲经。你们今天看见的若是仿制品，我会按展签说明它是仿的，不把它说成原件。我是罗什，我只讲这场龟兹的展。别的洞窟、别的城，今天不讲。",
    ],
}


def peak_of(pcm: bytes) -> int:
    if len(pcm) < 2:
        return 0
    samples = array("h")
    samples.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    return max((abs(n) for n in samples), default=0)


def save_wav(path: Path, pcm: bytes, sr: int) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sr)
        handle.writeframes(pcm)


def speak(speaker: str, text: str):
    body = json.dumps(
        {"text": text, "speaker_id": speaker, "format": "pcm", "stream": True},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        BASE + "/v1/tts", data=body, headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    first = None
    last = t0
    stalls = []
    buf = bytearray()
    with urllib.request.urlopen(req, timeout=180) as resp:
        sr = int(resp.headers.get("X-Sample-Rate") or 24000)
        while True:
            chunk = resp.read(4096)
            now = time.perf_counter()
            if not chunk:
                break
            if first is None:
                first = now - t0
            else:
                gap = now - last
                if gap >= 0.25:
                    stalls.append(round(gap, 3))
            last = now
            buf.extend(chunk)
    t_end = time.perf_counter()
    wall = t_end - t0
    audio = len(buf) / 2.0 / float(sr)
    return {
        "first_s": round(first or 0, 3),
        "audio_s": round(audio, 2),
        "wall_s": round(wall, 3),
        "rtf": round(wall / audio, 3) if audio else None,
        "peak": peak_of(bytes(buf)),
        "bytes": len(buf),
        "sr": sr,
        "stalls": stalls,
        "pcm": bytes(buf),
        "t_first": t0 + (first or 0),
        "t_end": t_end,
    }


def main() -> int:
    for speaker, lines in TEXTS.items():
        for i, text in enumerate(lines, 1):
            if len(text) < 150:
                print("%s 第%s句只有 %s 字" % (speaker, i, len(text)))
                return 1
    OUT.mkdir(exist_ok=True)
    health = json.load(urllib.request.urlopen(BASE + "/health", timeout=5))
    print("health ok=%s xvec_only=%s voices=%s" % (
        health.get("ok"), health.get("xvec_only"), health.get("voices_cached")))
    rows = []
    for speaker, lines in TEXTS.items():
        prev_end = None
        held = []
        for i, text in enumerate(lines, 1):
            print("发送 %s 第%s句，%s 字，%s 段" % (speaker, i, len(text), len(split_by_marks(text))), flush=True)
            row = speak(speaker, text)
            gap = None if prev_end is None else round(row["t_first"] - prev_end, 3)
            prev_end = row["t_end"]
            held.append((i, text, row, gap))
            print("  首包 %ss  音频 %ss  耗时 %ss  句间 %s  峰值 %s" % (
                row["first_s"], row["audio_s"], row["wall_s"], gap, row["peak"]), flush=True)
        for i, text, row, gap in held:
            name = "%s_%s.wav" % (speaker, i)
            save_wav(OUT / name, row["pcm"], row["sr"])
            rows.append({
                "speaker": speaker,
                "index": i,
                "chars": len(text),
                "clauses": len(split_by_marks(text)),
                "first_s": row["first_s"],
                "audio_s": row["audio_s"],
                "wall_s": row["wall_s"],
                "rtf": row["rtf"],
                "gap_s": gap,
                "peak": row["peak"],
                "stalls": row["stalls"],
                "wav": name,
            })
    lines_out = ["speaker index chars clauses first_s audio_s wall_s rtf gap_s peak wav"]
    for item in rows:
        lines_out.append("%s %s %s %s %s %s %s %s %s %s %s" % (
            item["speaker"], item["index"], item["chars"], item["clauses"],
            item["first_s"], item["audio_s"], item["wall_s"], item["rtf"],
            item["gap_s"], item["peak"], item["wav"]))
    (OUT / "long_report.txt").write_text("\n".join(lines_out) + "\n", encoding="utf-8")
    print("报告 %s" % (OUT / "long_report.txt"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
