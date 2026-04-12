#!/bin/bash
# 克隆优必选天工行者 URDF 到项目 urdf/ 目录
REPO="https://github.com/x-humanoid-robomind/TienKung_URDF.git"
DEST="$(dirname "$0")/../urdf"
mkdir -p "$DEST"
cd "$DEST"
if [ -d .git ]; then
  git pull
else
  git clone "$REPO" .
fi
echo "URDF at: $DEST/lite/urdf/humanoid_publish.urdf"
echo "Optional: pro/, tiangong2pro-urdf/, tianyi2-urdf/"
