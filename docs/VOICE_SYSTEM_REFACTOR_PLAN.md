# 语音输入系统重构方案

## 一、项目概述

### 1.1 目标

将现有语音系统从单一 `SpeechRecognizer` 升级为可插拔、多厂商适配的语音输入基础设施。

### 1.2 核心需求

| 需求 | 说明 |
|------|------|
| 输入 | 用户说话完成 |
| 输出 | 完整文本（非流式） |
| 目标 | 发送给机器人执行 |
| 约束 | 多厂商适配 + ASR 可插拔 |

### 1.3 关键价值

- **厂商无感** - 业务层不关心设备差异
- **ASR 可插拔** - 运行时切换，零代码改动
- **业务零感知** - 只拿到最终文本
- **多级降级** - 4 层引擎保障可用性

---

## 二、当前架构（已完成重构）

### 2.1 重构完成状态

根据 `TGrobot4s/mobile/REFACTORING_PLAN.md`，已完成以下重构：

| PR | 状态 | 说明 |
|----|------|------|
| PR-1 | ✅ 完成 | 合并 Repository 和 Transport 层 |
| PR-2 | ✅ 完成 | 引入 MessageStore 模块 |
| PR-3 | ✅ 完成 | 封装 ControlEngine |
| PR-4 | ✅ 完成 | 引入 UseCase 层 |
| PR-5 | ✅ 完成 | 语音模块独立化 |
| PR-6 | ✅ 完成 | 引入 TeleopCoordinator |
| PR-7 | ✅ 完成 | 引入 RobotSessionManager |
| PR-8 | ✅ 完成 | 事件处理重构 |

### 2.2 当前架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    TeleopCoordinator (协调器)                    │
│                    协调 UseCase、VoiceModule、ControlEngine       │
└────────────────────────────┬────────────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        ↓                    ↓                    ↓
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│  VoiceModule  │    │ ControlEngine │    │  MessageStore │
│  (语音模块)    │    │  (控制引擎)    │    │  (消息存储)    │
└───────┬───────┘    └───────────────┘    └───────────────┘
        │
        ↓
┌─────────────────────────────────────────────────────────────────┐
│                    VoiceController                               │
│                    (SpeechRecognizer 封装)                       │
└─────────────────────────────────────────────────────────────────┘
        │
        ↓
┌─────────────────────────────────────────────────────────────────┐
│                 ProcessVoiceIntentUseCase                        │
│                 (语音意图处理)                                    │
└────────────────────────────┬────────────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        ↓                    ↓                    ↓
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│VoiceIntentParser│   │  RobotClient  │    │ VoiceIntent   │
│  (意图解析)     │    │  (机器人通信)  │    │ Result        │
└───────────────┘    └───────────────┘    └───────────────┘
```

### 2.3 当前文件结构

```
feature/voice/
├── VoiceController.kt          # SpeechRecognizer 封装
├── VoiceModule.kt              # 语音模块（新增）
├── VoiceModuleState.kt         # 模块状态（新增）
└── VoiceModuleEvent.kt         # 模块事件（新增）

domain/voice/
├── VoiceIntentCommand.kt       # 意图命令定义
├── VoiceIntentParser.kt        # 意图解析器
└── ActionCatalog.kt            # 动作目录

domain/usecase/
└── ProcessVoiceIntentUseCase.kt  # 语音意图处理用例（新增）

feature/control/
├── TeleopCoordinator.kt        # 协调器（新增）
├── TeleopViewModel.kt          # UI 状态容器（精简）
└── TeleopUiState.kt            # UI 状态定义
```

---

## 三、待实现：ASR 可插拔架构

### 3.1 目标架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    VoiceModule (业务入口)                        │
│                    startListening() / stopListening()            │
└────────────────────────────┬────────────────────────────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────────┐
│               VoicePipelineController (流程编排)                 │
│               协调采集 → 识别 → 输出                              │
└────────────┬───────────────────────────────────┬────────────────┘
             ↓                                   ↓
┌──────────────────────────┐    ┌──────────────────────────────────┐
│   VoiceAdapter Layer     │    │      ASR Engine Layer            │
│   (厂商适配层)            │    │      (可插拔识别层)               │
├──────────────────────────┤    ├──────────────────────────────────┤
│ AospVoiceAdapter         │    │ SystemAsrEngine (SpeechRecognizer)│
│ XiaomiVoiceAdapter       │    │ FunAsrEngine (自建云ASR)          │
│ HuaweiVoiceAdapter       │    │ WhisperEngine (离线/服务端)       │
│ OppoVoiceAdapter         │    │ VoskEngine (低端设备)             │
└──────────────────────────┘    └──────────────────────────────────┘
             ↓                                   ↓
┌─────────────────────────────────────────────────────────────────┐
│                    AsrRouter (路由决策)                          │
│                    根据设备/网络选择引擎                          │
└────────────────────────────┬────────────────────────────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────────┐
│                 ProcessVoiceIntentUseCase                        │
│                 Final Text → VoiceIntentParser → Robot           │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 数据流

```
用户说话
    ↓
