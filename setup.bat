@echo off
chcp 65001 >nul
title 自動化測試框架 - 環境初始化安裝 (setup.bat)

echo ========================================================
echo       AI 自動化測試框架 - 一鍵環境設定程式
echo ========================================================
echo.

:: 1. 檢查系統是否已安裝 Python
python --version >nul 2>&1
if errorlevel 1 goto NO_PYTHON

:: 2. 建立或檢查專屬虛擬環境 (.venv)
if exist ".venv\Scripts\python.exe" goto VENV_EXISTS

echo [步驟 1/3] 正在建立專屬獨立虛擬環境 .venv ...
python -m venv .venv
if errorlevel 1 goto VENV_FAIL
echo           虛擬環境建立成功！
goto UPGRADE_PIP

:VENV_EXISTS
echo [步驟 1/3] 專屬虛擬環境 .venv 已存在，略過建立步驟。

:UPGRADE_PIP
echo.
:: 3. 升級 pip 工具
echo [步驟 2/3] 檢查與更新 pip 工具...
.venv\Scripts\python.exe -m pip install --upgrade pip >nul 2>&1

:: 4. 安裝相依套件與註冊專案模組
echo.
echo [步驟 3/3] 正在安裝相依套件 requirements.txt 並註冊核心模組...
.venv\Scripts\pip.exe install -r requirements.txt
if errorlevel 1 goto REQ_WARN

:REGISTER_UTILS
echo           正在以可編輯模式註冊 utils 模組...
.venv\Scripts\pip.exe install -e . >nul 2>&1
goto SUCCESS

:REQ_WARN
echo [警告] 部分套件安裝可能未完全成功，請檢查網路連線。
goto REGISTER_UTILS

:SUCCESS
echo.
echo ========================================================
echo   [成功] 環境設定完成！
echo.
echo   執行測試方式 - 在命令提示字元或終端機中：
echo   .venv\Scripts\python.exe "example\...\your_script.py"
echo.
echo   或先啟動虛擬環境：
echo   call .venv\Scripts\activate
echo   python "example\...\your_script.py"
echo ========================================================
echo.
pause
exit /b 0

:NO_PYTHON
echo [錯誤] 找不到 Python！請先安裝 Python 並確認已勾選 Add Python to PATH。
echo.
pause
exit /b 1

:VENV_FAIL
echo [錯誤] 建立虛擬環境失敗，請確認 Python venv 模組是否正常。
echo.
pause
exit /b 1
