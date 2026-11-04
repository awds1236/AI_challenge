@echo off
chcp 65001 > nul
if exist .venv\Scripts\pythonw.exe (
  start "" .venv\Scripts\pythonw.exe run.py
) else (
  start "" pythonw run.py
)
