@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
set "PORT=8812"
set "PY=%~dp0.venv\Scripts\python.exe"
set "INTERACTIVE="
if "%~1"=="" set "INTERACTIVE=1"

if /I "%~1"=="on" goto do_on
if /I "%~1"=="off" goto do_off
if /I "%~1"=="status" goto do_status
if "%~1"=="" goto menu
echo 用法: switch.bat [on^|off^|status]
exit /b 1

:menu
echo 1 开启
echo 2 关闭
echo 3 状态
choice /C 123 /N /M "请选择:"
if errorlevel 3 goto do_status
if errorlevel 2 goto do_off
goto do_on

:do_on
if not exist "%PY%" (
  echo 未找到 .venv\Scripts\python.exe，请先运行 install.bat
  goto finish_fail
)
call :listening
if defined LISTEN_PID (
  echo 已经在运行。端口 %PORT%  PID !LISTEN_PID!
  goto finish_ok
)
start "qwen-tts-service" cmd /k call "%~dp0start.bat"
echo 已打开启动窗口。模型加载完成前，端口 %PORT% 还没有健康检查。
goto finish_ok

:do_off
call :listening
if not defined LISTEN_PID (
  echo 服务未运行。端口 %PORT% 没有监听。
  goto finish_ok
)
for %%P in (!LISTEN_PID!) do (
  echo 关闭 PID %%P
  taskkill /T /F /PID %%P
  if errorlevel 1 goto finish_fail
)
goto finish_ok

:do_status
call :listening
if not defined LISTEN_PID (
  echo 状态: 未运行
  echo 端口: %PORT%
  goto finish_ok
)
echo 状态: 运行中
echo 端口: %PORT%
echo PID: !LISTEN_PID!
curl.exe -s -m 3 "http://127.0.0.1:%PORT%/health"
set "CURL_RC=!ERRORLEVEL!"
echo.
if not "!CURL_RC!"=="0" echo 健康检查暂无响应，模型可能仍在加载。
goto finish_ok

:listening
set "LISTEN_PID="
set "SEEN= "
for /f "tokens=5" %%P in ('netstat -ano ^| findstr "LISTENING" ^| findstr ":%PORT% "') do (
  echo !SEEN! | findstr /C:" %%P " >nul
  if errorlevel 1 (
    set "SEEN=!SEEN!%%P "
    if defined LISTEN_PID (
      set "LISTEN_PID=!LISTEN_PID! %%P"
    ) else (
      set "LISTEN_PID=%%P"
    )
  )
)
exit /b 0

:finish_ok
if defined INTERACTIVE pause
exit /b 0

:finish_fail
if defined INTERACTIVE pause
exit /b 1
