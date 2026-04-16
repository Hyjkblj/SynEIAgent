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

## 二、架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    VoiceFacade (业务唯一入口)                    │
│                    start() / stop() / observe()                 │
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
│                 Unified Result (统一输出)                        │
│                 Final Text → VoiceIntentParser → Robot           │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 数据流

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
VoiceIntentParser
    ↓
Robot Command
```

### 2.3 文件结构

```
feature/voice/
├── VoiceFacade.kt                    # 业务入口
├── VoicePipelineController.kt        # 流程编排
├── adapter/
│   ├── VoiceAdapter.kt               # 适配接口
│   ├── AospVoiceAdapter.kt           # 标准实现
│   ├── XiaomiVoiceAdapter.kt         # 小米适配 (可选)
│   └── HuaweiVoiceAdapter.kt         # 华为适配 (可选)
├── asr/
│   ├── AsrEngine.kt                  # ASR 接口
│   ├── AsrResult.kt                  # 结果定义
│   ├── AsrRouter.kt                  # 路由决策
│   ├── AsrRegistry.kt                # 注册中心
│   ├── SystemAsrEngine.kt            # 系统识别
│   ├── FunAsrEngine.kt               # FunASR
│   ├── WhisperEngine.kt              # Whisper (可选)
│   └── VoskEngine.kt                 # Vosk (可选)
└── policy/
    └── DevicePolicy.kt               # 设备策略

domain/voice/
├── VoiceIntentCommand.kt             # 保留
├── VoiceIntentParser.kt              # 保留
└── ActionCatalog.kt                  # 保留
```

---

## 三、PR 任务拆分

### PR-1: 核心接口定义

**目标**: 定义系统核心接口，建立抽象层

**文件变更**:
```
feature/voice/
├── VoiceAdapter.kt                   # 新增
├── asr/
│   ├── AsrEngine.kt                  # 新增
│   └── AsrResult.kt                  # 新增
```

**任务清单**:
- [ ] 定义 `VoiceAdapter` 接口
- [ ] 定义 `AsrEngine` 接口
- [ ] 定义 `AsrResult` 密封类
- [ ] 定义 `AudioConfig` 配置类

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
- [ ] 实现 `AsrRegistry` 注册中心
- [ ] 实现 `AsrRouter` 路由决策
- [ ] 实现 `DevicePolicy` 设备策略
- [ ] 定义 `AsrMode` 枚举

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
- [ ] 实现 `AudioRecord` 采集
- [ ] 实现权限检查
- [ ] 实现麦克风可用性检测
- [ ] 实现资源生命周期管理

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
- [ ] 实现 `SpeechRecognizer` 封装
- [ ] 适配 `AsrEngine` 接口
- [ ] 处理系统识别回调
- [ ] 错误处理与降级

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
- [ ] 实现采集启动/停止
- [ ] 实现 ASR 会话管理
- [ ] 实现结果流转发
- [ ] 实现错误处理

**验收标准**:
- 流程完整可运行
- 资源正确释放
- 异常情况处理

---

### PR-6: 业务入口封装

**目标**: 提供业务层唯一入口

**文件变更**:
```
feature/voice/
├── VoiceFacade.kt                    # 新增
```

**任务清单**:
- [ ] 实现 `start()` / `stop()` / `release()`
- [ ] 实现结果流暴露
- [ ] 实现状态管理
- [ ] 集成 `VoicePipelineController`

**验收标准**:
- API 简洁易用
- 状态正确同步
- 线程安全

---

### PR-7: FunASR 引擎实现

**目标**: 实现自建 FunASR 服务对接

**文件变更**:
```
feature/voice/asr/
├── FunAsrEngine.kt                   # 新增
```

**任务清单**:
- [ ] 实现 WebSocket 连接
- [ ] 实现音频流发送
- [ ] 实现结果解析
- [ ] 实现连接管理

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
- [ ] 实现 WebSocket/HTTP 调用
- [ ] 实现音频格式转换
- [ ] 实现结果解析

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

### PR-10: 业务层集成

**目标**: 将新系统集成到现有业务

**文件变更**:
```
feature/control/
├── TeleopViewModel.kt                # 修改
feature/voice/
├── VoiceController.kt                # 废弃/保留
MainActivity.kt                       # 修改
```

**任务清单**:
- [ ] 替换 `VoiceController` 为 `VoiceFacade`
- [ ] 更新 `TeleopViewModel` 调用
- [ ] 更新 `MainActivity` 初始化
- [ ] 保留旧代码作为降级

**验收标准**:
- 功能与原有一致
- 兼容现有流程
- 无回归问题

---

### PR-11: 厂商适配优化 (可选)

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

### PR-12: 测试与文档

**目标**: 完善测试和文档

**文件变更**:
```
test/
├── VoiceFacadeTest.kt                # 新增
├── AsrRouterTest.kt                  # 新增
├── AospVoiceAdapterTest.kt           # 新增
docs/
├── VOICE_SYSTEM_USAGE.md             # 新增
```

**任务清单**:
- [ ] 单元测试
- [ ] 集成测试
- [ ] 使用文档
- [ ] API 文档

**验收标准**:
- 测试覆盖率 > 70%
- 文档完整

---

## 四、实施计划

### 4.1 阶段划分

| 阶段 | PR | 时间 | 目标 |
|------|-----|------|------|
| Phase 1 | PR-1, PR-2 | 2天 | 核心框架 |
| Phase 2 | PR-3, PR-4 | 2天 | 基础实现 |
| Phase 3 | PR-5, PR-6 | 1天 | 流程集成 |
| Phase 4 | PR-7, PR-8, PR-9 | 3天 | 引擎扩展 |
| Phase 5 | PR-10 | 1天 | 业务集成 |
| Phase 6 | PR-11, PR-12 | 2天 | 优化测试 |

### 4.2 依赖关系

```
PR-1 (接口定义)
  ├── PR-2 (注册路由)
  ├── PR-3 (音频采集)
  └── PR-4 (系统ASR)
        ↓
