# 灵犀 X2 真机集成评估报告

> 评估视角：工程经理  
> 假设条件：机器人今日到货，目标为售楼处现场迎宾演示  
> 评估基准：基于当前 `x2_face_ros2_system` 源码全量梳理

---

# 已经具备的软件能力

以下模块**业务逻辑完整、链路已打通**，真机集成时**无需修改策略与编排代码**，仅需在底层 Adapter 替换 Mock 实现。

## 可直接使用的业务能力

| 能力 | 说明 |
|------|------|
| **分级迎宾决策** | VIP 7 级 + 群体 + 首次到访话术选取（`welcome_policy.py` + `vip_level.yaml`） |
| **迎宾节流与保护** | 识别防抖/确认、单人/全局 TTS 冷却、当日静默重复、销售接待模式（`recognition_guard.py` / `speech_throttle.py` / `daily_welcome_tracker.py`） |
| **欢送决策** | 区域离开检测、防重复欢送、收口话术（`farewell_policy.py` + `recognition_service.py`） |
| **人脸库运营** | 入库/删改/VIP 分级、候选池转正、1000 人容量维护、JSON 持久化（`face_repository.py` / `capacity_manager.py` / `face_db.py`） |
| **人脸匹配算法** | 余弦相似度匹配、按人阈值、last_seen 更新（`face_db.match()`） |
| **FSM 状态机** | IDLE / GREETING / COOLDOWN / NAVIGATION / DIALOG / ERROR 全流转与保护（`state_machine.py`） |
| **事件驱动编排** | EventBus 分发、Router 路由、Priority 仲裁、CommandEmitter 指令下发（`event_bus.py` / `event_router.py` / `command_emitter.py`） |
| **全链路 Trace** | trace_id 贯穿识别→决策→动作→播报（`trace_logger.py`） |
| **导航业务调度** | 请求授权、延迟队列、超时重试、完成/失败回调话术（`nav_policy.py` / `nav_controller.py`） |
| **对话策略框架** | LLM 回复转 TTS + 指向动作，导航/错误态抑制（`dialog_policy.py`） |
| **动作执行框架** | 队列串行、互斥锁、超时与失败上报（`action_executor.py`） |
| **运维工具** | 人脸录入 CLI（`tools/enroll_cli.py`） |
| **配置体系** | 环境变量可调防抖/冷却/容量等全部阈值（`config.py`） |

## 可直接使用的部署能力（ROS2 模式）

| 能力 | 说明 |
|------|------|
| **7 节点分布式启动** | `robot_system_ros2/launch/robot_system.launch.py` |
| **跨节点事件桥接** | `/robot_events` Schema v1.0（`bus_adapter.py` / `event_codec.py`） |
| **动作/语音指令分离** | `/action_commands`、`/audio_commands` |
| **Nav2 Action 客户端** | `nav_node.py` 已集成 `NavigateToPose`，Nav2 不可用时自动 Mock 降级 |
| **运行时降级** | FULL / DEGRADED / SAFE 三档（`brain_node.py` + `node_watchdog.py`） |
| **健康监控** | `/system_health` 1Hz、`/node_heartbeat`、`/system_mode`（`monitor_node.py`） |
| **互斥协调** | 导航与动作互斥（`runtime_state.py`：`is_nav_busy` / `is_action_busy`） |

## 真机到货当天即可验证（无需 SDK）

```bash
# 单机模式 — 验证业务链路
cd robot_system && pip install -r requirements.txt && python3 main.py

# ROS2 模式 — 验证多节点通信
colcon build --packages-select robot_system_ros2
ros2 launch robot_system_ros2 robot_system.launch.py
```

可观察：模拟人脸识别 → 分级迎宾决策 → Mock 动作/TTS 日志 → FSM 状态迁移 → system_health 上报。

---

# 需要接入 SDK 的功能

## 摄像头

