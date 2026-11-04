@echo off
setlocal EnableDelayedExpansion
chcp 65001 > nul
cd /d "%~dp0"
echo [서무비서 AI] 설치를 시작합니다.
echo.
rem 패키지 호환성을 위해 Python 3.13 / 3.12를 우선 사용
set "PY="
py -V:3.13 --version > nul 2>&1 && set "PY=py -V:3.13"
if not defined PY py -V:3.12 --version > nul 2>&1 && set "PY=py -V:3.12"
if not defined PY py -3.13 --version > nul 2>&1 && set "PY=py -3.13"
if not defined PY py -3.12 --version > nul 2>&1 && set "PY=py -3.12"
if not defined PY where python > nul 2>&1 && set "PY=python"
if not defined PY (
  echo [오류] Python이 없습니다. https://www.python.org/downloads/ 에서 설치하세요.
  echo        ^(권장: 설치 후 명령 프롬프트에서  py install 3.13^)
  pause
  exit /b 1
)
echo 사용할 Python:
%PY% --version
if exist .venv\Scripts\python.exe (
  echo 기존 가상환경^(.venv^)을 사용합니다. 다시 만들려면 .venv 폴더를 지우고 실행하세요.
) else (
  %PY% -m venv .venv || (echo [오류] 가상환경을 만들지 못했습니다. & pause & exit /b 1)
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
rem 패키지를 하나씩 설치: 일부가 실패해도 프로그램은 실행됩니다
set "FAILED="
for %%P in (pypdf olefile openpyxl pywebview playwright) do (
  echo.
  echo [패키지] %%P 설치 중...
  python -m pip install "%%P" || set "FAILED=!FAILED! %%P"
)
echo.
if defined FAILED (
  echo [경고] 설치하지 못한 패키지:%FAILED%
  echo        - pywebview 실패: 프로그램이 기본 브라우저 창으로 열립니다.
  echo        - playwright 실패: 공문 '브라우저 연동' 수집만 사용할 수 없습니다.
  echo        모든 기능을 쓰려면 Python 3.13 설치 후 ^(py install 3.13^) .venv 폴더를 지우고 다시 실행하세요.
) else (
  echo [완료] 모든 패키지를 설치했습니다.
)
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
