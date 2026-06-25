# 灵犀 X2 售楼迎宾机器人（x2_face_ros2_system）

# 项目定位

面向售楼中心的智能迎宾机器人软件层，以事件驱动方式串联人脸识别、分级迎宾、欢送、导航、动作与语音播报，支持单机运行与 ROS2 分布式部署。

---

# 一、人脸识别能力

## 已知人员识别

| 维度 | 说明 |
|------|------|
| **实现方式** | 视觉模块采集人脸特征向量（embedding），经 `RecognitionService` 与人脸库进行余弦相似度匹配；匹配成功发布 `FACE_RECOGNIZED` 事件，携带 `person_id`、`name`、`score`、`vip_level`。 |
| **触发条件** | 收到 `FACE_RAW_DETECTED` 事件且 `in_welcome_zone=true`，embedding 与人脸库最佳匹配分数 ≥ 该人员置信度阈值（默认 0.75）。 |
| **最终效果** | 识别出已知访客身份与 VIP 等级，进入迎宾决策链路；更新在场人员列表与 `last_seen` 时间戳。 |

## 陌生人员识别

| 维度 | 说明 |
|------|------|
| **实现方式** | 匹配分数未达阈值时发布 `FACE_UNKNOWN` 事件；同时将特征写入候选池（candidate pool），发布 `ENROLL_CANDIDATE` 事件供后续人工转正。 |
| **触发条件** | 欢迎区内检测到人脸，但与人脸库所有记录均不匹配。 |
| **最终效果** | 按"首次到访客户"等级触发迎宾；陌生访客特征暂存候选池，可通过 CLI 工具 `promote` 转正入库。 |

## VIP 识别

| 维度 | 说明 |
|------|------|
| **实现方式** | 人脸库每条记录绑定 `vip_level`（executive / director / sales_director / consultant / vip_customer / regular_customer / first_visit）；识别命中后随事件下发等级，迎宾策略按 `vip_level.yaml` 选取话术与动作。 |
| **触发条件** | 已知人员匹配成功，且该人员 `vip_level` 属于 VIP 分级体系。 |
| **最终效果** | 高等级 VIP 获得优先播报权、专属欢迎话术与更大转头角度；节流层按等级优先级仲裁多人场景。 |

## 人脸库管理

| 维度 | 说明 |
|------|------|
| **实现方式** | `FaceRepository` 统一提供增删查改、VIP 等级设置、候选转正；`FaceDB` 支持 JSON 持久化、embedding 版本迁移；`CapacityManager` 管理 1000 人上限、过期清理与 LRU 淘汰；提供 `enroll_cli` 命令行工具。 |
| **触发条件** | 人工录入、陌生候选转正、容量维护周期（每 20 次识别触发一次）、注册前容量预检。 |
| **最终效果** | 人脸库可持续运营：永久人员（领导/员工/VIP 客户）受保护不被自动删除；普通访客超期未出现自动过期；库满时按 LRU 淘汰可删除访客。 |

## 冷却机制

| 维度 | 说明 |
|------|------|
| **实现方式** | 三层冷却：`CooldownManager` 管理 FSM 级迎宾冷却（5 秒）；`SpeechThrottle` 管理单人 30 分钟 TTS 冷却与全局 20 秒间隔；`DailyWelcomeTracker` 管理当日重复到访静默策略。 |
| **触发条件** | 迎宾完成进入 COOLDOWN 状态；同一身份 30 分钟内再次触发 TTS；全局两次播报间隔不足 20 秒；当日已欢迎过的已知人员再次到访。 |
| **最终效果** | 避免频繁重复播报；当日老客户再次到访仅点头致意（静默模式）；FSM 冷却期内拦截新的人脸迎宾事件。 |

## 识别确认机制

| 维度 | 说明 |
|------|------|
| **实现方式** | `RecognitionGuard` 要求三项条件同时满足：身份连续出现 ≥ 1.5 秒（debounce）、最近 3 次识别结果一致（confirm）、欢迎区内停留 ≥ 2 秒（zone dwell）。 |
| **触发条件** | 每次 `FACE_RECOGNIZED` / `FACE_UNKNOWN` 事件进入迎宾策略前。 |
| **最终效果** | 未通过确认时返回 `guard_pending`，不触发迎宾；通过后才进入话术与动作决策，降低误识别导致的错误迎宾。 |