VoiceAdapter (厂商适配)
    ↓
Audio PCM
    ↓
ASR Engine (可插拔)
    ↓
Final Text
    ↓
ProcessVoiceIntentUseCase
    ↓
VoiceIntentParser
    ↓
Robot Command
```

### 3.3 目标文件结构

```
feature/voice/
├── VoiceModule.kt                    # 修改：集成新架构
├── VoiceModuleState.kt               # 保留
├── VoiceModuleEvent.kt               # 保留
├── VoicePipelineController.kt        # 新增：流程编排
├── adapter/
│   ├── VoiceAdapter.kt               # 新增：适配接口
│   ├── AospVoiceAdapter.kt           # 新增：标准实现
│   ├── XiaomiVoiceAdapter.kt         # 新增：小米适配 (可选)
│   └── HuaweiVoiceAdapter.kt         # 新增：华为适配 (可选)
├── asr/
│   ├── AsrEngine.kt                  # 新增：ASR 接口
│   ├── AsrResult.kt                  # 新增：结果定义
│   ├── AsrRouter.kt                  # 新增：路由决策
│   ├── AsrRegistry.kt                # 新增：注册中心
│   ├── SystemAsrEngine.kt            # 新增：系统识别封装
│   ├── FunAsrEngine.kt               # 新增：FunASR
│   ├── WhisperEngine.kt              # 新增：Whisper (可选)
│   └── VoskEngine.kt                 # 新增：Vosk (可选)
└── policy/
    └── DevicePolicy.kt               # 新增：设备策略

domain/voice/
├── VoiceIntentCommand.kt             # 保留
├── VoiceIntentParser.kt              # 保留
└── ActionCatalog.kt                  # 保留

domain/usecase/
└── ProcessVoiceIntentUseCase.kt      # 保留
```

### 3.4 当前开发进度同步（2026-04-17）

| PR | 状态 | 同步说明 |
|----|------|---------|
| PR-1 | ✅ 已完成 | `VoiceAdapter`/`AsrEngine`/`AsrResult`/`AudioConfig` 已落地 |
| PR-2 | ✅ 已完成 | `AsrRegistry` + `AsrRouter` + `DevicePolicy` + `AsrMode` 已落地 |
| PR-3 | ✅ 已完成 | `AospVoiceAdapter` 完成录音、权限检查、生命周期管理 |
| PR-4 | ✅ 已完成 | `SystemAsrEngine` 完成 `SpeechRecognizer` 适配 |
| PR-5 | ✅ 已完成 | `VoicePipelineController` 完成会话编排与终态收口 |
| PR-6 | ✅ 已完成 | `VoiceModule` 与 `MainActivity` 已接入 pipeline |
| PR-7 | 🟡 代码已完成，待联调 | `FunAsrEngine` 与 `VolcAsrEngine` 已实现（待服务联调） |
| PR-8 | 🟡 代码已完成，待联调 | `WhisperEngine` 已实现 HTTP 转录链路 |
| PR-9 | 🟡 骨架已完成，待联调 | `VoskEngine` 已落地（反射接入 SDK，待模型与真机验证） |
| PR-10 | ⏳ 未开始 | 厂商专用适配尚未实现 |
| PR-11 | 🟡 进行中 | 已新增 `VOICE_SYSTEM_USAGE.md`，测试与 API 文档待补齐 |

本次本地验证：`TGrobot4s/mobile` 执行 `:app:compileDebugKotlin` 通过。

---

## 四、PR 任务拆分

### PR-1: 核心接口定义

**目标**: 定义 ASR 可插拔核心接口

**文件变更**:
```
feature/voice/
├── adapter/
│   └── VoiceAdapter.kt               # 新增
├── asr/
│   ├── AsrEngine.kt                  # 新增
│   └── AsrResult.kt                  # 新增
```

**任务清单**:
- [x] 定义 `VoiceAdapter` 接口
- [x] 定义 `AsrEngine` 接口
- [x] 定义 `AsrResult` 密封类
- [x] 定义 `AudioConfig` 配置类

**验收标准**:
- 接口编译通过
- 文档注释完整

---

### PR-2: ASR 注册与路由机制

**目标**: 实现 ASR 引擎的注册、发现、路由机制

**文件变更**:
```
feature/voice/asr/
├── AsrRegistry.kt                    # 新增
├── AsrRouter.kt                      # 新增
└── policy/
    └── DevicePolicy.kt               # 新增