| 项目 | 内容 |
|------|------|
| **当前状态** | `FaceEngine` 每 3 秒随机生成 embedding，无真实图像采集 |
| **主接入点** | `robot_system/vision/face_engine.py` — 替换 `_loop()` 中模拟逻辑，改为读取相机帧并检测人脸区域 |
| **ROS2 扩展点** | `robot_system_ros2/ros2_bridge/vision_node.py` — 可新增 `sensor_msgs/Image` 或 `CompressedImage` 订阅，将帧传入 FaceEngine |
| **预留消息** | `robot_system_ros2/msg/Face.msg`（已定义，尚未被 vision_node 使用） |
| **下游无需改动** | `recognition_service.py` 仍消费 `FACE_RAW_DETECTED`（payload 含 `embedding`、`in_welcome_zone`、`person_count`） |
| **关键参数** | 需在 payload 中正确填充 `in_welcome_zone`（欢迎区判断）和 `person_count`（群体检测），否则 RecognitionGuard 群体策略失效 |

## 人脸 SDK

| 项目 | 内容 |
|------|------|
| **当前状态** | 自建 embedding 匹配（128 维余弦相似度）；无 X2 官方人脸 SDK 调用 |
| **方案 A（推荐）** | SDK 输出 embedding → 仍走现有 `FaceDB.match()` 链路 |
| | 接入点：`robot_system/vision/face_engine.py`（采集帧后调 SDK 提特征，发布 `FACE_RAW_DETECTED`） |
| **方案 B** | SDK 内置 1:N 识别 → 需新增 Adapter 将 SDK 结果映射为 `FACE_RECOGNIZED` / `FACE_UNKNOWN` 事件 |
| | 建议新建：`robot_system/adapters/face_sdk_adapter.py`（当前不存在） |
| | 修改点：`robot_system/vision/recognition_service.py` — 增加 SDK 直连分支，或绕过 `_repo.match()` |
| **人脸库同步** | 若 X2 SDK 自带库管理，需与 `face_repository.py` 双向同步；当前容量策略按 SDK 1000 人上限设计（`capacity_manager.py`） |
| **运维接入点** | `robot_system/tools/enroll_cli.py` — 录入时改为调 SDK 注册接口 |
| **阈值标定** | `robot_system/config.py` — `FACE_MATCH_THRESHOLD`；`face_db.py` — 每人 `confidence_threshold` |

## TTS

| 项目 | 内容 |
|------|------|
| **当前状态** | `TTSEngine` 仅打印日志，无真实发声 |
| **主接入点** | `robot_system/audio/tts_engine.py` — `_loop()` 收到 `TTS_REQUEST` 后调用 SDK 播报 |
| **备选接入点** | `robot_system/adapters/robot_sdk_adapter.py` — `speak(text, lang)` 方法；TTSEngine 内委托 `self._sdk.speak()` |
| **ROS2 执行点** | `robot_system_ros2/ros2_bridge/audio_node.py` — 消费 `/audio_commands` 后仍走本地 `TTSEngine` |
| **协调注意** | `brain_node.py` 用 `is_speaking` 防重复 TTS；SDK 需支持播报完成回调或超时释放，否则后续播报被阻塞 |
| **播报内容** | 已由 `WelcomePolicy` / `FarewellPolicy` / `NavPolicy` 生成，**无需改话术层** |

## 动作控制

| 项目 | 内容 |
|------|------|
| **当前状态** | `RobotSDKAdapter` 四个方法均为日志桩 |
| **主接入点** | `robot_system/adapters/robot_sdk_adapter.py` |
| | `wave()` / `turn_head(angle)` / `point(target)` / `navigate_to(location)` |
| **执行链路（无需改）** | `action_executor.py` → `_sdk.wave()` 等 |
| **ROS2 执行点** | `robot_system_ros2/ros2_bridge/action_node.py` — 订阅 `/action_commands`，仍用 `ActionExecutor` |
| **手势目录** | `robot_system/behavior/gesture.py` — 已定义 wave / turn_head / point / question_mark 及时长 |
| **角度映射** | `greeting_policy.py` — VIP 等级对应转头角度 18°–30°，需确认 X2 关节量纲（度 vs 弧度） |

