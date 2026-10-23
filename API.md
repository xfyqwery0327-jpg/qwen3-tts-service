# qwen-tts-service 接口文档

独立语音合成服务。只做口播，不调用大模型。默认地址 `http://127.0.0.1:8812`，无鉴权。

合成结果一律是单声道 16-bit 有符号小端 PCM（`int16`）。采样率以响应里的值为准，当前模型为 `24000`。时长（秒）= 字节数 / 2 / 采样率。

同一时刻只跑一路合成。HTTP 与 WebSocket 共用一把锁，后到的请求排队。一次请求里按标点切开的各短句使用同一种模式。

文本按标点切成短句再逐句合成：`，。！？；,.!?`。顿号 `、` 不切。不足八个字的小句会并进下一句。书名号 `《》` 内的标点不切。小数点两侧都是数字时，`.` 和 `,` 也不切。每句合成后会去掉句首句尾静音，把句内超过约 0.2 秒的空白收到约 0.16 秒，把偏轻的人声往本句的正常响度抬，再把整句峰值收到接近满幅。语言固定为中文。

## 音色

`speaker_id` 取 `kumarajiva`、`monet`、`fuhao`，大小写不敏感。参考音在本项目 `voice/`。启动时每个人物只读一次音频，同时缓存两份结果，之后不再打开文件。

| 模式 | 含义 |
| --- | --- |
| `xvec_only`（no-prefill） | 只用说话人向量。参考文本和参考码本不进每句 prefill |
| `prefill` | 参考文本和参考码本进入每句 prefill |

默认是 `xvec_only`。两份缓存都在内存里，用 `/v1/mode` 或单次请求切换，不会重新解析参考音。

| speaker_id | 参考音 | prefill 用的参考文本 |
| --- | --- | --- |
| `kumarajiva` | `voice/kumarajiva/TTS-20250515181155.wav` | 我是鸠摩罗什，也叫罗什，意为童寿。我出生在龟兹，是一名译师。 |
| `monet` | `voice/monet/monet-senlin_6to12s.wav` | 隆重登场的光影魔法森林。我们是这片森林的守护者。 |
| `fuhao` | `voice/fuhao/jimeng-2026-10-23-3521.wav` | 我的名字叫妇好，是中国第一位女将军，也是商国的皇后。我出生于子国，后由商国将军微城抚养长大，她教了我医术和武功。我在17岁的时候成为了商国皇后，带领商国走向强盛。 |

FastAPI 自带 `GET /docs`、`GET /redoc`、`GET /openapi.json`。流式 PCM 和 WebSocket 的细节以本文为准。

## 环境变量

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `QWEN_TTS_PORT` | `8812` | 约定端口。`app.py` 读取后未绑定监听，实际端口以启动命令为准 |
| `QWEN_TTS_MODEL` | `D:\projects\digital_human\models\Qwen3-TTS-12Hz-0.6B-Base` | 模型目录 |
| `QWEN_TTS_WARMUP` | `印象派的魅力。` | 启动预热文本，用当时的模式和 `monet` 的缓存音色跑一句 |
| `QWEN_TTS_CHUNK_SIZE` | `8` | 每块 codec 步数。12Hz 下约 0.67 秒一块波形 |
| `QWEN_TTS_XVEC_ONLY` | `1` | 启动模式。`1` / `true` 为 xvec_only。`0` / `false` / `no` 为 prefill。运行中可用 `/v1/mode` 改 |

模型只在启动时加载一次。未就绪时，健康检查和合成接口返回失败，不会在请求里现场加载。`/v1/mode` 不要求模型已就绪。

## GET /health

查看服务是否可以合成。

**成功 `200`**

```json
{
  "ok": true,
  "engine": "faster-qwen3-tts",
  "tts": true,
  "tts_engine": "faster-qwen3-tts",
  "tts_error": "",
  "dtype": "bfloat16",
  "cuda_graph": true,
  "capture_graph": true,
  "xvec_only": true,
  "prefill": false,
  "speakers": ["kumarajiva", "monet", "fuhao"],
  "voices_cached": ["kumarajiva", "monet", "fuhao"],
  "chunk_size": 8,
  "sample_rate": 24000,
  "model_loads": 1,
  "reload_each_sentence": false
}
```

**未就绪 `503`**，正文结构相同。`ok` 与 `tts` 为 `false`，`tts_error` 为加载失败原因，`voices_cached` 为空数组。

| 字段 | 含义 |
| --- | --- |
| `ok` / `tts` | 模型已加载、两份音色已缓存且预热完成 |
| `tts_error` | 失败原因；就绪时为空字符串 |
| `dtype` | 权重精度，固定 `bfloat16` |
| `cuda_graph` / `capture_graph` | CUDA Graph 是否已捕获。两者相同 |
| `xvec_only` | 当前服务模式是否为 no-prefill。默认 `true` |
| `prefill` | 当前服务模式是否为 prefill。与 `xvec_only` 相反 |
| `speakers` | 可请求的 `speaker_id` |
| `voices_cached` | 已缓存的人物 id。每个人物内部都有 xvec 和 prefill 两份，这里不分开列 |
| `chunk_size` | 当前流式块大小 |
| `sample_rate` | 当前采样率 |
| `model_loads` | 本次进程加载模型的次数 |
| `reload_each_sentence` | 固定 `false`，句间不重新加载权重 |

## /v1/mode

`GET` 查看当前服务模式，`POST` 切换。不重新解析参考音，也不改变已经在跑的那一句。未传模式字段的合成请求跟随这里的结果。

