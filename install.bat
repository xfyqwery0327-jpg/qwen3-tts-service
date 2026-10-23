@echo off
cd /d D:\projects\qwen-tts-service
if not exist .venv\Scripts\python.exe (
  D:\anaconda\envs\digital_human_server\python.exe -m venv .venv
)
.venv\Scripts\python.exe -m pip install -U pip
.venv\Scripts\python.exe -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu126
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -c "import torch; print('cuda', torch.cuda.is_available(), torch.__version__)"