## 防抖机制

| 维度 | 说明 |
|------|------|
| **实现方式** | `RecognitionGuard` 的 debounce 计时：同一身份自首次观测起累计 ≥ `RECOGNITION_DEBOUNCE_SEC`（默认 1.5 秒）才视为稳定；离开欢迎区时清除该身份计时。 |
| **触发条件** | 人脸在欢迎区内持续被检测，但尚未满足 debounce 时长。 |
| **最终效果** | 短暂路过或一闪而过的人脸不会触发迎宾；仅稳定停留的访客进入后续流程。 |

---

# 二、迎宾能力

## VIP 欢迎

| 维度 | 说明 |
|------|------|
| **触发逻辑** | 识别到已知人员且 `vip_level` 为 executive / director / sales_director / consultant / vip_customer；通过 RecognitionGuard 与 SpeechThrottle 后进入 `_greet_with_guards`。 |
| **话术逻辑** | `WelcomePolicy` 按等级从 `vip_level.yaml` 随机选取欢迎语（每等级 10 条模板，避免近 5 条重复）；支持 `{name}` 占位符个性化称呼。 |
| **节流逻辑** | VIP 等级在 `LEVEL_PRIORITY` 中排位靠前，多人同时到访时 VIP 获得 `primary_identity` 优先播报权；其余身份返回 `vip_priority_wait` 仅点头。 |

## 老客户欢迎

| 维度 | 说明 |
|------|------|
| **触发逻辑** | 识别到 `vip_level=regular_customer` 的已知回访客户；当日首次到访走完整欢迎，当日再次出现触发静默策略。 |
| **话术逻辑** | 使用 regular_customer 等级话术（如"欢迎回来，今天想看看沙盘还是直接去样板区？"）；近 5 条不重复随机选取。 |
| **节流逻辑** | 受单人 30 分钟 TTS 冷却、全局 20 秒间隔约束；`DAILY_SILENT_REPEAT` 开启时当日第二次到访仅执行 12° 点头动作，不播报 TTS。 |

## 首次客户欢迎

| 维度 | 说明 |
|------|------|
| **触发逻辑** | 陌生人员（`FACE_UNKNOWN`）或 `vip_level=first_visit`；默认将陌生人映射为 first_visit 等级。 |
| **话术逻辑** | 使用 first_visit 等级温和引导话术（如"欢迎首次莅临，我先带您看沙盘全貌"）；无姓名时使用无称呼模板。 |
| **节流逻辑** | 陌生人以 `unknown` 身份参与节流；不受单人冷却（因无 person_id），但受全局间隔与 sales_engaged 开关约束。 |

## 家庭客户欢迎

| 维度 | 说明 |
|------|------|
| **触发逻辑** | 当前软件层**未单独定义"家庭客户"等级**；多人同行（≥3 人）由群体检测逻辑自动切换为 group 模式。 |
| **话术逻辑** | 无家庭专属话术；群体模式下使用 group 等级统一欢迎（如"欢迎各位光临，请先在前台登记"），不连续报姓名。 |
| **节流逻辑** | 群体模式受独立 `group_throttle`（与全局间隔相同）约束；群体 TTS 单独记录 `_last_group_tts` 时间戳。 |

## 多人客户欢迎

| 维度 | 说明 |
|------|------|
| **触发逻辑** | `RecognitionGuard` 在 10 秒窗口内估算 `group_size ≥ 3`（取最大上报人数与不同身份数之较大值），进入 `group_mode`。 |
| **话术逻辑** | 调用 `WelcomePolicy.group_welcome()` 选取群体话术；禁止逐个报姓名。 |
| **节流逻辑** | `SpeechThrottle` 对群体播报执行 `group_policy` 判定；不满足全局/群体间隔时仅点头（`allow_nod=true`）。 |

## 群体欢迎

| 维度 | 说明 |
|------|------|
| **触发逻辑** | 与"多人客户欢迎"相同，`GROUP_GREETING_THRESHOLD=3` 为启用阈值。 |
| **话术逻辑** | `vip_level.yaml` 中 group 等级 5 条模板 + `SpeechThrottle.GROUP_WELCOMES` 备用池。 |
| **节流逻辑** | 群体欢迎占用一次全局 TTS 配额与群体 TTS 配额；动作使用固定 20° 转头 + 挥手。 |

