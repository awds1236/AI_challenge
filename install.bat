@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo [서무비서 AI] 설치를 시작합니다.
echo.
where python > nul 2>&1 || (echo [오류] Python 3.10 이상을 먼저 설치하세요: https://www.python.org/downloads/  ^(설치 시 "Add python.exe to PATH" 체크^) & pause & exit /b 1)
python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
echo.
where ollama > nul 2>&1
if errorlevel 1 (
  echo [안내] 로컬 AI 엔진^(Ollama^)이 설치되어 있지 않습니다.
  echo        https://ollama.com/download/windows 에서 설치한 뒤 이 파일을 다시 실행하세요.
  start "" https://ollama.com/download/windows
  pause
  exit /b 0
)
echo [AI 모델] 기본 모델 Gemma 4 E2B ^(QAT 경량판, 약 4.3GB^)를 내려받습니다.
ollama pull gemma4:e2b-it-qat
echo [AI 모델] 검색 보조 모델 EmbeddingGemma ^(약 0.6GB^)를 내려받습니다.
ollama pull embeddinggemma
echo.
echo 설치 완료. run.bat 을 실행하세요.
pause