`GET /v1/mode` 与切换成功都返回当前模式。默认是：

```json
{"xvec_only": true, "prefill": false}
```

`POST` 正文传其中一个，或两个互为相反：

```json
{"xvec_only": true}
```

```json
{"prefill": true}
```

```json
{"xvec_only": false, "prefill": true}
```

两个都传且取值相反时，以 `prefill` 为准。

| 状态码 | 正文 | 条件 |
| --- | --- | --- |
| `400` | `{"error":"需要 xvec_only 或 prefill"}` | 两个字段都空 |
| `400` | `{"error":"xvec_only 与 prefill 不能同为真或同为假"}` | 两个字段同为真或同为假 |

## POST /v1/tts

流式返回 PCM。请求体 `Content-Type: application/json`。

```json
{
  "text": "我是克洛德·莫奈。",
  "speaker_id": "monet",
  "format": "pcm",
  "stream": true
}
```

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `text` | string | `""` | 要合成的文本。空白视为空 |
| `speaker_id` | string | `"monet"` | `kumarajiva`、`monet`、`fuhao`。空白时用 `monet` |
| `format` | string | `"pcm"` | 兼容字段。当前实现不读取，响应始终是 PCM |
| `stream` | bool | `true` | 兼容字段。当前实现不读取，响应始终是流 |
| `xvec_only` | bool | 不传 | 只作用于本句。不传则跟随 `/v1/mode`，不改服务模式 |
| `prefill` | bool | 不传 | 只作用于本句。与 `xvec_only` 同时传时规则同 `/v1/mode` |

**成功 `200`**

- `Content-Type: application/octet-stream`
- `X-Sample-Rate`：采样率，例如 `24000`
- `X-Xvec-Only`：本句是否 no-prefill，`1` 或 `0`
- 正文：按生成顺序拼接的 PCM 字节。边合成边下发，第一块到达即可开始播放

```http
POST /v1/tts HTTP/1.1
Host: 127.0.0.1:8812
Content-Type: application/json

{"text":"印象派的魅力。","speaker_id":"fuhao","format":"pcm","stream":true}
```

单句改用 prefill，不改服务模式：

```json
{"text":"印象派的魅力。","speaker_id":"monet","prefill":true}
```

**失败**

| 状态码 | 正文 | 条件 |
| --- | --- | --- |
| `400` | `{"error":"text 为空"}` | `text` 去空白后为空 |
| `400` | `{"error":"未知 speaker_id: …，可选 kumarajiva、monet、fuhao"}` | `speaker_id` 不是三个人物之一 |
| `400` | `{"error":"xvec_only 与 prefill 不能同为真或同为假"}` | 两个模式字段冲突 |
| `503` | `{"error":"<原因>"}` | 模型未加载。原因为空时正文是 `{"error":"模型未加载"}` |

合成过程中抛错：若尚未写出任何音频，连接以服务端错误结束；若已经开始下发，连接会在中途断开，没有额外的 JSON 错误体。

## WebSocket /ws/{speaker}/tts

长连接口播。路径里的 `{speaker}` 决定音色，取值与 `speaker_id` 相同。未知人物在 `ready` 之前返回错误并关闭连接。

连接建立后服务端先发当前服务模式：

```json
{
  "type": "ready",
  "service": "qwen-tts-service",
  "speaker": "monet",
  "speakers": ["kumarajiva", "monet", "fuhao"],
  "xvec_only": true,
  "prefill": false,
  "sample_rate": 24000,
  "chunk_size": 8
}
```

客户端发送文本帧，内容为 JSON：

```json
{"type": "tts", "text": "我是克洛德·莫奈。"}
```

`type` 可省略，或为 `"tts"`。其他 `type` 直接忽略，不回包。`xvec_only` 与 `prefill` 可选，规则和 `POST /v1/tts` 相同；不传则跟随当前服务模式，不改服务模式。

一句合成的下行顺序：

1. `tts_start`：声明本句音频格式和实际使用的模式

```json
{
  "type": "tts_start",
  "format": "pcm",
  "sample_rate": 24000,
  "channels": 1,
  "sample_width": 2,
  "xvec_only": true,
  "prefill": false
}
```

2. `tts_chunk`：若干条，按生成顺序。`seq` 从 `0` 递增。`data` 是这块 PCM 的 Base64（标准字母表，无换行）

```json
{"type": "tts_chunk", "seq": 0, "data": "<base64 pcm>"}
```

3. `tts_end`：本句结束。`seq_count` 等于 chunk 条数。`cancelled` 当前恒为 `false`，没有取消指令

```json
{"type": "tts_end", "seq_count": 3, "cancelled": false}
```

同一连接可以连续发送多句。每句都是 `tts_start` → `tts_chunk`… → `tts_end`。

**错误消息**

```json
{"type": "error", "message": "不是 JSON"}
```

| `message` | 条件 |
| --- | --- |
| `未知 speaker_id: …，可选 kumarajiva、monet、fuhao` | 路径中的人物不在三个人物里。随后连接关闭 |
| `xvec_only 与 prefill 不能同为真或同为假` | 两个模式字段冲突。连接保持 |
| `不是 JSON` | 文本帧无法解析 |
| `text 为空` | `text` 缺失或去空白后为空 |
| 模型错误原文，或 `模型未加载` | 服务未就绪 |

合成过程中抛错时，连接关闭，不一定再收到 `tts_end` 或 `error`。客户端断开后服务端结束该连接。
