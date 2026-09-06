@echo off
call .venv\Scripts\activate.bat
echo [夜之主衣柜] 启动中... 浏览器打开 http://127.0.0.1:8765
python -m tag_manager.run
