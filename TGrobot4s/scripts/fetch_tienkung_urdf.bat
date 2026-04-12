@echo off
REM 克隆优必选天工行者 URDF 到项目 urdf/ 目录
set REPO=https://github.com/x-humanoid-robomind/TienKung_URDF.git
set DEST=%~dp0..\urdf
if not exist "%DEST%" mkdir "%DEST%"
cd /d "%DEST%"
if exist ".git" (
  git pull
) else (
  git clone %REPO% .
)
echo URDF at: %DEST%\lite\urdf\humanoid_publish.urdf
echo Optional: pro\, tiangong2pro-urdf\, tianyi2-urdf\
