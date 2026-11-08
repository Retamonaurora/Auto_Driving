import rclpy
from geometry_msgs.msg import Twist
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node


class CmdVelObserver(Node):
    def __init__(self):
        super().__init__('cmd_vel_observer')
        self.subscription = self.create_subscription(
            Twist,
            'cmd_vel',
            self.cmd_vel_callback,
            10)

        self.get_logger().info(
            'CmdVelObserver 节点已启动，正在监听 cmd_vel 话题。')

    def cmd_vel_callback(self, msg):
        linear_velocity = msg.linear.x
        angular_velocity = msg.angular.z
        self.get_logger().info(
            f'收到 cmd_vel：线速度={linear_velocity}，角速度={angular_velocity}')


def main(args=None):
    rclpy.init(args=args)

    node = CmdVelObserver()

    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()

        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
