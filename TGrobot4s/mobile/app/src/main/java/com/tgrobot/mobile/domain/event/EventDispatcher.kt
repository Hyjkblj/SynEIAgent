package com.tgrobot.mobile.domain.event

import com.tgrobot.mobile.core.model.RobotEvent
import com.tgrobot.mobile.domain.message.MessageStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancel
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.launch

/**
 * Dispatches robot events through a single serial consumer.
 */
class EventDispatcher(
    private val messageStore: MessageStore,
    private val scope: CoroutineScope = CoroutineScope(Dispatchers.Default),
) {
    private val handlers = mutableListOf<RobotEventHandler>()
    private val eventQueue = Channel<RobotEvent>(capacity = Channel.UNLIMITED)
    private val _processedEvents = MutableSharedFlow<ProcessedEvent>(extraBufferCapacity = 64)
    val processedEvents: SharedFlow<ProcessedEvent> = _processedEvents.asSharedFlow()

    private var deltaBuffer = StringBuilder()
    private val consumeJob: Job = scope.launch {
        for (event in eventQueue) {
            handlers.toList().forEach { handler ->
                handler.handle(event)
            }
            handleCommonEvent(event)
        }
    }

    fun registerHandler(handler: RobotEventHandler) {
        handlers.add(handler)
    }

    fun unregisterHandler(handler: RobotEventHandler) {
        handlers.remove(handler)
    }

    fun dispatch(event: RobotEvent) {
        eventQueue.trySend(event)
    }

    private suspend fun handleCommonEvent(event: RobotEvent) {
        when (event) {
            is RobotEvent.Message -> {
                flushDeltaBuffer()
                messageStore.addRobotMessage(event.content)
                _processedEvents.emit(ProcessedEvent.Message(event.content))
            }

            is RobotEvent.MessageDelta -> {
                if (event.content.isNotBlank()) {
                    deltaBuffer.append(event.content)
                }
                if (event.end) {
                    flushDeltaBuffer()
                }
            }

            is RobotEvent.Transcription -> {
                messageStore.addSystemMessage("Transcription: ${event.content}")
                _processedEvents.emit(ProcessedEvent.Transcription(event.content))
            }

            is RobotEvent.Error -> {
                messageStore.addSystemMessage("Error: ${event.content}")
                _processedEvents.emit(ProcessedEvent.Error(event.content))
            }

            is RobotEvent.Alert -> {
                val codePart = event.errorCode?.let { " code=$it" } ?: ""
                messageStore.addSystemMessage("Alert[${event.level}]$codePart ${event.content}")
                _processedEvents.emit(ProcessedEvent.Alert(event.level, event.errorCode, event.content))
            }

            is RobotEvent.JoystickAck -> {
                _processedEvents.emit(
                    ProcessedEvent.JoystickAck(
                        ts = event.ts,
                        reason = event.reason,
                    ),
                )
            }

            is RobotEvent.ControlAck -> {
                _processedEvents.emit(
                    ProcessedEvent.ControlAck(
                        ts = event.ts,
                        reason = event.reason,
                    ),
                )
            }

            is RobotEvent.GatewayEvent -> {
                handleGatewayEvent(event)
            }
        }
    }

    private suspend fun handleGatewayEvent(event: RobotEvent.GatewayEvent) {
        when (event.name) {
            "state_changed" -> {
                val oldState = event.oldState ?: "unknown"
                val newState = event.state ?: "unknown"
                messageStore.addSystemMessage("Gateway state: $oldState -> $newState")
            }

            "command_applied" -> {
                val kind = event.kind ?: "unknown"
                val source = event.source ?: "unknown"
                messageStore.addSystemMessage("Command applied: $kind from $source")
            }

            else -> {
                messageStore.addSystemMessage("Gateway event: ${event.name}")
            }
        }
        _processedEvents.emit(ProcessedEvent.Gateway(event.name, event.state, event.kind))
    }

    private suspend fun flushDeltaBuffer() {
        if (deltaBuffer.isEmpty()) return
        messageStore.addRobotMessage(deltaBuffer.toString())
        deltaBuffer = StringBuilder()
    }

    fun clear() {
        handlers.clear()
        deltaBuffer = StringBuilder()
        eventQueue.close()
        consumeJob.cancel()
        scope.cancel()
    }
}

sealed interface ProcessedEvent {
    data class Message(val content: String) : ProcessedEvent
    data class Transcription(val content: String) : ProcessedEvent
    data class Error(val content: String) : ProcessedEvent
    data class Alert(val level: String, val errorCode: Int?, val content: String) : ProcessedEvent
    data class JoystickAck(val ts: Long?, val reason: String) : ProcessedEvent
    data class ControlAck(val ts: Long?, val reason: String) : ProcessedEvent
    data class Gateway(val name: String, val state: String?, val kind: String?) : ProcessedEvent
}

