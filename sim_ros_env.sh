unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
unset all_proxy ALL_PROXY no_proxy NO_PROXY
unset LD_PRELOAD
unset LD_LIBRARY_PATH

unset ROS_LOCALHOST_ONLY
unset ROS_DISCOVERY_SERVER
unset CYCLONEDDS_URI
unset FASTRTPS_DEFAULT_PROFILES_FILE

export ROS_DOMAIN_ID=0

source /opt/ros/humble/setup.bash
export TURTLEBOT3_MODEL=burger
