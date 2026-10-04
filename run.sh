#!/usr/bin/env bash
# 一条本地命令启动：企业招聘背调授权与结果封存系统
# 用法：./run.sh        启动服务（默认 http://0.0.0.0:8000）
#       ./run.sh test   仅运行后端测试
set -e
cd "$(dirname "$0")"
ROOT="$(pwd)"

export PYTHONPATH="$ROOT/backend"
PORT="${PORT:-8000}"

# 1) 依赖自检（首次运行自动安装到用户目录）
if ! python3 -c "import fastapi, sqlalchemy, uvicorn" 2>/dev/null; then
  echo "[run.sh] 首次运行，安装 Python 依赖……"
  python3 -m pip install --user --break-system-packages -r "$ROOT/backend/requirements.txt"
fi

# 2) 前端运行时本地化（无网络环境也可打开页面）
VUE="$ROOT/frontend/vendor/vue.global.prod.js"
if [ ! -s "$VUE" ]; then
  mkdir -p "$(dirname "$VUE")"
  curl -fsSL https://unpkg.com/vue@3/dist/vue.global.prod.js -o "$VUE" \
    && sed -i 's#https://unpkg.com/vue@3/dist/vue.global.prod.js#vendor/vue.global.prod.js#' "$ROOT/frontend/index.html" \
    || echo "[run.sh] 警告：Vue 本地下载失败，将使用 CDN（需浏览器可访问网络）"
fi

if [ "${1:-}" = "test" ]; then
  python3 -m pytest "$ROOT/backend/tests" -q
  exit $?
fi

# 3) 启动（FastAPI 同时托管前端静态页与 /api）
echo "[run.sh] 服务已启动： http://localhost:$PORT"
exec python3 -m uvicorn app.main:app --app-dir "$ROOT/backend" --host 0.0.0.0 --port "$PORT"
