#!/usr/bin/env bash
set -e

ACTION="${1:-start}"

ROBOOS_ROOT="${ROBOOS_ROOT:-$HOME/qiao/code/RoboOS}"
ROS_SETUP="${ROS_SETUP:-/opt/ros/humble/setup.bash}"
TURTLEBOT3_WS_SETUP="${TURTLEBOT3_WS_SETUP:-$HOME/turtlebot3_ws/install/setup.bash}"
MAP_FILE="${MAP_FILE:-$HOME/map.yaml}"

VLLM_ENV="${VLLM_ENV:-vllm-fresh}"
ROBOOS_ENV="${ROBOOS_ENV:-RoboOS}"
TURTLEBOT3_MODEL="${TURTLEBOT3_MODEL:-burger}"

MODEL_PATH="${MODEL_PATH:-/home/rosos/qiao/code/RoboBrain2.5/models--BAAI--RoboBrain2.5-8B-NV/snapshots/3d77a19a3ddd8616b3979e03de56096edfb12ff6}"
MODEL_NAME="${MODEL_NAME:-RoboBrain2.5-8B-NV}"
CUDA_DEVICES="${CUDA_DEVICES:-0,1}"
VLLM_PORT="${VLLM_PORT:-4568}"

TASK="${TASK:-让小车拿苹果去服务台装盘后去顾客那上交}"
SEND_TASK="${SEND_TASK:-1}"

LOG_DIR="${LOG_DIR:-$ROBOOS_ROOT/logs/demo_$(date +%Y%m%d_%H%M%S)}"
PID_FILE="/tmp/roboos_demo_pids.txt"

mkdir -p "$LOG_DIR"

say() {
  printf "\033[1;36m%s\033[0m\n" "$*"
}

warn() {
  printf "\033[1;33m%s\033[0m\n" "$*"
}

fail() {
  printf "\033[1;31m%s\033[0m\n" "$*" >&2
  exit 1
}

conda_init_block='
if [ -f "$HOME/miniconda3/etc/profile.d/conda.sh" ]; then
  source "$HOME/miniconda3/etc/profile.d/conda.sh"
elif [ -f "$HOME/anaconda3/etc/profile.d/conda.sh" ]; then
  source "$HOME/anaconda3/etc/profile.d/conda.sh"
elif command -v conda >/dev/null 2>&1; then
  eval "$(conda shell.bash hook)"
fi
'

clean_old_processes() {
  say "[清理] 关闭旧 demo 进程"

  if [ -f "$PID_FILE" ]; then
    while read -r pid; do
      [ -n "$pid" ] && kill "$pid" >/dev/null 2>&1 || true
    done < "$PID_FILE"
    rm -f "$PID_FILE"
  fi

  pkill -f "vllm serve" >/dev/null 2>&1 || true
  pkill -f "turtlebot3_world.launch.py" >/dev/null 2>&1 || true
  pkill -f gzserver >/dev/null 2>&1 || true
  pkill -f gzclient >/dev/null 2>&1 || true
  pkill -f "navigation2.launch.py" >/dev/null 2>&1 || true
  pkill -f rviz2 >/dev/null 2>&1 || true
  pkill -f "demo_robot_remote/skill.py" >/dev/null 2>&1 || true
  pkill -f "python -s run.py" >/dev/null 2>&1 || true
  pkill -f "python run.py" >/dev/null 2>&1 || true

  sleep 2
}

run_bg() {
  local name="$1"
  local cmd="$2"
  local log="$LOG_DIR/${name}.log"

  say "[启动] $name"
  say "[日志] $log"

  bash -lc "$cmd" > "$log" 2>&1 &
  local pid=$!

  echo "$pid" >> "$PID_FILE"
  say "[PID] $name = $pid"
}

start_vllm() {
  run_bg "01_vllm" "
$conda_init_block
conda activate '$VLLM_ENV'

unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY no_proxy NO_PROXY
export PYTHONNOUSERSITE=1

unset LD_LIBRARY_PATH
export LD_LIBRARY_PATH=\"\$CONDA_PREFIX/lib\"
export LD_PRELOAD=\"\$CONDA_PREFIX/lib/libstdc++.so.6\"
export CUDA_VISIBLE_DEVICES='$CUDA_DEVICES'

cd '$ROBOOS_ROOT'

CUDA_VISIBLE_DEVICES='$CUDA_DEVICES' vllm serve \
  '$MODEL_PATH' \
  --served-model-name '$MODEL_NAME' \
  --tensor-parallel-size 2 \
  --port '$VLLM_PORT' \
  --trust-remote-code \
  --max-model-len 4096 \
  --max-num-seqs 8 \
  --gpu-memory-utilization 0.85 \
  --enable-auto-tool-choice \
  --tool-call-parser hermes
"
}