## 导航

| 项目 | 内容 |
|------|------|
| **当前状态** | 单机 `NavClient` 为 Mock；ROS2 `NavNode` 已接 Nav2，缺真实地图与点位 |
| **单机接入点** | `robot_system/navigation/nav_client.py` — `go_to()` / `return_to_charge()` |
| **可选统一** | 委托 `RobotSDKAdapter.navigate_to()`，由 `nav_controller.py` `_call_sdk()` 调用 |
| **ROS2 接入点** | `robot_system_ros2/ros2_bridge/nav_node.py` — Nav2 `navigate_to_pose` Action；`_default_pose()` 需替换为售楼处实际坐标 |
| **地图与点位** | 需在现场建图并配置 lobby / 沙盘区 / 样板区等 waypoints（当前仅硬编码 lobby、charging_station） |
| **业务层无需改** | `nav_policy.py` / `nav_controller.py` 事件协议已完整 |

## 麦克风

| 项目 | 内容 |
|------|------|
| **当前状态** | **项目中无麦克风/ASR 模块**，语音对话入口未实现 |
| **需新建** | 建议 `robot_system/audio/asr_engine.py`（或 `adapters/asr_adapter.py`） |
| **接入方式** | 采集音频 → ASR 转文字 → 发布 `LLM_REQUEST` 事件到 EventBus |
| **注册消费者** | `robot_system/main.py` — `_register_consumers()` 增加 asr 消费者；新建 asr 线程 |
| **ROS2 扩展** | `robot_system_ros2/ros2_bridge/audio_node.py` — 增加麦克风采集与 ASR，或独立 `asr_node` |
| **对话链路（已有）** | `LLM_REQUEST` → `llm_client.py` → `LLM_MESSAGE` → `dialog_policy.py` → TTS |
| **唤醒策略** | 需额外设计（按键唤醒 / 唤醒词 / 人脸触发后开麦），当前代码无此逻辑 |

## 大模型

| 项目 | 内容 |
|------|------|
| **当前状态** | `LLMClient` 为离线规则 Mock（关键词匹配返回固定话术） |
| **主接入点** | `robot_system/audio/llm_client.py` |
| | `generate_structured()` — 替换为真实 API 调用 |
| | `_handle_request()` — 保持发布 `LLM_MESSAGE` 事件结构不变 |
| **Prompt 模板** | `robot_system/behavior/dialog_policy.py` — `build_greet_prompt()` 已备好 context |
| **安全约束（已有）** | DialogPolicy 禁止 LLM 直接触发导航/动作，仅输出 TTS + 可选 point |
| **ROS2** | `audio_node.py` 已包装 `LLMClient`，改一处即可 |

---

# 预计开发工作量

> 假设：1 名熟悉 Python/ROS2 的工程师 + 灵犀 X2 SDK 文档齐备  
> 不含现场建图、网络部署、甲方验收沟通

| 模块 | 工作量 | 说明 |
|------|--------|------|
| **摄像头接入** | **3~7 天** | 无现有相机代码；需确认 X2 相机接口（V4L2 / ROS Topic / 私有 SDK）；欢迎区与人数检测需联调 |
| **人脸 SDK** | **3~7 天** | 特征维度对齐、阈值标定、现场光照测试、与自建 FaceDB 同步策略；若 SDK 自带库管理则偏上限 |
| **TTS** | **1~3 天** | 接口简单；难点在播报完成回调与 `is_speaking` 状态协调 |
| **动作控制** | **1~3 天** | 挥手/转头/指向三个动作；需确认 SDK 异步/同步语义与超时配置 |
| **导航** | **3~7 天** | ROS2 下 Nav2 框架已有；主要耗时在 SLAM 建图、点位标定、现场避障测试；单机模式若走 SDK 导航另计 |
| **麦克风 + ASR** | **7 天以上** | 全新模块；售楼处噪声环境、唤醒策略、与 TTS 播报互斥（回声）均需专项处理 |
| **大模型** | **1~3 天** | API 对接本身快；若要做售楼专属 Prompt、流式输出、离线容灾则偏上限 |
| **ROS2 联调与稳定性** | **3~7 天** | 7 节点启动时序、watchdog 降级、真机长时间运行；可与上述任务并行 |
| **售楼 VIP 数据准备** | **1~3 天** | 导入人脸、设置 vip_level、现场试识别；可用 `enroll_cli` + 运维脚本 |

