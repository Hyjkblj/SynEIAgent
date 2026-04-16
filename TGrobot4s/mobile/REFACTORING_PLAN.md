# Mobile App 解耦重构计划

## 概述

将高耦合的移动端架构拆分为清晰的分层结构，每个 PR 独立可测试，逐步完成解耦。

---

## PR 任务列表

### PR-1: 合并 Repository 和 Transport 层

**目标**: 消除冗余的 Repository 层，统一为 RobotClient

**变更范围**:
- 新增 `data/RobotClient.kt` 接口
- 重命名 `WebRtcRealtimeTransport` → `WebRtcRobotClient`
- 删除 `DefaultRobotRepository`
- 更新 `MainActivity` 依赖

**文件变更**:
```
data/
├── RobotClient.kt              # 新增 - 统一接口
├── WebRtcRobotClient.kt        # 重命名自 WebRtcRealtimeTransport
└── DefaultRobotRepository.kt   # 删除
```

**依赖关系**: 无前置依赖，可独立开始

**风险等级**: 低 - 接口兼容，行为不变

---

### PR-2: 引入 MessageStore 模块

**目标**: 将消息管理从 ViewModel 中剥离

**变更范围**:
- 新增 `domain/message/MessageStore.kt`
- 新增 `domain/message/UiMessage.kt` (从 TeleopUiState 迁移)
- 更新 `TeleopViewModel` 使用 MessageStore

**文件变更**:
```
domain/
└── message/
    ├── MessageStore.kt         # 新增
    └── UiMessage.kt            # 新增 (从 feature/control 迁移)
```

**依赖关系**: 无前置依赖，可独立开始

**风险等级**: 低 - 纯新增模块

---

### PR-3: 封装 ControlEngine

**目标**: 隐藏控制算法细节，提供简洁 API

**变更范围**:
- 新增 `domain/control/ControlEngine.kt`
- 重构 `ControlManager` 为内部实现
- 更新 `TeleopViewModel` 使用 ControlEngine

**文件变更**:
```
domain/control/
├── ControlEngine.kt            # 新增 - 门面类
├── ControlManager.kt           # 保留，内部实现
├── CommandMapper.kt            # 保留
├── Smoother.kt                 # 保留
├── SafetyController.kt         # 保留
└── RateLimiter.kt              # 保留
```

**依赖关系**: 无前置依赖，可独立开始

**风险等级**: 中 - 需要验证控制行为一致性

---

### PR-4: 引入 UseCase 层

**目标**: 将业务逻辑从 ViewModel 抽离到 UseCase

**变更范围**:
- 新增 `domain/usecase/ConnectRobotUseCase.kt`
- 新增 `domain/usecase/SendControlCommandUseCase.kt`
- 新增 `domain/usecase/ProcessVoiceIntentUseCase.kt`
- 更新 `TeleopViewModel` 使用 UseCase

**文件变更**:
```
domain/
└── usecase/
    ├── ConnectRobotUseCase.kt        # 新增
    ├── SendControlCommandUseCase.kt  # 新增
    └── ProcessVoiceIntentUseCase.kt  # 新增
```

**依赖关系**: 依赖 PR-1, PR-3

**风险等级**: 中 - 需要验证业务流程

---

### PR-5: 语音模块独立化

**目标**: 将语音控制封装为独立模块，消除跨 Feature 依赖

**变更范围**:
- 新增 `feature/voice/VoiceModule.kt`
- 新增 `feature/voice/VoiceModuleState.kt`
- 重构 `VoiceController` 为纯语音识别
- 更新 `TeleopViewModel` 通过 VoiceModule 交互

**文件变更**:
```
feature/voice/
├── VoiceController.kt          # 重构 - 仅保留语音识别
├── VoiceModule.kt              # 新增 - 语音命令处理
└── VoiceModuleState.kt         # 新增
```

**依赖关系**: 依赖 PR-4

**风险等级**: 中 - 需要验证语音流程

