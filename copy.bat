@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "NAME=qwen-tts-service"
set "SRC=%~dp0"
if "%SRC:~-1%"=="\" set "SRC=%SRC:~0,-1%"
set "DEST=D:\projects\copy\%NAME%"
set "ARCHIVE=D:\projects\copy\%NAME%.7z"
set "MODEL_SRC=D:\projects\digital_human\models\Qwen3-TTS-12Hz-0.6B-Base"
set "MODEL_DST=%DEST%\models\Qwen3-TTS-12Hz-0.6B-Base"

if /I "%~1"=="help" goto help
if "%~1"=="1" goto mode1
if "%~1"=="2" goto mode2
if "%~1"=="3" goto mode3
if not "%~1"=="" (
  echo 用法: copy.bat [1^|2^|3^|help]
  exit /b 1
)
echo 1 第一次复制需要带上模型，文件
echo 2 只需要复制项目代码文件，并覆盖
echo 3 将copy好的文件打包7z
choice /C 123 /N /M "请选择:"
if errorlevel 3 goto mode3
if errorlevel 2 goto mode2
goto mode1

:help
echo 1. 第一次复制需要带上模型，文件
echo 2. 只需要复制项目代码文件，并覆盖
echo 3. 将copy好的文件打包7z
exit /b 0

:mode1
echo 复制项目文件，并带上模型
call :copy_tree 1
if errorlevel 1 exit /b 1
if not exist "%MODEL_SRC%\" (
  echo 模型目录不存在: %MODEL_SRC%
  exit /b 1
)
robocopy "%MODEL_SRC%" "%MODEL_DST%" /E
set "RC=%ERRORLEVEL%"
if %RC% GEQ 8 (
  echo 模型复制失败，代码 %RC%
  exit /b %RC%
)
echo 复制完成: %DEST%
exit /b 0

:mode2
echo 只覆盖项目代码，保留已有模型和音色
call :copy_tree 2
exit /b %ERRORLEVEL%

:copy_tree
if "%~1"=="1" (
  robocopy "%SRC%" "%DEST%" /E /XD .git .venv .pytest_cache __pycache__ run out /XF *.pyc
) else (
  robocopy "%SRC%" "%DEST%" /E /IS /IT /XD .git .venv .pytest_cache __pycache__ run out models voice /XF *.pyc
)
set "RC=%ERRORLEVEL%"
if %RC% GEQ 8 (
  echo 复制失败，代码 %RC%
  exit /b %RC%
)
if "%~1"=="2" echo 复制完成: %DEST%
exit /b 0

:mode3
if not exist "%DEST%\" (
  echo 目标目录不存在，请先运行 1 或 2
  exit /b 1
)
set "SEVEN="
if exist "D:\Program Files\7-Zip\7z.exe" set "SEVEN=D:\Program Files\7-Zip\7z.exe"
if not defined SEVEN if exist "C:\Program Files\7-Zip\7z.exe" set "SEVEN=C:\Program Files\7-Zip\7z.exe"
if not defined SEVEN if exist "C:\Program Files (x86)\7-Zip\7z.exe" set "SEVEN=C:\Program Files (x86)\7-Zip\7z.exe"
if not defined SEVEN (
  for /f "delims=" %%Z in ('where 7z 2^>nul') do (
    if not defined SEVEN set "SEVEN=%%Z"
  )
)
if not defined SEVEN (
  echo 未找到 7z.exe
  exit /b 1
)
if exist "%ARCHIVE%" del /f "%ARCHIVE%"
"%SEVEN%" a -t7z -mx=3 -y "%ARCHIVE%" "%DEST%"
if errorlevel 1 (
  echo 打包失败
  exit /b 1
)
echo 已打包: %ARCHIVE%
exit /b 0
