@echo off
echo [夜之主衣柜] 正在创建虚拟环境...
python -m venv .venv
call .venv\Scripts\activate.bat
echo [夜之主衣柜] 正在安装依赖...
pip install -r requirements.txt -q
echo.
echo [夜之主衣柜] 安装完成！
echo 启动方式: start.bat
pause
