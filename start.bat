@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal EnableDelayedExpansion
title 夜之主衣柜

set "PYTHONIOENCODING=utf-8"
set "VENV_DIR=tag_manager\.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "REQ_FILE=tag_manager\requirements.txt"
set "FIND_PY=tag_manager\find_python.py"
set "CAND_FILE=%TEMP%\night_wardrobe_py_candidates.txt"
set "DIAG_FILE=%TEMP%\night_wardrobe_py_diag.txt"
set "FAIL_LOG=%TEMP%\night_wardrobe_venv_fail.txt"

echo ============================================
echo   夜之主衣柜 - 启动
echo ============================================
echo.
echo [信息] 工作目录: %CD%
echo.

if not exist "tag_manager\run.py" (
    echo [错误] 未找到 tag_manager\run.py
    echo        请把本脚本放在仓库根目录后运行。
    pause
    exit /b 1
)
if not exist "%REQ_FILE%" (
    echo [错误] 未找到 %REQ_FILE%
    pause
    exit /b 1
)

if exist "%VENV_PY%" (
    echo [信息] 检测到虚拟环境: %VENV_DIR%
    "%VENV_PY%" -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 11) else 1)"
    if errorlevel 1 (
        echo [警告] 现有虚拟环境的 Python 低于 3.11，将删除并重建。
        rmdir /s /q "%VENV_DIR%" 2>nul
        if exist "%VENV_PY%" (
            echo [错误] 无法删除旧虚拟环境，请关闭占用该目录的程序后重试。
            pause
            exit /b 1
        )
        goto CREATE_VENV
    )
    goto CHECK_DEPS
)

goto CREATE_VENV

:CHECK_DEPS
"%VENV_PY%" -c "import av, cryptography, fastapi" >nul 2>&1
if errorlevel 1 (
    echo [信息] 依赖冒烟未通过，开始安装依赖。
    goto INSTALL_DEPS
)
"%VENV_PY%" -c "import hashlib,os,sys; h=hashlib.sha256(open(os.path.join('tag_manager','requirements.txt'),'rb').read()).hexdigest(); p=os.path.join('tag_manager','.venv','.deps-stamp'); sys.exit(0 if os.path.isfile(p) and open(p,'r').read().strip()==h else 1)"
if errorlevel 1 (
    echo [信息] 依赖清单已变化，开始安装依赖。
    goto INSTALL_DEPS
)
echo [信息] 依赖已是最新，跳过安装
goto LAUNCH

:INSTALL_DEPS
echo [信息] 正在安装依赖（首次或更新时可能需要几分钟）...
"%VENV_PY%" -m pip install -r "%REQ_FILE%"
if errorlevel 1 (
    echo [错误] 依赖安装失败。请检查网络连接或 %REQ_FILE%
    pause
    exit /b 1
)
"%VENV_PY%" -c "import av, cryptography, fastapi"
if errorlevel 1 (
    echo [错误] 依赖安装后仍无法导入 av / cryptography / fastapi
    pause
    exit /b 1
)
call :WRITE_STAMP
echo [信息] 依赖已就绪。
goto LAUNCH

:CREATE_VENV
if not exist "%FIND_PY%" (
    echo [错误] 未找到 %FIND_PY%，无法探测本机 Python。
    pause
    exit /b 1
)

echo [信息] 正在探测本机 Python 3.11+ 解释器...
set "FINDER_RAN=0"

py -3 "%FIND_PY%" >"%CAND_FILE%" 2>"%DIAG_FILE%"
call :MARK_FINDER
if "!FINDER_RAN!"=="1" goto AFTER_FIND

python "%FIND_PY%" >"%CAND_FILE%" 2>"%DIAG_FILE%"
call :MARK_FINDER
if "!FINDER_RAN!"=="1" goto AFTER_FIND

py "%FIND_PY%" >"%CAND_FILE%" 2>"%DIAG_FILE%"
call :MARK_FINDER
if "!FINDER_RAN!"=="1" goto AFTER_FIND

python3 "%FIND_PY%" >"%CAND_FILE%" 2>"%DIAG_FILE%"
call :MARK_FINDER
if "!FINDER_RAN!"=="1" goto AFTER_FIND

echo [错误] 无法运行 find_python.py（py / python / python3 均不可用）。
goto NO_PYTHON

:AFTER_FIND
set "HAS_CAND=0"
for /f "usebackq delims=" %%P in ("%CAND_FILE%") do set "HAS_CAND=1"
if "!HAS_CAND!"=="0" goto NO_PYTHON