---

# 三、欢送能力

## VIP 欢送

| 维度 | 说明 |
|------|------|
| **触发条件** | VIP 已知人员离开欢迎区（超过 `ZONE_EXIT_TIMEOUT_SEC=15` 秒未再检测到，或 `in_welcome_zone=false`），发布 `FACE_DEPARTED` 事件。 |
| **防重复机制** | 同一 `person_id` 在 `FAREWELL_PERSON_COOLDOWN`（默认 30 分钟）内不重复欢送。 |
| **状态流转** | 仅在 IDLE / DIALOG / COOLDOWN 状态下执行；GREETING / NAVIGATION / ERROR 状态拦截欢送（`farewell_blocked_state`）。当前 VIP 与普通客户使用相同收口话术，未按等级区分欢送内容。 |

## 普通客户欢送

| 维度 | 说明 |
|------|------|
| **触发条件** | `regular_customer` 或 `first_visit` 等级已知/未知客户离开欢迎区。 |
| **防重复机制** | 同人 30 分钟冷却；未知人员以 `unknown` 身份记录。 |
| **状态流转** | 欢送动作：12° 点头 + TTS 播报 `closing_remark()`（3 条随机收口语，如"感谢您的到访，案场随时欢迎您再来"）。不触发 FSM 状态变更。 |

## 家庭客户欢送

| 维度 | 说明 |
|------|------|
| **触发条件** | 当前**无家庭客户专属欢送逻辑**；群体中各身份分别检测离开并独立触发 `FACE_DEPARTED`。 |
| **防重复机制** | 每个 `person_id` 独立 30 分钟冷却。 |
| **状态流转** | 与普通过客欢送相同，统一收口话术 + 点头动作。 |

## 未识别客户欢送

| 维度 | 说明 |
|------|------|
| **触发条件** | 陌生人员（`person_id=unknown`）离开欢迎区超时或区域退出。 |
| **防重复机制** | 以 `unknown` 身份记录最后欢送时间。 |
| **状态流转** | 发布 `FACE_DEPARTED`（无 person_id，携带 `vip_level=first_visit`）；执行统一收口话术欢送。 |

---

# 四、事件驱动能力

## EventBus

- 线程安全的事件发布/订阅总线，支持多消费者注册与按事件类型过滤。
- 入口队列容量 1024，独立分发线程 fan-out 到各消费者队列。
- 发布前经 `EventValidator` 校验，拒绝非法事件并统计 published / dispatched / rejected 计数。
- 支持 `publish_tick()` 周期性心跳、`drain()` 批量消费。

## Trace

- 全局单例 `TraceLogger` 记录事件全链路：lifecycle（PUBLISH / CONSUME / ROUTE）、pipeline chain（FACE → BRAIN → FSM → ACTION → TTS）、状态迁移历史、动作执行历史。
- 每条事件携带 `trace_id` 与 `event_id`，子事件通过 `from_parent` 继承 trace。
- 提供 `snapshot()` 输出最近 20 条状态/动作历史及活跃 trace 数量。

## 事件路由

- `EventRouter` 将事件分类为 face_known / face_unknown / face_departed / navigation / dialog / nav_lifecycle / enrollment / tick 等类别。
- 结合 `PriorityArbiter` 按当前 FSM 状态与事件优先级决定是否放行、丢弃或延迟（defer）。
- 导航请求在 GREETING / DIALOG / COOLDOWN 状态下标记为 defer，待 IDLE 后自动补发。

## 异步处理

- 所有子系统以独立守护线程运行：FaceEngine、RecognitionService、RobotBrain、ActionExecutor、TTSEngine、LLMClient、NavController、EventBus 分发器。
- Brain 以 0.1 秒 tick 周期 drain 事件队列并驱动 FSM 定时器。
- 导航任务在 NavController 中以独立线程执行，支持超时与重试。
- 动作执行通过队列 + 互斥锁串行化，防止并发冲突。

---

# 五、状态机能力

## 所有状态

