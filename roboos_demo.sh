#!/usr/bin/env bash

API_URL="http://127.0.0.1:5000/publish_task"

DEFAULT_TASK="让小车拿苹果去服务台装盘后去顾客那上交"

# 支持两种方式：
# 1. ./roboos_demo.sh "让小车拿苹果去服务台装盘后去顾客那上交"
# 2. 直接 ./roboos_demo.sh，然后在终端输入任务
if [ -n "$1" ]; then
  USER_INPUT="$1"
else
  echo "请输入任务指令："
  read -r USER_INPUT
fi

if [ -z "$USER_INPUT" ]; then
  USER_INPUT="$DEFAULT_TASK"
fi

log() {
  echo "[$(date '+%H:%M:%S')] $1"
}

sleep 3

log "收到用户指令：${USER_INPUT}"
sleep 1

log "正在理解任务意图..."
sleep 1

log "识别到任务目标：拿取苹果、服务台装盘、交付顾客"
sleep 1

echo ""
log "系统任务分解："
echo "  1. 小车前往【苹果区】，拾取苹果"
sleep 1
echo "  2. 小车前往【服务台】，将苹果装盘"
sleep 1
echo "  3. 小车前往【顾客区】，把装好盘的苹果交给顾客"
sleep 1

echo ""
log "正在发布任务到 RoboOS..."
sleep 1

# 实际发送给后端的任务
PUBLISH_TASK="$USER_INPUT"

# 用 python3 生成 JSON，避免中文、引号等字符导致 JSON 格式错误
JSON_PAYLOAD=$(python3 -c '
import json
import sys

payload = {
    "task": sys.argv[1],
    "refresh": False
}

print(json.dumps(payload, ensure_ascii=False))
' "$PUBLISH_TASK")

echo ""
echo "执行命令："
echo "curl -X POST ${API_URL} \\"
echo "  -H \"Content-Type: application/json\" \\"
echo "  -d '${JSON_PAYLOAD}'"
echo ""

RESPONSE=$(curl -sS -X POST "${API_URL}" \
  -H "Content-Type: application/json" \
  -d "${JSON_PAYLOAD}")

CURL_EXIT_CODE=$?

echo ""
if [ ${CURL_EXIT_CODE} -eq 0 ]; then
  log "RoboOS 接口返回：${RESPONSE}"
  echo ""
  log "任务发布完成，小车开始执行。"
  log "执行路线：苹果区 -> 服务台 -> 顾客区"
else
  log "任务发布失败，请检查 RoboOS 服务是否已启动。"
fi
