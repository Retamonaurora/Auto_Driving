from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    car_ip_argument = DeclareLaunchArgument(
        'car_ip',
        description='ESP32 小车 OLED 上显示的 IPv4 地址',
    )

    bridge_node = Node(
        package='yunyan_bringup',
        executable='ros_http_bridge',
        name='ros_http_bridge',
        output='screen',
        parameters=[
            {
                'http_server_ip': ParameterValue(
                    LaunchConfiguration('car_ip'),
                    value_type=str
                )
            }
        ]
    )

    return LaunchDescription([
        car_ip_argument,
        bridge_node,
    ])
