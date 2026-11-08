# 云衍小车车端固件（ESP32）

ESP32 侧固件：开一个 HTTP 服务，用离散路径控制电机方向，并带一个独立任务的软件超时停车。
ROS 2 侧的上位机在 [`src/yunyan_bringup`](../src/yunyan_bringup)，由 `ros_http_bridge`
把 `cmd_vel` 翻译成本固件认识的 HTTP 请求。

## 首次配置

Wi-Fi 凭据**不入库**，需要本地生成：

```bash
cd firmware/yunyan_car
cp wifi_credentials.h.example wifi_credentials.h
# 然后编辑 wifi_credentials.h，填入你的 SSID / 密码
```

`wifi_credentials.h` 已被 `.gitignore` 排除；仓库里只有 `.example` 模板。

## 编译烧录

Arduino IDE：

- 开发板：`ESP32 Dev Module`
- 库：`U8g2`（olikraus）
- 打开 `yunyan_car.ino` 直接烧录

## 接线

| 功能 | GPIO |
|---|---|
| 电机 A（INA1 / INA2） | 12 / 13 |
| 电机 B（INB1 / INB2） | 14 / 21 |
| OLED I2C（SCL / SDA） | 42 / 41 |

> GPIO 12 是 ESP32 的 strapping 引脚（启动时决定 flash 电压），外接电机驱动时
> 上电瞬间的电平会影响正常启动。烧录失败或启动异常时优先怀疑这里。

## HTTP 接口

| 路径 | 动作 | 备注 |
|---|---|---|
| `GET /` | 返回触屏网页控制页 | |
| `GET /forward` | 前进 | |
| `GET /back` | 后退 | |
| `GET /left` | 左转 | |
| `GET /right` | 右转 | |
| `GET /stop` | 立即停止 | 不刷新运动期限 |

返回 `200 OK`；Wi-Fi 断开时运动请求返回 `503 WIFI_DISCONNECTED`，抢不到锁返回 `503 BUSY`。

## 安全设计

- **车端超时**：`COMMAND_TIMEOUT_MS = 800`，超过 800 ms 没收到运动请求就自动停车。
  上位机 `ros_http_bridge` 的 `command_timeout` 是 0.5 s，比它更早介入，800 ms 是兜底。
- **独立看门狗任务**：超时判断放在单独的 FreeRTOS 任务里，避免 HTTP/OLED 主循环卡住就
  完全失去保护能力。
- **互斥锁**：HTTP 处理与看门狗任务通过 `motorMutex` 串行化，避免方向切换被撕裂。
- 软件保护**不能替代**人工断电、硬件急停和安全电路；MCU 整体卡死、供电故障、驱动故障
  都无法靠软件兜住。首次测试请架空车轮。

## 已知限制

- **车速不可通过 HTTP 调整**：`applyMotionLocked()` 用的是 `digitalWrite(..., HIGH)`，
  满占空比直接导通，没有 PWM。所以上位机改 `linear.x` 的大小对车速没有影响，
  `ros_http_bridge` 也只用符号判方向。要真正调速需要改用 `ledcSetup/ledcWrite`。
- **不能边走边转**：只支持纯直行或纯原地转向，上位机的 `classify_command()`
  在 `linear` 与 `angular` 同时超死区时会判为停止。
- **单客户端**：ESP32 的 `WebServer` 同一时刻只服务一个连接，网页控制端和 ROS 上位机
  不要同时使用。