---

### PR-6: 引入 TeleopCoordinator

**目标**: 拆分 ViewModel 职责，Coordinator 协调 UseCase

**变更范围**:
- 新增 `feature/control/TeleopCoordinator.kt`
- 精简 `TeleopViewModel` 为纯 UI 状态容器
- 更新 `MainActivity` 构建依赖

**文件变更**:
```
feature/control/
├── TeleopViewModel.kt          # 精简 - 仅保留 UI 状态
├── TeleopCoordinator.kt        # 新增 - 协调 UseCase
└── TeleopViewModelFactory.kt   # 更新
```

**依赖关系**: 依赖 PR-2, PR-4, PR-5

**风险等级**: 高 - 核心架构变更

---

### PR-7: 引入 RobotSessionManager

**目标**: 统一管理连接会话生命周期

**变更范围**:
- 新增 `domain/session/RobotSessionManager.kt`
- 新增 `domain/session/SessionState.kt`
- 更新 `ConnectRobotUseCase` 使用 SessionManager

**文件变更**:
```
domain/
└── session/
    ├── RobotSessionManager.kt   # 新增
    └── SessionState.kt          # 新增
```

**依赖关系**: 依赖 PR-4

**风险等级**: 低 - 纯新增模块

---

### PR-8: 事件处理重构

**目标**: 将事件处理逻辑从 ViewModel 移至专用处理器

**变更范围**:
- 新增 `domain/event/RobotEventHandler.kt`
- 新增 `domain/event/EventDispatcher.kt`
- 更新 `TeleopCoordinator` 使用 EventDispatcher

**文件变更**:
```
domain/
└── event/
    ├── RobotEventHandler.kt     # 新增
    └── EventDispatcher.kt       # 新增
```

**依赖关系**: 依赖 PR-6

**风险等级**: 中 - 需要验证事件流程

---

## 执行顺序

```
阶段 1 (可并行):
├── PR-1: 合并 Repository 和 Transport
├── PR-2: 引入 MessageStore
└── PR-3: 封装 ControlEngine

阶段 2 (依赖阶段1):
├── PR-4: 引入 UseCase 层 (依赖 PR-1, PR-3)
└── PR-7: 引入 RobotSessionManager (依赖 PR-4)

阶段 3 (依赖阶段2):
├── PR-5: 语音模块独立化 (依赖 PR-4)
└── PR-6: 引入 TeleopCoordinator (依赖 PR-2, PR-4, PR-5)

阶段 4 (依赖阶段3):
└── PR-8: 事件处理重构 (依赖 PR-6)
```

---

## 验收标准

每个 PR 需满足:

1. **编译通过**: 无编译错误
2. **功能不变**: 现有功能行为保持一致
3. **测试覆盖**: 核心逻辑有单元测试
4. **代码审查**: 通过 Code Review
5. **文档更新**: 更新相关文档注释

---

## 风险控制

| 风险 | 缓解措施 |
|------|----------|
| 控制行为变化 | PR-3 增加集成测试验证控制流程 |
| 语音流程中断 | PR-5 保留原有 VoiceController 作为备份 |
| 架构变更过大 | PR-6 分阶段迁移，保留旧代码路径 |

---

## 进度追踪

| PR | 状态 | 负责人 | 开始日期 | 完成日期 |
|----|------|--------|----------|----------|
| PR-1 | ✅ 完成 | - | 2026-04-16 | 2026-04-16 |
| PR-2 | ✅ 完成 | - | 2026-04-16 | 2026-04-16 |
| PR-3 | ✅ 完成 | - | 2026-04-16 | 2026-04-16 |
| PR-4 | ✅ 完成 | - | 2026-04-16 | 2026-04-16 |
| PR-5 | ✅ 完成 | - | 2026-04-16 | 2026-04-16 |
| PR-6 | 待开始 | - | - | - |
| PR-7 | 待开始 | - | - | - |
| PR-8 | 待开始 | - | - | - |