start_gazebo() {
  run_bg "02_gazebo" "
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY no_proxy NO_PROXY

source '$ROS_SETUP'
source '$TURTLEBOT3_WS_SETUP' 2>/dev/null || true
export TURTLEBOT3_MODEL='$TURTLEBOT3_MODEL'

cd '$ROBOOS_ROOT'

echo '[DISPLAY]' \$DISPLAY
echo '[检查] turtlebot3_gazebo'
ros2 pkg prefix turtlebot3_gazebo

echo '[启动] Gazebo'
ros2 launch turtlebot3_gazebo turtlebot3_world.launch.py x_pose:=2.0 y_pose:=1.0
"
}

start_nav2() {
  run_bg "03_nav2" "
$conda_init_block
conda activate '$ROBOOS_ENV'

unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY no_proxy NO_PROXY
export PYTHONNOUSERSITE=1

source '$ROS_SETUP'
source '$TURTLEBOT3_WS_SETUP' 2>/dev/null || true
export TURTLEBOT3_MODEL='$TURTLEBOT3_MODEL'

cd '$ROBOOS_ROOT'

echo '[地图] $MAP_FILE'
echo '[检查] turtlebot3_navigation2'
ros2 pkg prefix turtlebot3_navigation2

echo '[启动] Nav2'
ros2 launch turtlebot3_navigation2 navigation2.launch.py use_sim_time:=True map:='$MAP_FILE'
"
}

set_initialpose() {
  run_bg "05_initialpose" "
source '$ROS_SETUP'
source '$TURTLEBOT3_WS_SETUP' 2>/dev/null || true

cd '$ROBOOS_ROOT'

echo '[等待] 等 Nav2 稳定 5 秒'
sleep 10

echo '[发布] initialpose x=4.0 y=1.5'

ros2 topic pub --once /initialpose geometry_msgs/msg/PoseWithCovarianceStamped \
'{ header: {frame_id: \"map\"}, pose: { pose: { position: {x: 4.0, y: 1.5, z: 0.0}, orientation: {x: 0.0, y: 0.0, z: 0.0, w: 1.0} }, covariance: [0.25, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.25, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0685] } }'
"
}

start_skill_server() {
  run_bg "06_skill_server" "
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY no_proxy NO_PROXY

source '$ROS_SETUP'
source '$TURTLEBOT3_WS_SETUP' 2>/dev/null || true
export TURTLEBOT3_MODEL='$TURTLEBOT3_MODEL'

cd '$ROBOOS_ROOT'

/usr/bin/python3 slaver/demo_robot_remote/skill.py
"
}

start_redis() {
  if command -v redis-cli >/dev/null 2>&1 && redis-cli ping >/dev/null 2>&1; then
    say "[Redis] 已运行"
    return
  fi

  run_bg "07_redis" "
redis-server
"
}

start_master() {
  run_bg "08_master" "
$conda_init_block
conda activate '$ROBOOS_ENV'

unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY no_proxy NO_PROXY
export PYTHONNOUSERSITE=1

cd '$ROBOOS_ROOT/master'

python -s run.py
"
}

start_slaver() {
  run_bg "09_slaver" "
$conda_init_block
conda activate '$ROBOOS_ENV'

unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY no_proxy NO_PROXY
export PYTHONNOUSERSITE=1

cd '$ROBOOS_ROOT/slaver'

python -s run.py
"
}

send_task() {
  run_bg "10_send_task" "
echo '[等待] 等 master/slaver 稳定 8 秒'
sleep 8

echo '[发送任务] $TASK'

curl -X POST http://127.0.0.1:5000/publish_task \
  -H 'Content-Type: application/json' \
  -d '{\"task\":\"$TASK\",\"refresh\":false}'

echo
echo '[完成] curl 已发送'
"
}

start_all() {
  [ -d "$ROBOOS_ROOT" ] || fail "项目目录不存在：$ROBOOS_ROOT"

  say "[项目目录] $ROBOOS_ROOT"
  say "[日志目录] $LOG_DIR"

  : > "$PID_FILE"

  clean_old_processes

  start_vllm
  sleep 3

  start_gazebo
  sleep 8

  start_nav2
  sleep 8

  set_initialpose
  sleep 2

  start_skill_server
  sleep 3

  start_redis
  sleep 2

  start_master
  sleep 3

  start_slaver

  if [ "$SEND_TASK" = "1" ]; then
    sleep 3
    send_task
  else
    warn "[跳过] 不发送任务。SEND_TASK=0"
  fi

  say "[完成] 启动流程已执行"
  echo
  echo "日志目录：$LOG_DIR"
  echo
  echo "查看 Gazebo 日志："
  echo "  tail -n 80 $LOG_DIR/02_gazebo.log"
  echo
  echo "查看 RViz 日志："
  echo "  tail -n 80 $LOG_DIR/04_rviz.log"
  echo
  echo "停止："
  echo "  ./start_roboos_demo.sh stop"
}

case "$ACTION" in
  start)
    start_all
    ;;
  stop|clean)
    clean_old_processes
    say "[完成] 已清理 demo 相关进程"
    ;;
  logs)
    echo "$LOG_DIR"
    ls -lh "$LOG_DIR" || true
    ;;
  *)
    echo "Usage: $0 [start|stop|clean|logs]"
    exit 1
    ;;
esac