### 按演示场景汇总

| 演示目标 | 必做项 | 预估日历工期（1 人） | 预估日历工期（2 人并行） |
|----------|--------|----------------------|--------------------------|
| **最小可演示**（识人 + 挥手转头 + 语音欢迎） | 摄像头 + 人脸 SDK + TTS + 动作 | **10~15 天** | **7~10 天** |
| **标准售楼演示**（上述 + 主动迎宾稳定 + 欢送） | + 阈值标定 + VIP 录入 + 联调 | **15~20 天** | **10~14 天** |
| **完整演示**（上述 + 导航导览 + 语音问答） | + 导航建图 + 麦克风 ASR + LLM | **30~45 天** | **20~30 天** |

---

# 真机上线前 Checklist

## 一、硬件与 SDK 环境

- [ ] 确认灵犀 X2 SDK 版本与 Python/ROS2 绑定包可安装
- [ ] 确认机器人相机、麦克风、扬声器、头部电机、底盘导航均已授权可调用
- [ ] 在机器人上完成 SDK 最小示例跑通（单独脚本验证 wave / TTS / 相机帧）
- [ ] 确认机器人与开发机网络互通（ROS2 DDS 域、防火墙、时间同步 NTP）

## 二、感知层接入

- [ ] `face_engine.py` 接入真实相机，发布 `FACE_RAW_DETECTED`
- [ ] 人脸 SDK 输出 embedding 或识别结果，匹配阈值在现场标定（建议 50+ 人次测试）
- [ ] `in_welcome_zone` 逻辑与售楼处实际迎宾区对齐（物理标识 / 坐标区域）
- [ ] `person_count` 群体检测验证（单人 / 双人 / 三人以上场景）
- [ ] 陌生脸候选池入库与 `enroll_cli promote` 流程验证

## 三、执行层接入

- [ ] `robot_sdk_adapter.py` 四个动作方法真机验证
- [ ] `tts_engine.py` 真机发声，音量与展厅环境匹配
- [ ] TTS 播报完成与 `is_speaking` 状态释放验证（防卡死）
- [ ] 动作超时 `ACTION_TIMEOUT=5s` 与 SDK 实际耗时对齐
- [ ] GREETING 期间 ACTION_FAILED 兜底流程真机验证

## 四、导航（若演示含导览）

- [ ] 售楼处地图建图完成并加载 Nav2
- [ ] `nav_node.py` 中 `_default_pose()` 替换为真实点位坐标
- [ ] 沙盘区 / 样板区 / 接待台 / 充电站 waypoint 命名与 `location` 参数统一
- [ ] 导航与动作互斥（`is_nav_busy` / `is_action_busy`）现场验证
- [ ] 导航失败 TTS 播报与 FSM 恢复 IDLE 验证

## 五、语音对话（若演示含问答）

- [ ] 新建 ASR 模块并接入麦克风
- [ ] `llm_client.py` 对接真实大模型 API（密钥、网络、超时）
- [ ] 售楼处噪声环境下 ASR 准确率评估
- [ ] TTS 播报期间麦克风静音/回声消除策略
- [ ] `ROBOT_SALES_ENGAGED` 销售接待模式现场开关测试

## 六、业务数据

- [ ] 导入售楼 VIP 名单（领导 / 销冠 / VIP 客户）并设置对应 `vip_level`
- [ ] `vip_level.yaml` 话术现场试听，必要时调整用语
- [ ] 验证当日静默重复欢迎（老客户第二次到访仅点头）
- [ ] 验证 30 分钟单人 TTS 冷却与 20 秒全局间隔

