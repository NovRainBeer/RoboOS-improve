按你目前的状态，主 demo 用基础运动最稳：
自然语言任务 → RoboOS → slaver → MCP skill → ROS2 → Gazebo 小车运动
先不要把“导航”当主 demo，除非你已经把 navigate_to_target 真接到 Nav2 了。
Demo 目标
演示两条命令：
让小车前进2秒，速度0.1米每秒
让小车后退1秒，速度0.1米每秒
0. 先确认你在改好的分支
cd ~/qiao/code/RoboOS
git branch
当前最好看到：
* demo-update
1. 清理旧进程
开一个新终端，执行：
pkill -f "vllm serve"
pkill -f "turtlebot3_world.launch.py"
pkill -f gzserver
pkill -f gzclient
pkill -f "navigation2.launch.py"
pkill -f "teleop_keyboard"
pkill -f "demo_robot_remote/skill.py"
pkill -f "python -s run.py"
pkill -f "python run.py"
sleep 2
2. 启动本地大模型
终端 1
conda activate vllm-fresh
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY no_proxy NO_PROXY
export PYTHONNOUSERSITE=1
unset LD_LIBRARY_PATH
export LD_LIBRARY_PATH="$CONDA_PREFIX/lib"
export LD_PRELOAD="$CONDA_PREFIX/lib/libstdc++.so.6"

CUDA_VISIBLE_DEVICES=0,1 vllm serve \
  /home/rosos/qiao/code/RoboBrain2.5/models--BAAI--RoboBrain2.5-8B-NV/snapshots/3d77a19a3ddd8616b3979e03de56096edfb12ff6 \
  --served-model-name RoboBrain2.5-8B-NV \
  --tensor-parallel-size 2 \
  --port 4568 \
  --trust-remote-code \
  --max-model-len 4096 \
  --max-num-seqs 8 \
  --gpu-memory-utilization 0.85 \
  --enable-auto-tool-choice \
  --tool-call-parser hermes
检查模型是否起来
新开一个小终端：
curl http://127.0.0.1:4568/v1/models
如果能看到 RoboBrain2.5-8B-NV，这一层就好了。
3. 启动 Gazebo
终端 2
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY no_proxy NO_PROXY
source /opt/ros/humble/setup.bash
export TURTLEBOT3_MODEL=burger
ros2 launch turtlebot3_gazebo turtlebot3_world.launch.py x_pose:=2.0 y_pose:=1.0

4. 启动 Nav2
conda activate RoboOS
source /opt/ros/humble/setup.bash
export TURTLEBOT3_MODEL=burger
ros2 launch turtlebot3_navigation2 navigation2.launch.py use_sim_time:=True map:=$HOME/map.yaml

5. 设定初始点，告诉地图初始点在哪里
source /opt/ros/humble/setup.bash
ros2 topic pub --once /initialpose geometry_msgs/msg/PoseWithCovarianceStamped \
'{
  header: {frame_id: "map"},
  pose: {
    pose: {
      position: {x: 2.0, y: 1.0, z: 0.0},
      orientation: {x: 0.0, y: 0.0, z: 0.0, w: 1.0}
    },
    covariance: [0.25, 0.0, 0.0, 0.0, 0.0, 0.0,
                 0.0, 0.25, 0.0, 0.0, 0.0, 0.0,
                 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                 0.0, 0.0, 0.0, 0.0, 0.0, 0.0685]
  }
}'

6. 启动 skill server
终端 3
cd ~/qiao/code/RoboOS
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY no_proxy NO_PROXY
source /opt/ros/humble/setup.bash
export TURTLEBOT3_MODEL=burger
/usr/bin/python3 slaver/demo_robot_remote/skill.py
你应该能看到类似：
Uvicorn running on http://0.0.0.0:8000
7. 确认 Redis
终端 4
redis-cli ping
如果返回：
PONG
就继续。
如果没开，再执行：
redis-server
8. 启动 master
终端 5
conda activate RoboOS
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY no_proxy NO_PROXY
export PYTHONNOUSERSITE=1
cd ~/qiao/code/RoboOS/master
python -s run.py
正常会看到：
Running on http://127.0.0.1:5000
9. 启动 slaver
终端 6
conda activate RoboOS
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY no_proxy NO_PROXY
export PYTHONNOUSERSITE=1
cd ~/qiao/code/RoboOS/slaver
python -s run.py
正常你会看到：
connecting to robot...
Connected to robot with tools: ...
connection success
并且 tools 里应该能看到 move_linear。
10. 先做一次自检
发一条最稳的测试命令。
前进测试
curl -X POST http://127.0.0.1:5000/publish_task \
  -H "Content-Type: application/json" \
  -d '{"task":"让小车前进2秒，速度0.1米每秒","refresh":false}'