echo.
echo -------- 探测诊断 --------
type "%DIAG_FILE%"
echo --------------------------
echo.

set "VENV_OK=0"
type nul >"%FAIL_LOG%"
for /f "usebackq delims=" %%P in ("%CAND_FILE%") do (
    call :TRY_VENV "%%P"
    if "!VENV_OK!"=="1" goto LAUNCH
)

echo [错误] 全部候选解释器均未能创建可用环境。
echo.
echo -------- 失败摘要 --------
if exist "%FAIL_LOG%" type "%FAIL_LOG%"
echo --------------------------
echo.
echo 常见原因：网络无法下载 pip 包、磁盘权限不足、文件被占用。
pause
exit /b 1

:NO_PYTHON
echo.
echo [错误] 未找到可用的 Python 3.11 或更高版本。
echo.
if exist "%DIAG_FILE%" (
    echo -------- 已探测解释器 --------
    type "%DIAG_FILE%"
    echo ------------------------------
    echo.
)
echo 请安装 Python 3.12 后重试：
echo   winget install -e --id Python.Python.3.12
echo.
echo 或从官网下载安装包：
echo   https://www.python.org/downloads/windows/
echo 安装时请勾选 Add python.exe to PATH。
echo.
echo 若本机已有 3.11+ 但仍无法识别，可设置环境变量
echo WARDROBE_PYTHON 指向 python.exe 的完整路径后重新运行。
echo.
pause
exit /b 1

:LAUNCH
echo.
echo [信息] 解释器: %VENV_PY%
if exist "%VENV_PY%" "%VENV_PY%" --version
echo [信息] 数据库: tag_manager\tag_wardrobe.sqlite3
if exist "tag_manager\tag_wardrobe.sqlite3" (
    echo [信息] 数据库文件已存在。
) else (
    echo [信息] 数据库文件不存在，将在首次运行时创建。
)
echo.
echo ============================================
echo   服务启动地址: http://127.0.0.1:8765
echo   按 Ctrl+C 可停止服务
echo ============================================
echo.
start "" http://127.0.0.1:8765
"%VENV_PY%" -m tag_manager.run
echo.
echo [信息] 服务已停止。
pause
exit /b 0

:TRY_VENV
set "CAND=%~1"
echo [信息] 尝试使用: %CAND%
if exist "%VENV_DIR%" rmdir /s /q "%VENV_DIR%" 2>nul
"%CAND%" -m venv "%VENV_DIR%"
if errorlevel 1 (
    echo [警告] 创建虚拟环境失败: %CAND%
    echo 创建虚拟环境失败: %CAND%>>"%FAIL_LOG%"
    if exist "%VENV_DIR%" rmdir /s /q "%VENV_DIR%" 2>nul
    goto :eof
)
if not exist "%VENV_PY%" (
    echo [警告] 虚拟环境未生成 python.exe: %CAND%
    echo 虚拟环境未生成 python.exe: %CAND%>>"%FAIL_LOG%"
    if exist "%VENV_DIR%" rmdir /s /q "%VENV_DIR%" 2>nul
    goto :eof
)
echo [信息] 正在安装依赖...
"%VENV_PY%" -m pip install -r "%REQ_FILE%"
if errorlevel 1 (
    echo [警告] 安装依赖失败: %CAND%
    echo 安装依赖失败: %CAND%>>"%FAIL_LOG%"
    rmdir /s /q "%VENV_DIR%" 2>nul
    goto :eof
)
"%VENV_PY%" -c "import av, cryptography, fastapi"
if errorlevel 1 (
    echo [警告] 依赖冒烟失败: %CAND%
    echo 依赖冒烟失败: %CAND%>>"%FAIL_LOG%"
    rmdir /s /q "%VENV_DIR%" 2>nul
    goto :eof
)
call :WRITE_STAMP
set "VENV_OK=1"
echo [信息] 虚拟环境已就绪。
goto :eof

:WRITE_STAMP
"%VENV_PY%" -c "import hashlib,os; h=hashlib.sha256(open(os.path.join('tag_manager','requirements.txt'),'rb').read()).hexdigest(); f=open(os.path.join('tag_manager','.venv','.deps-stamp'),'w'); f.write(h+chr(10)); f.close()"
goto :eof

:MARK_FINDER
set "FINDER_RAN=0"
if not exist "%DIAG_FILE%" goto :eof
findstr /c:"[find_python]" "%DIAG_FILE%" >nul 2>&1
if not errorlevel 1 set "FINDER_RAN=1"
goto :eof
