# x2_face_ros2_system — Architecture Report

> 灵犀 X2 售楼迎宾机器人 · 商业部署版本  
> 单机 ROS2 架构 · 事件驱动中间件

---

## 1. 当前目录结构

```
x2_face_project2/
├── README.md
├── ARCHITECTURE_REPORT.md
├── robot_system/                         # 核心业务（单机可运行）
│   ├── main.py                           # 入口
│   ├── config.py                         # 全局配置（含 DEMO_MODE）
│   ├── requirements.txt
│   ├── adapters/                         # 【新增】硬件 / ROS2 适配层
│   │   ├── robot_sdk_adapter.py          # 灵犀 X2 SDK 统一接口（Mock）
│   │   └── ros2_adapter.py               # ROS2 Humble 预留接口（Stub）
│   ├── face_core/                        # 【新增】人脸数据访问层
│   │   └── repository.py                 # CRUD + VIP，Brain 禁止直连 FaceDB
│   ├── policy/                           # 【新增】业务策略
│   │   └── welcome_policy.py             # VIP / 普通 / 陌生欢迎语
│   ├── core/
│   │   ├── brain.py                      # RobotBrain（已拆分 handler）
│   │   ├── health_monitor.py             # 【新增】线程健康监控
│   │   ├── state_machine.py              # FSM（IDLE/GREETING/COOLDOWN 等，未改流转）
│   │   ├── event_bus.py
│   │   ├── event_router.py
│   │   ├── policy_layer.py
│   │   ├── command_emitter.py
│   │   └── ...
│   ├── behavior/
│   │   ├── action_executor.py            # 动作执行 → RobotSDKAdapter
│   │   ├── greeting_policy.py            # 迎宾流程（调用 WelcomePolicy）
│   │   ├── dialog_policy.py
│   │   ├── nav_policy.py
│   │   └── gesture.py
│   ├── vision/
│   │   ├── face_db.py                    # 底层存储（Repository 封装）
│   │   ├── face_engine.py
│   │   └── recognition_service.py        # 经 FaceRepository 访问数据
│   ├── audio/
│   ├── navigation/
│   └── utils/
│
└── robot_system_ros2/                    # ROS2 包装层（未改动核心逻辑）
    ├── launch/robot_system.launch.py
    ├── msg/
    └── ros2_bridge/
        ├── brain_node.py
        ├── vision_node.py
        ├── action_node.py
        └── ...
```

---

## 2. 新增模块说明

### 2.1 RobotBrain 拆分（`core/brain.py`）

外部接口不变：`start()` / `stop()` / `process()` / `tick()`。

`process()` 按事件类别委托：

| 方法 | 职责 |
|------|------|
| `_handle_face_event()` | 已知/未知人脸 → GREETING |
| `_handle_navigation_event()` | 导航请求 / 导航生命周期 |
| `_handle_system_event()` | FSM 定时器、注册候选等 |
| `_handle_dialog_event()` | LLM 对话后续 |

公共收尾：`_finalize_greeting()` 统一处理 `greeting_complete`。

### 2.2 RobotSDKAdapter（`adapters/robot_sdk_adapter.py`）

统一硬件接口（当前 Mock）：

```python
wave() / turn_head() / point() / navigate_to() / speak()
```

业务层禁止直接调用 SDK；`ActionExecutor` 是唯一动作出口。

### 2.3 ActionExecutor 改造

```
ActionExecutor → RobotSDKAdapter
```

队列 + 锁 + 超时机制保持不变，底层动作由 Adapter 执行。

### 2.4 HealthMonitor（`core/health_monitor.py`）

每 10 秒输出一次 `system_health` 日志：

```json
{"event_bus": true, "executor": true, "face_engine": true}
```

监控对象：EventBus 分发线程、ActionExecutor 双线程、FaceEngine 采集线程。

### 2.5 Demo Mode（`config.py`）

```python
DEMO_MODE = False   # 默认关闭演示导航
```

启用方式：

```bash
export ROBOT_DEMO_MODE=1
python3 main.py
```

仅 `DEMO_MODE=True` 时执行 `_schedule_demo_nav()`。

### 2.6 Ros2Adapter（`adapters/ros2_adapter.py`）

预留 ROS2 Humble 接入点（空实现）：

```python
publish() / subscribe() / call_action()
```

### 2.7 FaceRepository（`face_core/repository.py`）

| 方法 | 说明 |
|------|------|
| `add_person()` | 新增人员 |
| `delete_person()` | 删除人员 |
| `query_person()` | 查询人员信息 |
| `set_vip()` / `is_vip()` | VIP 标记 |
| `match()` | 人脸匹配（RecognitionService 使用） |

