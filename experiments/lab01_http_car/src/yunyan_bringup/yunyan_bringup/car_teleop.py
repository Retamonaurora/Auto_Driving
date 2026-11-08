"""
键盘遥操作节点：以固定频率持续发布 cmd_vel.

ros_http_bridge 有 0.5 秒的指令超时，所以不能只在按键时发一帧，
必须持续发布，否则小车会走走停停。
"""

import select
import sys
import termios
import threading
import tty

import rclpy
from geometry_msgs.msg import Twist
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node

# 键位 -> (线速度系数, 角速度系数)
KEY_BINDINGS = {
    'w': (1.0, 0.0),
    's': (-1.0, 0.0),
    'a': (0.0, 1.0),
    'd': (0.0, -1.0),
    ' ': (0.0, 0.0),
}

HELP = """
云衍小车键盘控制（线速度 {speed} m/s，角速度 {turn} rad/s，发布频率 {rate} Hz）
---------------------------
    w 前进      s 后退
    a 左转      d 右转
  空格 停止     q 退出
---------------------------
注意：本桥接不支持同时平移+转向（斜向），会按停止处理。
"""


class CarTeleop(Node):
    """把键盘输入翻译成持续发布的 cmd_vel 指令."""

    def __init__(self):
        """声明参数、创建发布者并启动按键读取线程."""
        super().__init__('car_teleop')
        self.declare_parameter('speed', 0.3)
        self.declare_parameter('turn', 0.5)
        self.declare_parameter('publish_rate', 10.0)

        self.speed = self.get_parameter('speed').value
        self.turn = self.get_parameter('turn').value
        self.publish_rate = self.get_parameter('publish_rate').value

        if self.speed <= 0.1:
            self.get_logger().warning(
                'speed 不大于 0.1，会被桥接节点的死区判定为停止。')

        self.publisher = self.create_publisher(Twist, 'cmd_vel', 10)

        self.command_lock = threading.Lock()
        self.command = (0.0, 0.0)
        self.quit_event = threading.Event()

        # 定时器保证匀速发布，不受按键节奏影响
        self.create_timer(1.0 / self.publish_rate, self.publish_cmd)

        self.key_thread = threading.Thread(target=self.read_keys, daemon=True)
        self.key_thread.start()

        print(HELP.format(
            speed=self.speed, turn=self.turn, rate=self.publish_rate))

    def publish_cmd(self):
        """按当前指令发布一帧 Twist（由定时器周期调用）."""
        with self.command_lock:
            linear_factor, angular_factor = self.command

        msg = Twist()
        msg.linear.x = linear_factor * self.speed
        msg.angular.z = angular_factor * self.turn
        self.publisher.publish(msg)

    def read_keys(self):
        """循环读取按键，直到收到 q 或退出信号."""
        if not sys.stdin.isatty():
            self.get_logger().warning(
                '标准输入不是终端，键盘控制不可用；请在前台终端里运行本节点。')
            return

        settings = termios.tcgetattr(sys.stdin)
        try:
            tty.setcbreak(sys.stdin.fileno())
            while not self.quit_event.is_set():
                ready, _, _ = select.select([sys.stdin], [], [], 0.1)
                if not ready:
                    continue

                key = sys.stdin.read(1)
                if key == 'q':
                    self.get_logger().info('收到退出指令，正在停止。')
                    self.set_command((0.0, 0.0))
                    self.quit_event.set()
                    break

                if key in KEY_BINDINGS:
                    self.set_command(KEY_BINDINGS[key])
        finally:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, settings)

    def set_command(self, command):
        """更新当前指令，变化时打印一行提示."""
        with self.command_lock:
            changed = command != self.command
            self.command = command

        if changed:
            names = {
                (1.0, 0.0): '前进',
                (-1.0, 0.0): '后退',
                (0.0, 1.0): '左转',
                (0.0, -1.0): '右转',
                (0.0, 0.0): '停止',
            }
            self.get_logger().info(f'切换为：{names.get(command, "未知")}')

    def wait_for_quit(self):
        """阻塞直到用户要求退出."""
        self.quit_event.wait()


def main(args=None):
    """启动节点并阻塞到用户退出."""
    rclpy.init(args=args)

    node = None

    try:
        node = CarTeleop()
        while rclpy.ok() and not node.quit_event.is_set():
            rclpy.spin_once(node, timeout_sec=0.1)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if node:
            # 显式补一帧停止，不等桥接节点的超时
            node.set_command((0.0, 0.0))
            node.publish_cmd()
            node.destroy_node()

        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