正常现象
你会看到：
master 终端
出现任务接收、分解、下发日志。
slaver 终端
出现类似：
Calling tool: 'move_linear' with arguments: {"direction": "forward", "duration": 2.0, "speed": 0.1}
Observations: Move forward success, duration=2.0, speed=0.1
Gazebo
小车前进。
11. 正式演示命令
演示 1：前进
curl -X POST http://127.0.0.1:5000/publish_task \
  -H "Content-Type: application/json" \
  -d '{"task":"让小车前进2秒，速度0.1米每秒","refresh":false}'
演示 2：后退
curl -X POST http://127.0.0.1:5000/publish_task \
  -H "Content-Type: application/json" \
  -d '{"task":"让小车后退1秒，速度0.1米每秒","refresh":false}'
12. 演示时屏幕怎么摆
建议只展示 3 个画面：
Gazebo
master 终端
slaver 终端
这样客户能直观看到：
任务输入了
RoboOS 在处理
tool 被调用了
小车真的动了

13. 演示时怎么讲
你可以直接这样讲：
“现在输入的是自然语言任务，而不是底层控制指令。
RoboOS 接收到任务后，会把任务转成机器人可执行的动作。
然后 slaver 调用 MCP skill，skill 通过 ROS2 去控制 Gazebo 中的小车执行。
所以最终看到的是从自然语言到机器人动作执行的完整链路。”
14. 备用方案
如果现场前后运动链路临时有问题，你立刻切到这个备用方案：
只演示 Gazebo + teleop
开一个新终端：
source /opt/ros/humble/setup.bash
export TURTLEBOT3_MODEL=burger
ros2 run turtlebot3_teleop teleop_keyboard
然后手动让小车动。
口播改成：
“当前已经验证 Gazebo 小车和 ROS2 控制链路正常，RoboOS 侧的任务调用链已经打通，正在继续往更高层任务扩展。”
15. 不建议你现在主讲导航
除非你已经把 navigate_to_target 真接到 Nav2。
如果你现在这版还是 mock，就不要把导航当主 demo，不然客户会问“为什么车没真正导航”。
16. 演示前最后 1 分钟检查
只检查这 4 条：
curl http://127.0.0.1:4568/v1/models
redis-cli ping
ss -ltnp | grep 5000
ss -ltnp | grep 8000
都正常就能演示。
最后一版最短流程
如果你要一眼记住，就记这个顺序：
1. vLLM
2. Gazebo
3. skill server
4. Redis
5. master
6. slaver
7. curl 发任务


- 没有GUI，看odom
source /opt/ros/humble/setup.bash
ros2 topic echo /odom
ros2 topic echo /cmd_vel

- 测试
curl -X POST http://127.0.0.1:5000/publish_task -H "Content-Type: application/json" -d '{"task":"获取当前机器人状态","refresh":false}'

curl -X POST http://127.0.0.1:5000/publish_task -H "Content-Type: application/json" -d '{"task":"让小车前进1秒，速度0.1米每秒","refresh":false}'

curl -X POST http://127.0.0.1:5000/publish_task -H "Content-Type: application/json" -d '{"task":"让小车后退1秒，速度0.1米每秒","refresh":false}'

curl -X POST http://127.0.0.1:5000/publish_task -H "Content-Type: application/json" -d '{"task":"让小车左转1秒，角速度0.5弧度每秒","refresh":false}'

curl -X POST http://127.0.0.1:5000/publish_task -H "Content-Type: application/json" -d '{"task":"让小车右转1秒，角速度0.5弧度每秒","refresh":false}'

curl -X POST http://127.0.0.1:5000/publish_task -H "Content-Type: application/json" -d '{"task":"立即停止小车","refresh":false}'

curl -X POST http://127.0.0.1:5000/publish_task -H "Content-Type: application/json" -d '{"task":"让小车去 kitchen","refresh":false}'
