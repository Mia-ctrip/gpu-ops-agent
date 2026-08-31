#!/bin/bash
# GPU Ops Agent 服务启动脚本
#
# ⚠️ 关键要点：
# 1. 必须用 --host 0.0.0.0 才能从外网访问（不是 localhost 或 127.0.0.1）
# 2. 不要用 --host 127.0.0.1，这样只能本机访问
# 3. 前后端服务都要这样配置

set -e

cd "$(dirname "$0")"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "GPU Ops Agent 服务启动"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 杀死旧进程
echo "清理旧进程..."
ps aux | grep -E "uvicorn|frontend_server" | grep -v grep | awk '{print $2}' | xargs kill -9 2>/dev/null || true
sleep 2

# 启动后端 (必须用 0.0.0.0)
echo "启动后端服务 (8030)..."
python3 -m uvicorn main:app --host 0.0.0.0 --port 8030 > /tmp/backend.log 2>&1 &
BACKEND_PID=$!
sleep 3

# 启动前端 (必须用 0.0.0.0)
echo "启动前端服务 (8035)..."
python3 -m uvicorn frontend_server:app --host 0.0.0.0 --port 8035 > /tmp/frontend.log 2>&1 &
FRONTEND_PID=$!
sleep 2

echo ""
echo "✅ 服务已启动"
echo ""
echo "后端进程 ID: $BACKEND_PID"
curl -s http://127.0.0.1:8030/health | python3 -m json.tool 2>/dev/null | head -3 || echo "  (后端启动中...)"
echo ""
echo "前端进程 ID: $FRONTEND_PID"
curl -s http://127.0.0.1:8035 | grep -o "GPU Ops" | head -1 && echo "  ✅ 前端已响应" || echo "  (前端启动中...)"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "访问地址："
echo "  🌐 http://port8035.ocp312proabscxpco-tr020002-0-svc.gps.cloud.ctripcorp.com"
echo "  💻 http://localhost:8035 (仅本机)"
echo ""
echo "后端 API (用于测试):"
echo "  http://port8030.ocp312proabscxpco-tr020002-0-svc.gps.cloud.ctripcorp.com/api/clusters"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
