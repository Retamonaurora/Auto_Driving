# Auto_Driving

ROS 2 + ESP32 的移动机器人（云衍小车）学习实验集。每个实验自包含：ROS 2 上位机包、
ESP32 固件、以及该实验的说明文档都放在 `experiments/<实验名>/` 下。

## 实验列表

| 实验 | 内容 | 状态 |
|---|---|---|
| [`lab01_http_car`](experiments/lab01_http_car/) | `cmd_vel` → HTTP 桥接 → 云衍小车；含键盘遥操作与 ESP32 固件 | ✅ 完成 |

## 目录结构

```
Auto_Driving/
└── experiments/
    └── lab01_http_car/            ← 一个实验 = 一个独立 colcon 工作空间
        ├── README.md
        ├── src/
        │   ├── control_learn/     # cmd_vel 订阅观察节点
        │   └── yunyan_bringup/    # HTTP 桥接节点 + 键盘遥操作 + launch
        └── firmware/
            ├── README.md
            └── yunyan_car/        # ESP32 固件（Arduino）
```

`build/` `install/` `log/` 都是 colcon 产物，按实验各自生成，不入库。

## 环境要求

- Ubuntu 22.04 + ROS 2 Humble（`source /opt/ros/humble/setup.bash`）
- Python 3.10
- Arduino IDE + ESP32 board package + [U8g2](https://github.com/olikraus/u8g2) 库（仅烧录固件需要）

## 快速开始

每个实验都是独立工作空间，**先进到实验目录再构建**：

```bash
cd ~/Auto_Driving/experiments/lab01_http_car
source /opt/ros/humble/setup.bash
colcon build --symlink-install
source install/setup.bash
```

之后按该实验 README 的步骤运行。

## 约定

- **每个实验独立工作空间**：互不干扰，换实验只换目录，不用清理旧 build。
- **凭据不入库**：Wi-Fi 密码等写进被 `.gitignore` 排除的本地文件，仓库只保留 `.example` 模板。
- **提交信息遵循 [Conventional Commits](https://www.conventionalcommits.org/)**：`feat:` / `fix:` / `docs:` / `chore:` …
- 分支：`main` 上只保留可运行状态，改动走 `feature/<名字>` 分支再合并。
