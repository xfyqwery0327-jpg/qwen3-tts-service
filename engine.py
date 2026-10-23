# -*- coding: utf-8 -*-
"""faster-qwen3-tts。模型只在启动时加载一次，句间不重建、不重新读权重。

三个人物的参考音在启动时各解析一次，同时留下两份缓存：
xvec_only（no-prefill，只留说话人向量）和 prefill（参考文本加参考码本）。
之后按 speaker_id 和当前模式取缓存，不再读音频。
默认是 xvec_only。chunk_size=8：大约每 8 个 codec 步吐一块波形。
Torch 后端在 warmup 时捕获 CUDA Graph。
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

import numpy as np

from tts_text import polish_pcm, split_by_marks

log = logging.getLogger("qwen-tts-service")

ROOT = Path(__file__).resolve().parent
MODEL_DIR = Path(os.environ.get(
    "QWEN_TTS_MODEL",
    r"D:\projects\digital_human\models\Qwen3-TTS-12Hz-0.6B-Base",
))
VOICE_DIR = ROOT / "voice"
SPEAKERS = {
    "kumarajiva": (
        VOICE_DIR / "kumarajiva" / "TTS-20250515181155.wav",
        "我是鸠摩罗什，也叫罗什，意为童寿。我出生在龟兹，是一名译师。",
    ),
    "monet": (
        VOICE_DIR / "monet" / "monet-senlin_6to12s.wav",
        "隆重登场的光影魔法森林。我们是这片森林的守护者。",
    ),
    "fuhao": (
        VOICE_DIR / "fuhao" / "jimeng-2026-10-23-3521.wav",
        "我的名字叫妇好，是中国第一位女将军，也是商国的皇后。我出生于子国，后由商国将军微城抚养长大，她教了我医术和武功。我在17岁的时候成为了商国皇后，带领商国走向强盛。",
    ),
}
DEFAULT_SPEAKER = "monet"
WARMUP_TEXT = os.environ.get("QWEN_TTS_WARMUP", "印象派的魅力。")
CHUNK_SIZE = max(1, int(os.environ.get("QWEN_TTS_CHUNK_SIZE", "8")))
XVEC_ONLY = os.environ.get("QWEN_TTS_XVEC_ONLY", "1").strip().lower() not in {"0", "false", "no"}


def resolve_mode(xvec_only=None, prefill=None, default=None):
    """xvec_only 为真就是 no-prefill。两者都空时用 default。"""
    if default is None:
        default = XVEC_ONLY
    if xvec_only is None and prefill is None:
        return bool(default)
    if xvec_only is not None and prefill is not None and bool(xvec_only) == bool(prefill):
        raise ValueError("xvec_only 与 prefill 不能同为真或同为假")
    if prefill is not None:
        return not bool(prefill)
    return bool(xvec_only)


def normalize_speaker(speaker_id: str) -> str:
    sid = (speaker_id or "").strip().lower() or DEFAULT_SPEAKER
    if sid not in SPEAKERS:
        known = "、".join(SPEAKERS)
        raise ValueError("未知 speaker_id: %s，可选 %s" % (speaker_id, known))
    return sid


def _patch_qwen_rope() -> None:
    """qwen-tts-hf 在 Transformers 5 上读 config.rope_theta，Mimi 没有这个字段。"""
    import qwen_tts._transformers_compat as compat

    original = compat._default_rope_parameters

    def _safe(config, device=None, seq_len=None, layer_type=None):
        if not hasattr(config, "rope_theta"):
            try:
                config.rope_theta = 10000.0
            except Exception:
                pass
        if hasattr(config, "rope_theta"):
            return original(config, device, seq_len, layer_type)
        import torch
        base = 10000.0
        partial = getattr(config, "partial_rotary_factor", 1.0)
        head_dim = getattr(config, "head_dim", None)
        if head_dim is None:
            head_dim = config.hidden_size // config.num_attention_heads
        dim = int(head_dim * partial)
        inv_freq = 1.0 / (
            base ** (torch.arange(0, dim, 2, dtype=torch.int64).to(device=device, dtype=torch.float) / dim)
        )
        return inv_freq, 1.0

    compat._default_rope_parameters = _safe
    try:
        from transformers.modeling_rope_utils import ROPE_INIT_FUNCTIONS
        if ROPE_INIT_FUNCTIONS.get("default") is original:
            ROPE_INIT_FUNCTIONS["default"] = _safe
    except Exception:
        pass


def _trim_ref(audio, sr: int):
    """参考音头尾的静音不进说话人向量，避免把音量平均拉低。"""
    if audio.size < sr // 5:
        return audio
    peak = float(np.max(np.abs(audio)))
    if peak < 1e-4:
        return audio
    hop = max(int(sr * 0.02), 1)
    n = (audio.size // hop) * hop
    if n < hop:
        return audio
    rms = np.sqrt((audio[:n].reshape(-1, hop) ** 2).mean(axis=1))
    voiced = np.flatnonzero(rms >= peak * 0.03)
    if voiced.size == 0:
        return audio
    start = max(0, int(voiced[0]) - 1) * hop
    end = min(int(audio.size), (int(voiced[-1]) + 2) * hop)
    return np.ascontiguousarray(audio[start:end])


def pcm16(audio) -> bytes:
    arr = np.asarray(audio, dtype=np.float32).reshape(-1)
    if arr.size == 0:
        return b""
    arr = np.clip(arr, -1.0, 1.0)
    return (arr * 32767.0).astype("<i2").tobytes()


class SpeechEngine:
    def __init__(self):
        self.model = None
        self.sample_rate = 24000
        self.ready = False
        self.error = ""
        self.dtype = "bfloat16"
        self.cuda_graph = False
        self.lock = threading.Lock()
        self._loads = 0
        self.voices = {}
        self.xvec_only = XVEC_ONLY

    def load(self) -> None:
        import torch
        _patch_qwen_rope()
        from faster_qwen3_tts import FasterQwen3TTS

        if not MODEL_DIR.is_dir():
            raise FileNotFoundError("模型目录不存在: %s" % MODEL_DIR)
        missing = [str(path) for path, _text in SPEAKERS.values() if not path.is_file()]
        if missing:
            raise FileNotFoundError("参考音不存在: %s" % "；".join(missing))
        if not torch.cuda.is_available():
            raise RuntimeError("faster-qwen3-tts 的 CUDA Graph 需要 CUDA")
        log.info("加载模型 %s dtype=bfloat16 chunk=%s speakers=%s xvec_only=%s",
                 MODEL_DIR, CHUNK_SIZE, ",".join(SPEAKERS), int(self.xvec_only))
        self.model = FasterQwen3TTS.from_pretrained(
            str(MODEL_DIR),
            device="cuda",
            dtype=torch.bfloat16,
            attn_implementation="sdpa",
            local_files_only=True,
        )
        self._loads += 1
        self.sample_rate = int(getattr(self.model, "sample_rate", None) or 24000)
        self._cache_voices()
        log.info("捕获 CUDA Graph warmup")
        self.model.warmup(prefill_len=64)
        self.cuda_graph = True
        for _audio, sr, _timing in self._speak(WARMUP_TEXT, DEFAULT_SPEAKER, self.xvec_only):
            if sr:
                self.sample_rate = int(sr)
        self.ready = True
        self.error = ""
        log.info("就绪 sr=%s loads=%s voices=%s xvec_only=%s 句间不重新加载权重",
                 self.sample_rate, self._loads, ",".join(self.voices), int(self.xvec_only))

    def _load_ref(self, path: Path, silence_secs: float):
        import librosa

        audio, sr = librosa.load(str(path), sr=None, mono=True)
        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        audio = _trim_ref(audio, int(sr))
        if silence_secs > 0 and audio.size:
            silence = np.zeros(int(silence_secs * sr), dtype=np.float32)
            audio = np.concatenate([audio, silence])
        return audio, int(sr)

    def _freeze_prompt(self, items, xvec: bool):
        import torch

        if not isinstance(items, list):
            items = [items]
        for one in items:
            emb = getattr(one, "ref_spk_embedding", None)
            if isinstance(emb, torch.Tensor):
                one.ref_spk_embedding = emb.detach()
            code = getattr(one, "ref_code", None)
            if xvec:
                one.ref_code = None
                one.ref_text = None
                one.x_vector_only_mode = True
                one.icl_mode = False
            else:
                if isinstance(code, torch.Tensor):
                    one.ref_code = code.detach()
                one.x_vector_only_mode = False
                one.icl_mode = True
        return items

    def _cache_voices(self) -> None:
        """每个说话人只解析一次参考音，xvec 和 prefill 两份都留在内存里。"""
        cached = {}
        for speaker, (path, ref_text) in SPEAKERS.items():
            audio, sr = self._load_ref(path, silence_secs=0)
            xvec_items = self.model.model.create_voice_clone_prompt(
                ref_audio=(audio, sr),
                ref_text="",
                x_vector_only_mode=True,
            )
            if audio.size:
                silence = np.zeros(int(0.5 * sr), dtype=np.float32)
                prefill_audio = np.concatenate([audio, silence])
            else:
                prefill_audio = audio
            prefill_items = self.model.model.create_voice_clone_prompt(
                ref_audio=(prefill_audio, sr),
                ref_text=ref_text,
                x_vector_only_mode=False,
            )
            cached[speaker] = {
                "xvec": self._freeze_prompt(xvec_items, True),
                "prefill": self._freeze_prompt(prefill_items, False),
            }
            log.info("音色已缓存 speaker=%s file=%s modes=xvec,prefill", speaker, path.name)
        self.voices = cached

    def set_xvec_only(self, enabled: bool) -> bool:
        self.xvec_only = bool(enabled)
        log.info("切换合成模式 xvec_only=%s prefill=%s", int(self.xvec_only), int(not self.xvec_only))
        return self.xvec_only

    def _speak(self, text: str, speaker: str, xvec_only: bool):
        """一句。调用方必须已经拿着 self.lock。只使用启动时缓存的音色。"""
        cached = self.voices.get(speaker) or {}
        prompt = cached.get("xvec" if xvec_only else "prefill")
        if not prompt:
            raise RuntimeError("音色未缓存: %s" % speaker)
        return self.model.generate_voice_clone_streaming(
            text=text,
            language="Chinese",
            ref_text="",
            voice_clone_prompt=prompt,
            chunk_size=CHUNK_SIZE,
            do_sample=False,
            non_streaming_mode=True,
        )

    def iter_pcm(self, text: str, speaker: str = DEFAULT_SPEAKER, xvec_only=None):
        """按标点分句，逐句流式吐 int16 PCM。模型对象保持不变。"""
        speaker = normalize_speaker(speaker)
        clauses = split_by_marks(text)
        if not clauses:
            return
        with self.lock:
            if self.model is None:
                raise RuntimeError(self.error or "模型未加载")
            use_xvec = self.xvec_only if xvec_only is None else bool(xvec_only)
            for clause in clauses:
                chunks = []
                for audio, sr, _timing in self._speak(clause, speaker, use_xvec):
                    self.sample_rate = int(sr or self.sample_rate)
                    pcm = pcm16(audio)
                    if pcm:
                        chunks.append(pcm)
                polished = polish_pcm(b"".join(chunks), self.sample_rate)
                if polished:
                    yield polished


engine = SpeechEngine()
