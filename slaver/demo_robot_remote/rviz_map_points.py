#!/usr/bin/env python3

import math
import os
import yaml

import rclpy
from rclpy.node import Node
from visualization_msgs.msg import Marker, MarkerArray


class RvizMapPoints(Node):
    def __init__(self):
        super().__init__("rviz_map_points")

        self.declare_parameter("config_file", "config.yaml")
        self.declare_parameter("frame_id", "map")
        self.declare_parameter("topic_name", "/map_points")

        config_file = self.get_parameter("config_file").value
        self.frame_id = self.get_parameter("frame_id").value
        topic_name = self.get_parameter("topic_name").value

        if not os.path.isabs(config_file):
            current_dir = os.path.dirname(os.path.abspath(__file__))
            config_file = os.path.join(current_dir, config_file)

        self.points = self.load_points(config_file)

        self.pub = self.create_publisher(MarkerArray, topic_name, 10)
        self.timer = self.create_timer(0.5, self.publish_markers)

        self.get_logger().info(f"publish rviz map points to {topic_name}")
        self.get_logger().info(f"frame_id = {self.frame_id}")

    def load_points(self, config_file):
        with open(config_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data:
            self.get_logger().warn("config is empty")
            return {}

        if "map_points" in data:
            points = data["map_points"]
        else:
            points = data

        valid_points = {}
        for name, value in points.items():
            if not isinstance(value, dict):
                continue
            if "x" not in value or "y" not in value:
                continue
            valid_points[name] = value

        self.get_logger().info(f"loaded {len(valid_points)} map points from {config_file}")
        return valid_points

    def make_sphere(self, name, point, marker_id):
        marker = Marker()
        marker.header.frame_id = self.frame_id
        marker.header.stamp = self.get_clock().now().to_msg()

        marker.ns = "map_points_sphere"
        marker.id = marker_id
        marker.type = Marker.SPHERE
        marker.action = Marker.ADD

        marker.pose.position.x = float(point["x"])
        marker.pose.position.y = float(point["y"])
        marker.pose.position.z = 0.08
        marker.pose.orientation.w = 1.0

        marker.scale.x = 0.28
        marker.scale.y = 0.28
        marker.scale.z = 0.28

        marker.color.r = 1.0
        marker.color.g = 0.0
        marker.color.b = 0.0
        marker.color.a = 1.0

        marker.lifetime.sec = 0
        return marker

    def make_text(self, name, point, marker_id):
        marker = Marker()
        marker.header.frame_id = self.frame_id
        marker.header.stamp = self.get_clock().now().to_msg()

        marker.ns = "map_points_text"
        marker.id = marker_id
        marker.type = Marker.TEXT_VIEW_FACING
        marker.action = Marker.ADD

        marker.pose.position.x = float(point["x"])
        marker.pose.position.y = float(point["y"])
        marker.pose.position.z = 0.45
        marker.pose.orientation.w = 1.0

        marker.scale.z = 0.28

        marker.color.r = 1.0
        marker.color.g = 1.0
        marker.color.b = 1.0
        marker.color.a = 1.0

        marker.text = name
        marker.lifetime.sec = 0
        return marker

    def make_arrow(self, name, point, marker_id):
        yaw = float(point.get("yaw", 0.0))

        marker = Marker()
        marker.header.frame_id = self.frame_id
        marker.header.stamp = self.get_clock().now().to_msg()

        marker.ns = "map_points_arrow"
        marker.id = marker_id
        marker.type = Marker.ARROW
        marker.action = Marker.ADD

        marker.pose.position.x = float(point["x"])
        marker.pose.position.y = float(point["y"])
        marker.pose.position.z = 0.18

        marker.pose.orientation.z = math.sin(yaw / 2.0)
        marker.pose.orientation.w = math.cos(yaw / 2.0)

        marker.scale.x = 0.45
        marker.scale.y = 0.08
        marker.scale.z = 0.08

        marker.color.r = 0.0
        marker.color.g = 1.0
        marker.color.b = 0.0
        marker.color.a = 1.0

        marker.lifetime.sec = 0
        return marker

    def publish_markers(self):
        array = MarkerArray()

        marker_id = 0
        for name, point in self.points.items():
            array.markers.append(self.make_sphere(name, point, marker_id))
            marker_id += 1

            array.markers.append(self.make_text(name, point, marker_id))
            marker_id += 1

            array.markers.append(self.make_arrow(name, point, marker_id))
            marker_id += 1

        self.pub.publish(array)


def main():
    rclpy.init()
    node = RvizMapPoints()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
