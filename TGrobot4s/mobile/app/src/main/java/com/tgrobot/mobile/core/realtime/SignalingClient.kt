package com.tgrobot.mobile.core.realtime

import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener

class SignalingClient(
    private val okHttpClient: OkHttpClient = OkHttpClient(),
) {
    interface Listener {
        fun onOpen()
        fun onMessage(text: String)
        fun onClosed(code: Int, reason: String)
        fun onFailure(error: Throwable)
    }

    private val lock = Any()
    private var webSocket: WebSocket? = null

    fun connect(url: String, listener: Listener) {
        synchronized(lock) {
            close()
            val request = Request.Builder()
                .url(url)
                .build()

            webSocket = okHttpClient.newWebSocket(
                request,
                object : WebSocketListener() {
                    override fun onOpen(webSocket: WebSocket, response: Response) {
                        listener.onOpen()
                    }

                    override fun onMessage(webSocket: WebSocket, text: String) {
                        listener.onMessage(text)
                    }

                    override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                        synchronized(lock) {
                            this@SignalingClient.webSocket = null
                        }
                        listener.onClosed(code, reason)
                    }

                    override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                        synchronized(lock) {
                            this@SignalingClient.webSocket = null
                        }
                        listener.onFailure(t)
                    }
                },
            )
        }
    }

    fun send(payload: String): Boolean {
        synchronized(lock) {
            return webSocket?.send(payload) == true
        }
    }

    fun close(code: Int = 1000, reason: String = "bye") {
        synchronized(lock) {
            webSocket?.close(code, reason)
            webSocket = null
        }
    }
}