```

**任务清单**:
- [x] 实现 `AsrRegistry` 注册中心
- [x] 实现 `AsrRouter` 路由决策
- [x] 实现 `DevicePolicy` 设备策略
- [x] 定义 `AsrMode` 枚举

**验收标准**:
- 支持动态注册/注销引擎
- 支持按策略选择引擎
- 单元测试覆盖

---

### PR-3: AOSP 标准音频采集

**目标**: 实现标准 Android 音频采集

**文件变更**:
```
feature/voice/adapter/
├── AospVoiceAdapter.kt               # 新增
```

**任务清单**:
- [x] 实现 `AudioRecord` 采集
- [x] 实现权限检查
- [x] 实现麦克风可用性检测
- [x] 实现资源生命周期管理

**验收标准**:
- 标准设备采集正常
- 权限检查正确
- 无内存泄漏

---

### PR-4: 系统 ASR 引擎封装

**目标**: 将 `SpeechRecognizer` 封装为 `AsrEngine`

**文件变更**:
```
feature/voice/asr/
├── SystemAsrEngine.kt                # 新增
```

**任务清单**:
- [x] 重构 `VoiceController` 为 `SystemAsrEngine`
- [x] 适配 `AsrEngine` 接口
- [x] 处理系统识别回调
- [x] 错误处理与降级

**验收标准**:
- 标准设备识别正常
- 错误正确传递
- 兼容 Android 8.0+

---

### PR-5: 流程编排器

**目标**: 实现语音采集→识别→输出的完整流程编排

**文件变更**:
```
feature/voice/
├── VoicePipelineController.kt        # 新增
```

**任务清单**:
- [x] 实现采集启动/停止
- [x] 实现 ASR 会话管理
- [x] 实现结果流转发
- [x] 实现错误处理

**验收标准**:
- 流程完整可运行
- 资源正确释放
- 异常情况处理

---

### PR-6: VoiceModule 集成

**目标**: 将新架构集成到 VoiceModule

**文件变更**:
```
feature/voice/
├── VoiceModule.kt                    # 修改
```

**任务清单**:
- [x] 集成 `VoicePipelineController`
- [x] 保持现有 API 兼容
- [x] 更新状态管理
- [x] 更新事件流

**验收标准**:
- API 向后兼容
- 功能与原有一致
- 无回归问题

---

### PR-7: FunASR 引擎实现

**目标**: 实现自建 FunASR 服务对接

**文件变更**:
```
feature/voice/asr/
├── FunAsrEngine.kt                   # 新增
```

**任务清单**:
- [x] 实现 WebSocket 连接
- [x] 实现音频流发送
- [x] 实现结果解析
- [x] 实现连接管理

**验收标准**:
- WebSocket 连接稳定
- 流式识别正常
- 断线重连

---

### PR-8: Whisper 引擎实现 (可选)

**目标**: 实现离线 Whisper 识别

**文件变更**:
```
feature/voice/asr/
├── WhisperEngine.kt                  # 新增
```

**任务清单**:
- [x] 实现 WebSocket/HTTP 调用
- [x] 实现音频格式转换
- [x] 实现结果解析

**验收标准**:
- 识别准确
- 延迟可接受

---

### PR-9: Vosk 引擎实现 (可选)

**目标**: 实现轻量级离线识别

**文件变更**:
```
feature/voice/asr/
├── VoskEngine.kt                     # 新增
```

**任务清单**:
- [ ] 集成 Vosk SDK
- [ ] 加载中文模型
- [ ] 实现流式识别

**验收标准**:
- 低端设备可运行
- 识别基本准确

---

### PR-10: 厂商适配优化 (可选)

**目标**: 针对特定厂商优化

**文件变更**:
```
feature/voice/adapter/
├── XiaomiVoiceAdapter.kt             # 新增
├── HuaweiVoiceAdapter.kt             # 新增
```

**任务清单**:
- [ ] 小米设备适配
- [ ] 华为设备适配
- [ ] OPPO/VIVO 适配

**验收标准**:
- 目标设备正常工作
- 无副作用

---

### PR-11: 测试与文档

**目标**: 完善测试和文档

**文件变更**:
```
test/
├── VoiceModuleTest.kt                # 新增
├── AsrRouterTest.kt                  # 新增
├── AospVoiceAdapterTest.kt           # 新增
docs/
├── VOICE_SYSTEM_USAGE.md             # 新增
```

**任务清单**:
- [ ] 单元测试
- [ ] 集成测试
- [x] 使用文档
- [ ] API 文档

**验收标准**:
- 测试覆盖率 > 70%
- 文档完整

---

## 五、实施计划

### 5.1 阶段划分

| 阶段 | PR | 时间 | 目标 |
|------|-----|------|------|
| Phase 1 | PR-1, PR-2 | 2天 | 核心框架 |
| Phase 2 | PR-3, PR-4 | 2天 | 基础实现 |
| Phase 3 | PR-5, PR-6 | 1天 | 流程集成 |
| Phase 4 | PR-7, PR-8, PR-9 | 3天 | 引擎扩展 |
| Phase 5 | PR-10, PR-11 | 2天 | 优化测试 |

### 5.2 依赖关系

```
PR-1 (接口定义)
  ├── PR-2 (注册路由)
  ├── PR-3 (音频采集)
  └── PR-4 (系统ASR)
        ↓
