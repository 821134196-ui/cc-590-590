#!/usr/bin/env bash
# 一条命令启动:安装依赖 -> 初始化种子数据 -> 启动服务(前后端一体)
set -e
cd "$(dirname "$0")"

PY=python3
PIP_FLAGS="--user"
# Debian/Ubuntu 的 PEP 668 环境需要该标记;旧版 pip 不支持时自动去掉
if $PY -m pip install --help 2>/dev/null | grep -q break-system-packages; then
  PIP_FLAGS="$PIP_FLAGS --break-system-packages"
fi

if ! $PY -c "import fastapi, sqlalchemy, uvicorn" 2>/dev/null; then
  echo "[start] 安装依赖..."
  $PY -m pip install $PIP_FLAGS -r requirements.txt
fi

echo "[start] 初始化数据库与演示数据..."
$PY -m backend.app.seed

echo "[start] 启动服务: http://127.0.0.1:8000  (API 文档: /docs)"
exec $PY -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
