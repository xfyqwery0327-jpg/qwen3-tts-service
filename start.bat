@echo off
cd /d D:\projects\qwen-tts-service
if not exist .venv\Scripts\python.exe (
  echo 先创建虚拟环境并安装依赖，见 install.bat
  exit /b 1
)
set PYTHONUNBUFFERED=1
set PYTHONUTF8=1
set QWEN_TTS_MODEL=D:\projects\digital_human\models\Qwen3-TTS-12Hz-0.6B-Base
set QWEN_TTS_CHUNK_SIZE=8
set QWEN_TTS_XVEC_ONLY=1
set QWEN_TTS_WARMUP=印象派的魅力。
set QWEN_TTS_PORT=8812
.venv\Scripts\python.exe -m uvicorn app:app --host 0.0.0.0 --port 8812
