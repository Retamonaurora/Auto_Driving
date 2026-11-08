# 实验 01：用 ROS 2 控制云衍小车（cmd_vel → HTTP 桥接）

**目标**：让 ROS 2 里发布的一条 `cmd_vel` 消息，最终变成小车电机的真实转动。

云衍小车（ESP32）提供的是**离散 HTTP 接口**（`/forward`、`/back`、`/left`、`/right`、`/stop`），
没有 ROS 话题。本实验用一个桥接节点把连续的 `Twist` 消息"翻译"成这些 HTTP 请求。

## 数据流

```
        ┌──────────────────┐        ┌───────────────────┐        ┌──────────────┐
        │  car_teleop      │        │  ros_http_bridge  │  HTTP  │   ESP32      │
        │  （键盘，10 Hz）  │        │  （订阅 + 翻译）   │  10 Hz │   yunyan_car │
        │                  │        │                   │        │              │
  按键 →│ Twist → /cmd_vel ├───────►│ classify_command  ├───────►│ /forward     ├─► 电机
        └──────────────────┘        │  + 超时兜底        │  GET   │ /back /left  │
        ┌──────────────────┐        │  + HTTP 发送线程   │        │ /right /stop │
        │ ros2 topic pub   ├───────►│                   │        └──────────────┘
        │ （命令行调试）     │        └───────────────────┘               │
        └──────────────────┘                                            ▼
                                                                   OLED 显示当前状态
```

双向的两层超时兜底：

```
上位机：cmd_vel 停止 0.5 s  →  bridge 改发 /stop
车端  ：800 ms 没收到运动请求 →  固件看门狗任务强制停车
```

## 目录结构

```
lab01_http_car/
├── README.md                      ← 本文件
├── src/
│   ├── control_learn/
│   │   └── control_learn/cmd_vel_observer.py    # 只订阅、打印，用来确认话题通不通
│   └── yunyan_bringup/
│       ├── launch/car.launch.py                 # 启动桥接节点
│       └── yunyan_bringup/
│           ├── ros_http_bridge.py               # 核心：cmd_vel → HTTP
│           └── car_teleop.py                    # 键盘遥操作（10 Hz 持续发布）
└── firmware/
    ├── README.md                                # 固件接线/接口/安全说明
    └── yunyan_car/
        ├── yunyan_car.ino                       # ESP32 固件
        └── wifi_credentials.h.example            # 凭据模板
```

## 前置条件

1. 小车上电、连上同一个 Wi-Fi，OLED 上能看到 IPv4 地址（例如 `192.168.31.11`）。
2. 在电脑上确认能访问它：

```bash
curl --noproxy '*' --max-time 2 http://192.168.31.11/stop     # 期望返回 OK
```

> `--noproxy '*'` 不能省：桥接节点内部用 `ProxyHandler({})` 禁用了代理，
> 而你的 shell 可能配了 `http_proxy`，两边不一致会让人误判"车不通"。

## 快速开始

### 0. 构建

```bash
cd ~/Auto_Driving/experiments/lab01_http_car
source /opt/ros/humble/setup.bash
colcon build --symlink-install
source install/setup.bash
```

`--symlink-install` 的好处：改 Python 代码不用重新 build，直接重启节点就生效
（新增节点/改 `setup.py` 的 entry_points 例外，必须重新 build）。

### 1. 终端 1：启动桥接

```bash
ros2 launch yunyan_bringup car.launch.py car_ip:=192.168.31.11
```

期望输出：

```
[INFO] [ros_http_bridge]: ROS HTTP 桥接节点已启动，正在向 http://192.168.31.11/ 发送指令
[INFO] [ros_http_bridge]: 指令超时时间已设置为 0.5 秒
[INFO] [ros_http_bridge]: 指令切换：stop
```

### 2. 终端 2：键盘控制

```bash
ros2 run yunyan_bringup car_teleop
```

```
    w 前进      s 后退
    a 左转      d 右转
  空格 停止     q 退出
```

按下 `w` 后，**终端 1 会打印 `指令切换：forward`** —— 用这一行判断链路是否打通。

### 3. 可选：命令行直接压（不用键盘节点）

```bash
ros2 topic pub -r 10 /cmd_vel geometry_msgs/msg/Twist '{linear:  {x:  0.3}}'   # 前进
ros2 topic pub -r 10 /cmd_vel geometry_msgs/msg/Twist '{linear:  {x: -0.3}}'   # 后退
ros2 topic pub -r 10 /cmd_vel geometry_msgs/msg/Twist '{angular: {z:  0.5}}'   # 左转
ros2 topic pub -r 10 /cmd_vel geometry_msgs/msg/Twist '{angular: {z: -0.5}}'   # 右转
```

`-r 10` 必须保留。发布频率低于 2 Hz 时，大部分时间会落在 0.5 s 超时之外，
表现为"走一下停一下"（实测 10 Hz 有 92% 的周期在发 `forward`，1 Hz 只剩 38%）。

## 指令映射（`ros_http_bridge.classify_command`）

| `cmd_vel` 条件（`deadzone = 0.1`） | 发出的 HTTP 请求 |
|---|---|
| `linear.x > 0.1` | `GET /forward` |
| `linear.x < -0.1` | `GET /back` |
| `angular.z > 0.1` | `GET /left` |
| `angular.z < -0.1` | `GET /right` |
| 都 ≤ 0.1，或超时，或消息里有非有限值 | `GET /stop` |
| **`linear` 与 `angular` 同时超死区** | `GET /stop`（不支持边走边转） |
| `linear.y/z`、`angular.x/y` 非零 | `GET /stop`（车端不支持） |