PR-5 (流程编排)
        ↓
PR-6 (业务入口)
        ↓
PR-7/8/9 (引擎扩展) ← 可并行
        ↓
PR-10 (业务集成)
        ↓
PR-11/12 (优化测试)
```

---

## 五、风险与对策

### 5.1 技术风险

| 风险 | 等级 | 对策 |
|------|------|------|
| AudioRecord 权限问题 | 🔴 高 | 实际录音验证 + 错误提示 |
| SpeechRecognizer 不可用 | 🟡 中 | 多引擎降级 |
| FunASR 服务部署复杂 | 🟡 中 | 先用官方 Demo 验证 |
| Whisper 性能问题 | 🟡 中 | 服务端部署 |

### 5.2 兼容性风险

| 设备 | 问题 | 对策 |
|------|------|------|
| 小米 | SpeechRecognizer 不稳定 | 强制使用其他引擎 |
| 华为 | HMS 兼容 | AOSP 兜底 |
| OPPO/VIVO | 后台限制 | 前台服务 |

---

## 六、验收标准

### 6.1 功能验收

- [ ] 标准设备语音识别正常
- [ ] 小米设备语音识别正常
- [ ] 华为设备语音识别正常
- [ ] ASR 引擎可运行时切换
- [ ] 识别结果正确传递给机器人

### 6.2 性能验收

- [ ] 识别延迟 < 2s
- [ ] 内存占用 < 50MB
- [ ] 无内存泄漏

### 6.3 稳定性验收

- [ ] 连续使用 1 小时无崩溃
- [ ] 异常情况正确恢复
- [ ] 资源正确释放

---

## 七、附录

### 7.1 接口定义

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

### 7.2 配置示例

```kotlin
// 初始化
val facade = VoiceFacade(
    VoicePipelineController(
        adapterProvider = { AospVoiceAdapter(context) },
        asrRouter = AsrRouter(AsrRegistry, DevicePolicy(context))
    )
)

// 注册引擎
AsrRegistry.register(SystemAsrEngine(context))
AsrRegistry.register(FunAsrEngine("ws://your-server:10095"))

// 使用
facade.start()
scope.launch {
    facade.result.collect { result ->
        when (result) {
            is VoiceResult.Success -> sendToRobot(result.text)
            is VoiceResult.Error -> showError(result.message)
        }
    }
}
```

---

## 八、变更记录

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.0 | 2024-01-XX | 初始方案 |