PR-5 (流程编排)
        ↓
PR-6 (VoiceModule集成)
        ↓
PR-7/8/9 (引擎扩展) ← 可并行
        ↓
PR-10/11 (优化测试)
```

---

## 六、风险与对策

### 6.1 技术风险

| 风险 | 等级 | 对策 |
|------|------|------|
| AudioRecord 权限问题 | 🔴 高 | 实际录音验证 + 错误提示 |
| SpeechRecognizer 不可用 | 🟡 中 | 多引擎降级 |
| FunASR 服务部署复杂 | 🟡 中 | 先用官方 Demo 验证 |
| Whisper 性能问题 | 🟡 中 | 服务端部署 |

### 6.2 兼容性风险

| 设备 | 问题 | 对策 |
|------|------|------|
| 小米 | SpeechRecognizer 不稳定 | 强制使用其他引擎 |
| 华为 | HMS 兼容 | AOSP 兜底 |
| OPPO/VIVO | 后台限制 | 前台服务 |

---

## 七、验收标准

### 7.1 功能验收

- [ ] 标准设备语音识别正常
- [ ] 小米设备语音识别正常
- [ ] 华为设备语音识别正常
- [ ] ASR 引擎可运行时切换
- [ ] 识别结果正确传递给机器人

### 7.2 性能验收

- [ ] 识别延迟 < 2s
- [ ] 内存占用 < 50MB
- [ ] 无内存泄漏

### 7.3 稳定性验收

- [ ] 连续使用 1 小时无崩溃
- [ ] 异常情况正确恢复
- [ ] 资源正确释放

---

## 八、附录

### 8.1 接口定义

#### VoiceAdapter

```kotlin
interface VoiceAdapter {
    fun isAvailable(): Boolean
    fun startRecording(onAudio: (ByteArray) -> Unit)
    fun stopRecording()
    fun release()
}
```

#### AsrEngine

```kotlin
interface AsrEngine {
    val name: String
    fun isAvailable(): Boolean
    fun startSession(): String
    fun sendAudio(sessionId: String, audio: ByteArray)
    fun observe(sessionId: String): Flow<AsrResult>
    fun endSession(sessionId: String)
}
```

#### AsrResult

```kotlin
sealed class AsrResult {
    data class Partial(val text: String) : AsrResult()
    data class Final(val text: String) : AsrResult()
    data class Error(val code: Int, val message: String) : AsrResult()
    
    val isFinal: Boolean get() = this is Final
    val text: String get() = when (this) {
        is Partial -> text
        is Final -> text
        is Error -> ""
    }
}
```

### 8.2 配置示例

```kotlin
// 初始化
val pipeline = VoicePipelineController(
    adapterProvider = { AospVoiceAdapter(context) },
    asrRouter = AsrRouter(AsrRegistry, DevicePolicy(context))
)

// 注册引擎
AsrRegistry.register(SystemAsrEngine(context))
AsrRegistry.register(FunAsrEngine("ws://your-server:10095"))

// VoiceModule 使用
val voiceModule = VoiceModule(
    context = context,
    processVoiceIntentUseCase = processVoiceIntentUseCase,
    pipeline = pipeline
)

// 使用
voiceModule.startListening()
scope.launch {
    voiceModule.commandResults.collect { result ->
        // 处理语音命令结果
    }
}
```

---

## 九、变更记录

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.0 | 2024-01-XX | 初始方案 |
| v1.1 | 2026-04-17 | 根据移动端重构更新架构，调整 PR 任务 |
| v1.2 | 2026-04-17 | 同步 PR 落地进度，补充本地编译验证结果 |
| v1.3 | 2026-04-17 | 增加 VoskEngine 骨架实现并同步 PR-9 进度 |
| v1.4 | 2026-04-17 | 新增 VOICE_SYSTEM_USAGE 使用文档并同步 PR-11 进度 |
| v1.5 | 2026-04-17 | 增加可配置 ASR 引擎注册（BuildConfig/gradle.properties） |
| v1.6 | 2026-04-17 | 新增 VolcAsrEngine（火山流式 ASR）并接入配置注册 |