注意：`linear.x` 只取**符号**，数值大小完全不参与判断 —— 发 `0.3` 和发 `0.9` 的结果一模一样。
原因见"已知限制"。

## 关键参数

| 参数 | 位置 | 默认值 | 含义 |
|---|---|---|---|
| `http_server_ip` | launch `car_ip:=` | `192.168.31.11` | 车端 IP |
| `command_timeout` | `ros_http_bridge` | 0.5 s | 超过此时长没收到 `cmd_vel` 就改发 `/stop` |
| `send_period` | `ros_http_bridge` | 0.1 s | HTTP 发送周期（10 Hz） |
| `http_timout` | `ros_http_bridge` | 0.25 s | 单次 HTTP 请求超时 |
| `deadzone` | `ros_http_bridge` | 0.1 | 判"动/不动"的死区 |
| `COMMAND_TIMEOUT_MS` | 固件 | 800 ms | 车端兜底停车时间 |
| `speed` / `turn` | `car_teleop` | 0.3 / 0.5 | 发布的 `linear.x` / `angular.z` 幅值 |

## 调试手段

```bash
# 1. 话题上有没有数据、频率对不对
ros2 topic hz /cmd_vel

# 2. 谁在订阅、谁在发布
ros2 topic info /cmd_vel -v

# 3. 看看消息内容
ros2 topic echo /cmd_vel

# 4. 只观察不控制，确认话题通了
ros2 run control_learn cmd_vel_observer

# 5. 绕过 ROS，直接验证车端
curl --noproxy '*' http://192.168.31.11/forward
```

## 故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| `Package 'yunyan_bringup' not found` | 没 source 本工作空间的 `install/setup.bash` | `source install/setup.bash`，或在 `~/.bashrc` 里加 |
| `ros2 node list` 有节点，但车一动不动、日志也不报错 | 桥接的 HTTP 发送线程已死（异常穿透导致静默退出） | 已修：`send_http_command` 同时捕获 `OSError`/`HTTPException`，线程另有 `try/except` 保活 |
| 按了键但终端 1 没有 `指令切换：xxx` | 发布端没发出来，或 topic 名不匹配 | `ros2 topic hz /cmd_vel`；确认发布到 `/cmd_vel` 而不是 `/cmd_vel_nav` |
| 有 `指令切换：forward` 但车不动 | 车端问题：Wi-Fi 掉线、供电、电机驱动 | 看 OLED 显示；`curl` 直接打 `/forward` 验证 |
| 车走走停停 | 发布频率太低（< 2 Hz）撞上 0.5 s 超时 | 用 `-r 10` 或 `car_teleop` |
| 发出的是 `stop`，但语义上应该转弯 | `linear` 与 `angular` 同时超死区 | 分开给：要么纯直行，要么纯转向 |
| `Ctrl-C` 时出现 `KeyboardInterrupt` / `exit code -2` | Ctrl-C 会发两次 SIGINT，第二次打断 `join()` | 已修：`close_bridge()` 限时轮询 + 吞掉打断，`main` 同时捕获 `ExternalShutdownException` |
| 偶发 `<urlopen error timed out>` | ESP32 是单客户端 WebServer，10 Hz 短连接偶有超时 | 已修：线程不会因此退出，会自动恢复；也可把 `send_period` 调到 0.15 与厂商网页节奏（150 ms）对齐 |
| 车机网页控制端和 ROS 控制互相打断 | ESP32 同时只服务一个连接 | 只用一种控制端 |

## 安全须知

- **软件保护不能替代硬件保护**。必须保留人工断电和硬件急停；MCU 整体卡死、供电故障、
  驱动故障都无法靠软件兜住。
- **首次测试请架空车轮**，确认方向映射正确（尤其左右转向）。
- 车速由固件固定且偏快，第一次跑留足场地余量，手放在电源开关旁。
- 退出时按 `q` 或 `Ctrl-C`，程序会显式补发一帧全零，车在 0.5 s 内停住。

## 已知限制

1. **无法从 ROS 侧调速**：车端固件 `applyMotionLocked()` 用 `digitalWrite(..., HIGH)`
   满占空比导通，没有 PWM，所以 `linear.x` 的数值被丢弃，只能表达方向。
   真正的调速要么改固件用 `ledcWrite`，要么在桥接里做"发 N 拍前进 + M 拍停止"的占空比
   （能用，但车会一顿一顿，且频繁启停对电机不友好）。
2. **不支持边走边转**：只有 5 条离散指令，没有弧度式的差速控制。
3. **单客户端**：ESP32 WebServer 同一时刻只服务一个连接。
4. **GPIO 12 是 strapping 引脚**（决定启动时 flash 电压），接电机驱动后上电瞬间电平会
   影响启动。烧录失败或偶尔启动不了优先怀疑这里。

## 可以继续做的

- 固件改用 `ledcSetup/ledcWrite`，加 `/speed?value=` 接口，桥接把 `|linear.x|` 映射成占空比
- 桥接增加 `advertise` 或 service，把车端状态（IP、当前动作）回报成 ROS 话题
- `car.launch.py` 里把 `car_teleop` 一起拉起来，一条命令完成启动
- 用 `ros2 bag record /cmd_vel` 录制操作序列，做回放测试
