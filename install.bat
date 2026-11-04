@echo off
chcp 65001 > nul
echo [서무비서 AI] 설치를 시작합니다.
where python > nul 2>&1 || (echo Python 3.10 이상을 먼저 설치하세요: https://www.python.org/downloads/ & pause & exit /b 1)
python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
echo.
echo [안내] 로컬 AI 엔진(Ollama)을 설치한 뒤 모델을 받아 주세요:
echo     ollama pull gemma3:4b
echo     ollama pull bge-m3        (선택: 의미 검색 정확도 향상)
echo.
echo 설치 완료. run.bat 을 실행하세요.
pause