Brain 不访问 FaceDB；Vision 层经 Repository 读写。

### 2.8 WelcomePolicy（`policy/welcome_policy.py`）

| 方法 | 场景 |
|------|------|
| `vip_welcome(name)` | VIP 客户 |
| `normal_welcome(name)` | 普通已知客户 |
| `stranger_welcome()` | 陌生访客 |

`GreetingPolicy` 调用 `WelcomePolicy.resolve()` 生成 TTS 文本，Brain 不拼接欢迎词。

---

## 3. ROS2 接入点

现有 ROS2 包装层（`robot_system_ros2/`）保持不变，后续可按以下路径接入：

```
robot_system_ros2/ros2_bridge/
    ├── brain_node.py      → 复用 RobotBrain
    ├── vision_node.py     → FaceEngine + RecognitionService
    ├── action_node.py     → ActionExecutor + RobotSDKAdapter
    ├── nav_node.py        → NavController
    └── bus_adapter.py     → EventBus ↔ ROS2 Topic

adapters/ros2_adapter.py   → 替换 stub，对接 rclpy Node
```

推荐接入顺序：

1. `Ros2Adapter.publish/subscribe` 对接 `/robot_events`
2. `robot_system_ros2/launch/robot_system.launch.py` 启动各 Node
3. Action / Nav 通过 `RobotSDKAdapter` 对接真实底盘与头部电机

---

## 4. 灵犀 X2 SDK 接入点

只需替换 Adapter，业务层零改动：

| 文件 | 替换内容 |
|------|----------|
| `adapters/robot_sdk_adapter.py` | 调用灵犀 X2 官方 SDK |
| `navigation/nav_client.py` | 可委托 `RobotSDKAdapter.navigate_to()` |
| `audio/tts_engine.py` | 可委托 `RobotSDKAdapter.speak()` |

接入示例：

```python
class LingxiX2SDKAdapter(RobotSDKAdapter):
    def wave(self):
        self._sdk.arm.wave()

    def turn_head(self, angle: float = 30.0):
        self._sdk.head.rotate(angle)

    def navigate_to(self, location: str) -> bool:
        return self._sdk.nav.go(location)
```

`main.py` 中注入：

```python
self._sdk = LingxiX2SDKAdapter()
self._action_executor = ActionExecutor(self._bus, sdk=self._sdk)
```

---

## 5. 后续部署流程

### 5.1 本地单机验证

```bash
cd robot_system
pip install -r requirements.txt
python3 main.py
```

预期日志：

- `DEMO_MODE=False` → 无自动演示导航
- 每 10 秒 → `system_health {"event_bus": true, ...}`
- 人脸识别 → `[SDK] wave()` / `[SDK] turn_head()` 等 Mock 输出

### 5.2 启用演示模式（展厅调试）

```bash
export ROBOT_DEMO_MODE=1
python3 main.py
```

10 秒后自动注入 `NAV_REQUEST -> lobby`。

### 5.3 ROS2 Humble 部署

```bash
cd /path/to/x2_ws
colcon build --packages-select robot_system_ros2
source install/setup.bash
ros2 launch robot_system_ros2 robot_system.launch.py
```

### 5.4 生产环境 checklist

- [ ] 替换 `RobotSDKAdapter` 为灵犀 X2 真实 SDK
- [ ] 替换 `FaceEngine` 模拟采集为真实相机流
- [ ] 通过 `FaceRepository.add_person()` / `set_vip()` 导入售楼 VIP 名单
- [ ] 确认 `DEMO_MODE=False`
- [ ] 确认 `system_health` 三项均为 `true`
- [ ] ROS2 节点 watchdog / monitor 正常

---

## 6. 架构总览

```
                    ┌─────────────────┐
                    │   FaceEngine    │
                    └────────┬────────┘
                             │ FACE_RAW_DETECTED
                    ┌────────▼────────┐
                    │RecognitionService│──► FaceRepository
                    └────────┬────────┘
                             │ FACE_RECOGNIZED / UNKNOWN
                    ┌────────▼────────┐
                    │   RobotBrain    │  ← EventRouter + PolicyLayer
                    │  _handle_*()    │
                    └────────┬────────┘
                             │ ACTION / TTS / LLM / NAV
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
      ActionExecutor    TTSEngine     NavController
              │
              ▼
      RobotSDKAdapter  ◄── 灵犀 X2 SDK 替换点
              │
      Ros2Adapter      ◄── ROS2 Humble 替换点
```

FSM 状态流转（未修改）：

```
IDLE ──face──► GREETING ──complete──► COOLDOWN ──timer──► IDLE
```

---

*Generated for commercial deployment — single-machine ROS2 architecture.*
