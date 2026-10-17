@echo off
rem ============================================================
rem  Diablo II HD widescreen launcher (D2DX + SGD2FreeRes)
rem  Keep this file in your Diablo II folder (next to Game.exe)
rem ============================================================
cd /d "%~dp0"
if not exist "Game.exe" (
    echo [ERROR] Game.exe was not found in this folder.
    echo Please copy this launcher into your Diablo II folder,
    echo i.e. the same folder that contains Game.exe.
    echo.
    pause
    exit /b 1
)
start "" "Game.exe" -3dfx