| 状态 | 含义 |
|------|------|
| **IDLE** | 空闲待命，可接受人脸、导航、对话请求 |
| **GREETING** | 正在执行迎宾（动作 + TTS） |
| **COOLDOWN** | 迎宾完成冷却期（默认 5 秒），拦截新人脸迎宾 |
| **NAVIGATION** | 导航进行中，拦截人脸与 LLM 请求 |
| **DIALOG** | 对话进行中（LLM 回复处理） |
| **ERROR** | 异常状态（导航超时/失败），支持自动恢复 |

## 所有状态流转

| 当前状态 | 事件 | 目标状态 |
|----------|------|----------|
| IDLE / DIALOG | FACE_RECOGNIZED / FACE_UNKNOWN | GREETING |
| GREETING | GREETING_COMPLETE | COOLDOWN |
| COOLDOWN | FSM_TIMER_EXPIRED (greeting) | IDLE |
| IDLE | NAV_REQUEST | NAVIGATION |
| IDLE / NAVIGATION | NAV_STARTED | NAVIGATION |
| NAVIGATION | NAV_COMPLETED (SUCCESS) | IDLE |
| NAVIGATION | NAV_COMPLETED (非 SUCCESS) / NAV_FAILED | ERROR |
| NAVIGATION | FSM_TIMER_EXPIRED (navigation) | ERROR |
| IDLE / GREETING | LLM_MESSAGE | DIALOG |
| COOLDOWN | LLM_MESSAGE | COOLDOWN（保持） |
| DIALOG | FSM_TIMER_EXPIRED (dialog) | IDLE |
| ERROR | recover_from_error | IDLE |

## 所有保护机制

- **状态门禁**：`can_greet()` 仅 IDLE/DIALOG 可迎宾；`can_navigate()` 仅 IDLE 可导航；`can_dialog()` 在 IDLE/GREETING/DIALOG/COOLDOWN 可对话。
- **优先级仲裁**：导航事件 CRITICAL 优先级，执行中拦截 NORMAL 级人脸事件；GREETING 状态阻止 FACE_DEPARTED 欢送。
- **冷却联动**：进入 COOLDOWN/DIALOG/NAVIGATION 自动启动对应计时器；回到 IDLE 清除所有冷却。
- **动作失败兜底**：GREETING 期间 ACTION_FAILED 自动触发 GREETING_COMPLETE 防止卡死。
- **错误自恢复**：ERROR 状态 5 秒后自动恢复 IDLE（可配置 `ERROR_AUTO_RECOVERY`）。
- **导航延迟队列**：非 IDLE 状态的 NAV_REQUEST 暂存，IDLE 后自动补发。

---

# 六、导航业务能力

## 导航请求

- 通过 `NAV_REQUEST` 事件发起，payload 携带 `action`（go_to / return_to_charge）与 `location`（lobby / charging_station 等）。
- `NavPolicy` 校验 FSM 状态，非 IDLE 时标记 `nav_deferred` 并延迟执行。
- 授权后下发 `NAV_EXECUTE` 命令。

## 导航调度

- `NavController`（单机模式）或 `NavNode`（ROS2 模式）消费 `NAV_EXECUTE`。
- 支持互斥锁：同一时刻仅一个导航任务；controller/nav 忙碌时返回 REJECTED。
- 超时 30 秒、最多重试 3 次；与动作执行互斥（`is_nav_busy` / `is_action_busy`）。

## 导航事件

- 生命周期事件：`NAV_STARTED` → `NAV_COMPLETED` / `NAV_FAILED`。
- 结果枚举：SUCCESS / FAILED / TIMEOUT / REJECTED。
- FSM 根据结果驱动状态流转；Brain 在 NAVIGATION 状态设置 CRITICAL 活跃优先级。

## 导航完成回调

- `NavPolicy.lifecycle()` 处理完成事件：成功时 TTS 播报"已到达{location}"；失败时播报"导航失败，请稍后重试"。
- NavController 发布带 `retries` 计数的完成/失败 payload。

## 当前是否为 Mock

| 运行模式 | 导航实现 |
|----------|----------|
| **单机模式**（`python main.py`） | **Mock** — `NavClient` 模拟 0.5 秒延迟后返回成功 |
| **ROS2 模式**（`nav_node`） | **半真实** — 优先调用 Nav2 `navigate_to_pose` Action；Nav2 不可用时自动降级为 Mock 导航（0.3 秒模拟成功） |

---

# 七、动作执行能力

## 挥手（wave）

