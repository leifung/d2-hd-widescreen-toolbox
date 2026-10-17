@echo off
chcp 65001 >nul
title Diablo II HD - PlugY Launch
cd /d "%~dp0"
echo Starting Diablo II with D2DX HD widescreen + PlugY...
start "" "PlugY.exe" -3dfx
