import http.client
import ipaddress
import math
import threading
import time
import urllib.error
import urllib.request
import rclpy
from geometry_msgs.msg import Twist
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node


class RosHttpBridge(Node):
    def __init__(self):
        super().__init__('ros_http_bridge')
        # 启动时指定小车ip地址
        self.declare_parameter('http_server_ip', '192.168.31.11')

        self.car_ip = self.get_parameter('http_server_ip').value

        # 检查ip地址是否有效
        try:
            address = ipaddress.ip_address(self.car_ip)

            if address.version != 4:
                self.get_logger().error(f'IP 地址无效：{self.car_ip}')
                raise ValueError(f'Invalid IP address: {self.car_ip}')

        except ValueError as exc:
            raise ValueError(
                f'Invalid IP address: {self.car_ip}'
            ) from exc

        invalid_address = (
            address.is_unspecified
            or address.is_loopback
            or address.is_multicast
        )
        if invalid_address:
            self.get_logger().error(f'IP 地址无效：{self.car_ip}')
            raise ValueError(f'Invalid IP address: {self.car_ip}')

        self.base_url = f'http://{self.car_ip}/'

        # 创建一个锁对象，用于保护对命令的访问
        self.command_lock = threading.Lock()

        self.latest_command = 'stop'  # 初始化为停止命令
        self.last_command_time = None
        self.command_timeout = 0.5  # 设置命令超时时间为0.5秒

        self.send_period = 0.1  # 设置发送周期为0.1秒
        self.http_timout = 0.25  # 设置HTTP请求超时时间为0.25秒

        # 创建一个HTTP请求的opener对象，禁用代理
        self.http_opner = urllib.request.build_opener(
            urllib.request.ProxyHandler({})
        )

        self.stop_event = threading.Event()

        self.cmd_vel_subscription = self.create_subscription(
            Twist,
            'cmd_vel',
            self.cmd_vel_callback,
            10
        )

        self.http_thread = threading.Thread(
            target=self.http_loop,
            daemon=True
        )

        self.http_thread.start()

        self.get_logger().info(f'ROS HTTP 桥接节点已启动，正在向 {self.base_url} 发送指令')
        self.get_logger().info(f'指令超时时间已设置为 {self.command_timeout} 秒')

    def classify_command(self, msg):
        values = (
            msg.linear.x,
            msg.linear.y,
            msg.linear.z,
            msg.angular.x,
            msg.angular.y,
            msg.angular.z
        )

        if not all(math.isfinite(v) for v in values):
            return 'stop'

        linear_x = msg.linear.x
        angular_z = msg.angular.z

        deadzone = 0.1  # 设置死区阈值

        unsupported_values = [
            msg.linear.y,
            msg.linear.z,
            msg.angular.x,
            msg.angular.y
        ]

        if any(abs(v) > deadzone for v in unsupported_values):
            return 'stop'

        has_linear = abs(linear_x) > deadzone
        has_angular = abs(angular_z) > deadzone

        if has_linear and has_angular:
            return 'stop'

        if linear_x > deadzone:
            return 'forward'

        if linear_x < -deadzone:
            return 'back'

        if angular_z > deadzone:
            return 'left'

        if angular_z < -deadzone:
            return 'right'

        return 'stop'

    def cmd_vel_callback(self, msg):
        command = self.classify_command(msg)

        with self.command_lock:
            self.latest_command = command
            self.last_command_time = time.time()

    def get_current_command(self):
        with self.command_lock:
            if self.last_command_time is None:
                return 'stop'

            elapsed_time = time.time() - self.last_command_time
            if elapsed_time > self.command_timeout:
                return 'stop'

            return self.latest_command

    def send_http_command(self, command):
        url = self.base_url + command
        try:
            with self.http_opner.open(
                url,
                timeout=self.http_timout
            ) as response:
                if response.status != 200:
                    self.get_logger().error(
                        f'HTTP 请求失败，状态码：{response.status}')
                    return False
        except (urllib.error.URLError, OSError) as e:
            # socket.timeout(TimeoutError)/RemoteDisconnected/ConnectionResetError
            # 在读取响应阶段抛出，不会被 urllib 包成 URLError，必须一并捕获
            self.get_logger().error(
                f'HTTP 请求失败：{e}', throttle_duration_sec=1.0)
            return False
        except http.client.HTTPException as e:
            self.get_logger().error(
                f'HTTP 协议异常：{e}', throttle_duration_sec=1.0)
            return False

        return True

    def http_loop(self):
        previous_failed = None
        previous_command = None
        while not self.stop_event.is_set():
            start_time = time.monotonic()

            # 任何未预料的异常都不能终止这个线程，否则节点看似正常却不再发指令
            try:
                command = self.get_current_command()

                if command != previous_command:
                    self.get_logger().info(f'指令切换：{command}')
                    previous_command = command

                success = self.send_http_command(command)
            except Exception as exc:  # noqa: BLE001 - 线程保活优先
                self.get_logger().error(f'HTTP 发送线程异常：{exc}')
                command = 'stop'
                success = False

            failed = not success

            if failed and previous_failed is not True:
                self.get_logger().warning(
                    f'向 {self.base_url} 发送指令“{command}”失败')

            if success and previous_failed is True:
                self.get_logger().info(
                    f'已成功向 {self.base_url} 发送指令“{command}”')

            previous_failed = failed

            elapsed = time.monotonic() - start_time
            wait_time = max(0, self.send_period - elapsed)

            self.stop_event.wait(wait_time)

        self.send_http_command('stop')

    def close_bridge(self):
        self.stop_event.set()

        # Ctrl-C 时终端和 ros2 launch 会各发一次 SIGINT，第二次会打断 join()
        # 并抛 KeyboardInterrupt，所以限时轮询并在被打断时继续等
        deadline = time.monotonic() + self.http_timout + self.send_period + 1.0
        while self.http_thread.is_alive() and time.monotonic() < deadline:
            try:
                self.http_thread.join(timeout=0.05)
            except KeyboardInterrupt:
                continue

        if self.http_thread.is_alive():
            self.get_logger().warning(
                'HTTP 发送线程未能在超时前退出，已放弃等待。')
        else:
            self.get_logger().info('ROS HTTP 桥接节点已停止。')


def main(args=None):
    rclpy.init(args=args)

    node = None

    try:
        node = RosHttpBridge()
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if node:
            node.close_bridge()
            node.destroy_node()

        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