- 迎宾与群体欢迎的标准动作之一，持续约 2 秒。
- 执行链路：Policy 决策 → `CommandEmitter` 发布 `ACTION_REQUEST` → `ActionExecutor` 队列消费 → `RobotSDKAdapter.wave()`。

## 转头（turn_head）

- 按 VIP 等级配置不同角度（18°–30°）；静默点头使用 12°；群体模式固定 20°。
- 执行链路：同上 → `RobotSDKAdapter.turn_head(angle)`。

## 指向（point）

- 对话场景中 LLM 回复（smalltalk / question 意图）附加 point 动作，目标默认 `visitor`。
- 执行链路：DialogPolicy → ACTION_REQUEST → `RobotSDKAdapter.point(target)`。

## 播报（TTS）

- 迎宾、欢送、导航完成、对话回复均通过 `TTS_REQUEST` 事件驱动。
- 执行链路：Policy 决策 → `CommandEmitter` 发布 `TTS_REQUEST` → `TTSEngine` 消费并日志输出（当前为 Mock 播报）。

## 当前执行链路

```
PolicyOutcome.commands
  → CommandEmitter（转 ACTION_REQUEST / TTS_REQUEST）
    → EventBus 分发
      → ActionExecutor（队列 + 锁 + 超时）→ RobotSDKAdapter（Mock 日志）
      → TTSEngine（Mock 日志）
```

**ROS2 模式下**：BrainNode 将 ACTION/TTS 事件转发至 `/action_commands` 与 `/audio_commands` 话题，由 ActionNode / AudioNode 本地执行。

**当前执行层均为 Mock**：`RobotSDKAdapter` 与 `TTSEngine` 仅输出日志，待接入灵犀 X2 真机 SDK 与 TTS 引擎。

---

# 八、语音交互能力

## 欢迎语

| 状态 | 说明 |
|------|------|
| **已实现** | 7 级 VIP 分级欢迎话术（`vip_level.yaml`，每级 10 条）；群体欢迎 5 条；首次到访 15 条；随机去重选取；支持姓名嵌入。 |
| **Mock 部分** | TTS 播报为日志模拟，未对接真实语音合成硬件。 |

## 欢送语

| 状态 | 说明 |
|------|------|
| **已实现** | `closing_remark()` 提供 3 条售楼收口话术，离开时随机选取。 |
| **Mock 部分** | TTS 播报为日志模拟。 |

## 售楼话术

| 状态 | 说明 |
|------|------|
| **已实现** | `tour_invitation()` 提供 5 条沙盘/样板区引导话术；各级 strategy 块定义 escort / route / duration / notes 业务元数据（供后续导航联动扩展）。 |
| **未接入** | tour_invitation 尚未自动触发，需业务层显式调用或后续接入。 |

## 对话链路

| 状态 | 说明 |
|------|------|
| **已实现** | LLM_REQUEST → LLMClient（结构化 Mock 回复）→ LLM_MESSAGE → DialogPolicy → TTS + 可选 point 动作；支持 greet / unknown / 天气 / 问候等意图识别。 |
| **Mock 部分** | `LLMClient` 为离线规则 Mock，未对接真实大模型 API；TTS 为日志模拟。 |

## sales_engaged 保护

- 可通过环境变量 `ROBOT_SALES_ENGAGED=1` 或 ROS2 话题 `/robot_sales_engaged` 开启。
- 开启后 SpeechThrottle 禁止主动 TTS 播报，仅允许点头动作（`sales_engaged` 原因拦截）。

---

# 九、ROS2 适配能力

## 已完成

| 能力 | 说明 |
|------|------|
| **多节点部署** | event_bridge / vision / brain / action / nav / audio / monitor 共 7 个 ROS2 节点，launch 文件分阶段启动 |
| **事件桥接** | `/robot_events` 话题（Schema v1.0 JSON），`Ros2BusAdapter` 双向桥接本地 EventBus |
| **命令话题** | `/action_commands`、`/audio_commands` 分离动作与语音指令 |
| **导航对接** | NavNode 集成 Nav2 `NavigateToPose` Action Client，支持 `/nav_goal` PoseStamped 订阅 |
| **QoS 标准化** | ROBOT_EVENTS（BEST_EFFORT）、COMMANDS/AUDIO/NAV（RELIABLE）统一配置 |
| **背压控制** | `EventBackpressureController` 防止事件洪峰 |
| **运行时可观测** | `/system_health`（1Hz）、`/node_heartbeat`、`/system_mode`（FULL/DEGRADED/SAFE） |
| **节点看门狗** | NodeWatchdog 监测节点存活，BrainNode 根据状态降级（SAFE 模式仅保留恢复 TTS） |
| **互斥协调** | RuntimeState 共享 `is_nav_busy` / `is_action_busy` / `is_speaking` 标志 |

