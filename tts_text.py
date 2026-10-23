# -*- coding: utf-8 -*-
"""按标点分句。书名号里面的标点不切。顿号不切，过短的小句并进下一句。"""
from __future__ import annotations

from array import array

# 顿号不切：切开会把「雾、日出」拆成两三个字，模型会在每段末尾垫静音。
_MARKS = "，。！？；,.!?"
_MIN_CORE = 8


def split_by_marks(text: str) -> list:
    raw = (text or "").strip()
    if not raw:
        return []
    parts = []
    buf = []
    depth = 0
    n = len(raw)
    for i, ch in enumerate(raw):
        buf.append(ch)
        if ch == "《":
            depth += 1
            continue
        if ch == "》":
            if depth > 0:
                depth -= 1
            continue
        if depth != 0 or ch not in _MARKS:
            continue
        if ch in ".,":
            prev_d = i > 0 and raw[i - 1].isdigit()
            next_d = i + 1 < n and raw[i + 1].isdigit()
            if prev_d and next_d:
                continue
        piece = "".join(buf).strip()
        if piece:
            parts.append(piece)
        buf = []
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return _merge_short(parts) or [raw]


def _core_len(piece: str) -> int:
    return len(piece.strip("，。！？；、,.!? \n"))


def _merge_short(parts: list) -> list:
    """不足八个字的小句并进下一句，避免模型为两三字单独垫一段空白。"""
    if len(parts) < 2:
        return parts
    merged = []
    pending = ""
    for piece in parts:
        pending = pending + piece if pending else piece
        if _core_len(pending) >= _MIN_CORE:
            merged.append(pending)
            pending = ""
    if pending:
        if merged:
            merged[-1] += pending
        else:
            merged.append(pending)
    return merged


def polish_pcm(pcm: bytes, sr: int = 24000) -> bytes:
    """去掉句首句尾静音。零星尖峰不算人声。超过约 0.2 秒的空白收到约 0.16 秒，偏轻的人声抬到接近满幅。"""
    if not pcm:
        return b""
    n = len(pcm) - (len(pcm) % 2)
    if n < 4:
        return b""
    samples = array("h")
    samples.frombytes(pcm[:n])
    hop = max(int(sr * 0.02), 1)
    nframes = len(samples) // hop
    if nframes < 3:
        return samples.tobytes()
    rms = []
    peak = 0
    for i in range(nframes):
        base = i * hop
        acc = 0
        local = 0
        for s in samples[base:base + hop]:
            v = s if s >= 0 else -s
            if v > local:
                local = v
            acc += s * s
        if local > peak:
            peak = local
        rms.append((acc / hop) ** 0.5)
    if peak < 200:
        return b""
    speech = _speech_mask(rms, peak)
    if not any(speech):
        return b""
    first = next(i for i, on in enumerate(speech) if on)
    last = nframes - 1 - next(i for i, on in enumerate(reversed(speech)) if on)
    head = max(0, first - 1)
    tail = min(nframes, last + 3)
    max_sil = 8
    keep = []
    i = head
    while i < tail:
        if speech[i]:
            keep.append(i)
            i += 1
            continue
        j = i
        while j < tail and not speech[j]:
            j += 1
        run = j - i
        if run <= max_sil + 2:
            keep.extend(range(i, j))
        else:
            keep.extend(range(i, min(i + 4, j)))
            if j - 4 > i + 4:
                keep.extend(range(j - 4, j))
        i = j
    if not keep:
        return b""
    out = array("h")
    speech_peak = 0
    for frame in keep:
        base = frame * hop
        chunk = samples[base:base + hop]
        if speech[frame]:
            for s in chunk:
                v = s if s >= 0 else -s
                if v > speech_peak:
                    speech_peak = v
        out.extend(chunk)
    out = _lift_quiet(out, sr)
    fade = min(int(sr * 0.008), len(out) // 4)
    if fade > 1:
        last_i = len(out) - 1
        for k in range(fade):
            g = k / (fade - 1)
            out[k] = int(out[k] * g)
            out[last_i - k] = int(out[last_i - k] * g)
    if 800 <= speech_peak < 27000 and len(out) > 0:
        gain = 30000.0 / speech_peak
        for k in range(len(out)):
            v = int(out[k] * gain)
            if v > 32767:
                v = 32767
            elif v < -32768:
                v = -32768
            out[k] = v
    return out.tobytes()


def _lift_quiet(samples: array, sr: int) -> array:
    """把明显偏轻的人声抬向本句的中等响度，停顿保持原样。"""
    import numpy as np

    x = np.asarray(samples, dtype=np.float32)
    win = int(sr * 0.4)
    hop = int(sr * 0.1)
    if x.size < win or win <= 0:
        return samples
    nwin = 1 + (x.size - win) // hop
    rms = np.empty(nwin, dtype=np.float32)
    peaks = np.empty(nwin, dtype=np.float32)
    for i in range(nwin):
        sl = x[i * hop:i * hop + win]
        rms[i] = np.sqrt(np.mean(sl * sl))
        peaks[i] = np.max(np.abs(sl))
    voiced = np.sort(rms[rms >= 900])
    if voiced.size < 4:
        return samples
    target = float(voiced[int(voiced.size * 0.55)])
    gains = np.ones(nwin, dtype=np.float32)
    soft = (rms >= 700) & (rms < target)
    raw = np.minimum(target / np.maximum(rms, 1.0), 1.8)
    cap = 28000.0 / np.maximum(peaks, 1.0)
    gains[soft] = np.maximum(1.0, np.minimum(raw[soft], cap[soft]))
    centers = np.arange(nwin, dtype=np.float32) * hop + (win // 2)
    curve = np.interp(np.arange(x.size, dtype=np.float32), centers, gains).astype(np.float32)
    y = np.clip(np.round(x * curve), -32768, 32767).astype("<i2")
    lifted = array("h")
    lifted.frombytes(y.tobytes())
    return lifted


def _speech_mask(rms, peak: int) -> list:
    """连续约 60ms 超过阈值才算人声，短空白补上，避免把字切断，也避免把噪声尖峰当成语音。"""
    nframes = len(rms)
    thr = max(500.0, peak * 0.045)
    speech = [False] * nframes
    run = 0
    need = 3
    hang = 4
    for i, value in enumerate(rms):
        if value >= thr:
            run += 1
        else:
            run = 0
        if run >= need:
            start = max(0, i - need + 1)
            end = min(nframes, i + 1 + hang)
            for k in range(start, end):
                speech[k] = True
    i = 0
    while i < nframes:
        if speech[i]:
            i += 1
            continue
        j = i
        while j < nframes and not speech[j]:
            j += 1
        if i > 0 and j < nframes and (j - i) <= 5:
            for k in range(i, j):
                speech[k] = True
        i = j
    return speech