## 七、ROS2 部署

- [ ] `colcon build` 在机器人环境编译通过
- [ ] `ros2 launch robot_system_ros2 robot_system.launch.py` 7 节点全部 online
- [ ] `/system_health` 1Hz 上报正常，`system_mode=FULL`
- [ ] `node_watchdog` 心跳正常，单节点 kill 后降级策略符合预期
- [ ] `/robot_events` 跨节点 trace 链路完整（识别→大脑→动作→TTS 可追溯）

## 八、配置与运维

- [ ] `ROBOT_DEMO_MODE=0`（关闭自动注入导航）
- [ ] `ROBOT_FACE_DB_PATH` 指向持久化路径，重启后人脸库不丢失
- [ ] `ROBOT_LOG_LEVEL` 生产环境设为 INFO 或 WARNING
- [ ] 人脸库容量监控（850 预警 / 950 紧急清理）策略确认
- [ ] 编写现场重启 SOP 与应急降级预案（SAFE 模式仅保留恢复 TTS）

## 九、现场彩排

- [ ] 连续运行 2 小时无内存泄漏、线程僵死
- [ ] VIP / 普通客户 / 陌生人 / 多人 四类场景各彩排 ≥ 3 次
- [ ] 欢送流程（离开迎宾区 15 秒）验证
- [ ] 网络断开 / SDK 超时 / 节点崩溃 三类异常恢复验证

---

# 最终结论

## 如果机器人明天到货

从工程经理视角，当前项目**软件业务层成熟度约 85%**，**真机感知与执行层成熟度约 15%**。业务大脑、状态机、迎宾策略、事件编排、ROS2 分布式框架均已可用于生产；**机器人在售楼处「动起来、说出来、认出来」仍依赖 4 项 SDK 接入**（相机、人脸、TTS、动作），其中麦克风/ASR 为全新开发。

### 距售楼处现场演示还差多少？

| 场景 | 差距评估 |
|------|----------|
| **明天到货，最快现场演示** | **不可行**。无 SDK 接入，机器人无法完成真实识人迎宾，仅可演示软件 Mock 日志或 PC 端仿真。 |
| **迎宾级演示**（识人 + 动作 + 语音欢迎 + 欢送） | 距可彩排约 **7~15 个工作日**（2 人并行可压至 **7~10 天**）。关键路径：相机 + 人脸 SDK（3~7 天）→ TTS + 动作（各 1~3 天）→ 联调标定（3~5 天）。 |
| **售楼完整演示**（含导航导览 + 语音问答） | 距可彩排约 **20~30 个工作日**（2 人并行）。额外增加：现场建图与 Nav2 点位（3~7 天）、麦克风 ASR 新模块（7 天以上）、LLM API 与回声处理（3~5 天）。 |

### 工程建议（到货后第一周）

1. **Day 1~2**：用 SDK 独立脚本验证相机、TTS、挥手/转头，不碰业务代码，确认接口契约。  
2. **Day 3~5**：替换 `robot_sdk_adapter.py` + `tts_engine.py`（见效快，可先让机器人「说话挥手」）。  
3. **Day 3~7**：并行攻关 `face_engine.py` + 人脸 SDK（迎宾核心，耗时最长）。  
4. **Day 8~10**：ROS2 真机联调 + 售楼处阈值标定 + VIP 数据导入。  
5. **导航与语音对话**：不作为第一周的阻塞项；售楼迎宾演示可先用「原地迎宾」模式上线。

### 一句话结论

**机器人明天到货，当前项目还需约 1.5~3 周（2 人团队）可达到售楼处「识人迎宾 + 动作 + 语音」最小可演示状态；完整「迎宾 + 导览 + 对话」需 1~1.5 个月。** 软件业务层无需重写，风险集中在 SDK 接口对齐、现场光照识别率、以及麦克风模块从零开发。