## 已预留

| 能力 | 说明 |
|------|------|
| **Ros2Adapter 桩** | `adapters/ros2_adapter.py` 预留 publish / subscribe / call_action 接口 |
| **RobotSDKAdapter** | 挥手/转头/指向/导航/播报方法体待替换为灵犀 X2 SDK 调用 |
| **Face.msg** | ROS2 消息定义文件已创建，待 vision_node 对接真实相机话题 |
| **事件编解码** | `event_codec.py` 支持 Legacy 与 v1.0 双向映射 |
| **人脸录入 CLI** | `enroll_cli` 支持 list / promote / set-vip，可对接案场运维流程 |

## 待接入

| 能力 | 说明 |
|------|------|
| **真实相机/人脸检测** | 当前 FaceEngine 为模拟数据源（每 3 秒随机生成 embedding） |
| **灵犀 X2 动作 SDK** | RobotSDKAdapter 方法体为日志桩 |
| **真实 TTS 引擎** | TTSEngine 为日志桩 |
| **真实 LLM 服务** | LLMClient 为离线规则 Mock |
| **真实人脸特征提取** | 待对接 X2 视觉 SDK 替换模拟 embedding |
| **地图点位管理** | NavNode 当前仅预设 lobby / charging_station 坐标，待对接实际地图 |

---

# 十、软件层最终能力矩阵

| 能力名称 | 状态 | 完成度(%) | 是否可演示 | 是否可真机接入 |
|----------|------|-----------|------------|----------------|
| 已知人员识别 | 已实现（模拟数据源） | 85 | 是 | 待接相机 SDK |
| 陌生人员识别 | 已实现 | 85 | 是 | 待接相机 SDK |
| VIP 分级识别 | 已实现 | 95 | 是 | 是 |
| 人脸库管理 | 已实现 | 90 | 是 | 是 |
| 识别确认/防抖 | 已实现 | 95 | 是 | 是 |
| 分级迎宾话术 | 已实现 | 95 | 是 | 是 |
| 群体迎宾 | 已实现 | 90 | 是 | 是 |
| 当日静默重复欢迎 | 已实现 | 95 | 是 | 是 |
| 播报节流保护 | 已实现 | 95 | 是 | 是 |
| 欢送（离开检测） | 已实现 | 80 | 是 | 是 |
| 家庭客户专属策略 | 未实现 | 0 | 否 | 否 |
| 事件驱动总线 | 已实现 | 95 | 是 | 是 |
| 全链路 Trace | 已实现 | 90 | 是 | 是 |
| FSM 状态机 | 已实现 | 95 | 是 | 是 |
| 导航业务逻辑 | 已实现 | 85 | 是（Mock） | 半就绪（Nav2） |
| 动作执行框架 | 已实现（Mock 执行） | 75 | 是（日志） | 待接动作 SDK |
| TTS 播报框架 | 已实现（Mock 播报） | 70 | 是（日志） | 待接 TTS 引擎 |
| LLM 对话 | 已实现（规则 Mock） | 60 | 是（日志） | 待接 LLM API |
| 售楼引导话术 | 已实现（未自动触发） | 50 | 部分 | 是 |
| ROS2 多节点部署 | 已实现 | 90 | 是 | 是 |
| 系统健康监控 | 已实现 | 85 | 是 | 是 |
| 容量自动维护 | 已实现 | 90 | 是 | 是 |
| 人脸录入 CLI | 已实现 | 85 | 是 | 是 |

---

# 十一、一句话总结

"当前项目已经具备**事件驱动的人脸识别分级迎宾、节流防抖保护、欢送检测、FSM 状态管控、导航调度框架、动作与语音指令链路、ROS2 分布式部署与运行时降级监控**能力，可作为灵犀 X2 售楼迎宾机器人软件层基础版本进行真机集成。"
