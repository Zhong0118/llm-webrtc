import { ref, reactive, onUnmounted } from 'vue'
import { defineStore } from 'pinia'
import { useSocketStore } from './useSocketStore'
import { ElMessage } from 'element-plus'

const AI_NAMESPACE = '/ai_analysis'

export const useAIStore = defineStore('ai', () => {
  const socketStore = useSocketStore()
  const aiSocket = ref(null)
  const pc = ref(null)

  const isConnected = ref(false)
  const isSending = ref(false)
  const isReceiving = ref(false)

  const resultsMap = reactive({})

  const netStats = reactive({ rtt: 0, bitrate: 0, fps: 0, packetLoss: 0 })
  let statsTimer = null
  let prevBytesSent = 0
  let prevTimestamp = 0

  const ensureSocketConnected = async (socket) => {
    if (socket.connected) return
    try {
      await new Promise((resolve, reject) => {
        const timeout = setTimeout(() => reject(new Error('AI Socket 连接超时')), 5000)
        socket.once('connect', () => { clearTimeout(timeout); resolve() })
        socket.once('connect_error', (err) => { clearTimeout(timeout); reject(err) })
      })
    } catch (err) {
      throw new Error(`AI 服务连接失败: ${err.message}`)
    }
  }

  const setupResultListener = (socket) => {
    socket.off('ai_result');
    socket.on('ai_result', (data) => {
      if (data && data.peerId) {
        resultsMap[data.peerId] = data;
      }
    });
  }
  const joinAIRoomOnly = async (roomId) => {
    if (!roomId) return
    aiSocket.value = socketStore.getSocket(AI_NAMESPACE)
    try {
      await ensureSocketConnected(aiSocket.value)
      setupResultListener(aiSocket.value)
      aiSocket.value.emit('join', { roomId })
      isReceiving.value = true
    } catch (err) {
      console.error(err)
    }
  }
  const connectAI = async (stream, roomId, myPeerId) => {
    if (isConnected.value) return
    if (!stream || !myPeerId) {
      ElMessage.warning('启动 AI 失败：缺少流或 PeerID')
      return
    }

    // 确保流有轨道
    if (stream.getVideoTracks().length === 0) {
      ElMessage.error('启动 AI 失败：视频流没有轨道')
      return
    }

    aiSocket.value = socketStore.getSocket(AI_NAMESPACE)

    try {
      await ensureSocketConnected(aiSocket.value)
      setupResultListener(aiSocket.value)

      aiSocket.value.emit('join', { roomId })
      isReceiving.value = true

      pc.value = new RTCPeerConnection({
        iceServers: [{ urls: 'stun:stun.l.google.com:19302' }],
      })

      aiSocket.value.on('answer', async (data) => {
        if (pc.value) await pc.value.setRemoteDescription(data.answer)
      })

      aiSocket.value.on('candidate', async (data) => {
        if (pc.value && data.candidate) await pc.value.addIceCandidate(data.candidate)
      })

      pc.value.onicecandidate = (event) => {
        if (event.candidate) aiSocket.value.emit('candidate', { candidate: event.candidate.toJSON() })
        else aiSocket.value.emit('candidate', { candidate: null })
      }

      pc.value.onconnectionstatechange = () => {
        if (pc.value.connectionState === 'connected') {
          isConnected.value = true
          isSending.value = true
          startStatsLoop()
          ElMessage.success('AI 推流已建立')
        } else if (['disconnected', 'failed', 'closed'].includes(pc.value.connectionState)) {
          stopStreaming()
        }
      }

      stream.getTracks().forEach((track) => {
        if (track.kind === 'video') pc.value.addTrack(track, stream)
      })

      const offer = await pc.value.createOffer()
      await pc.value.setLocalDescription(offer)

      aiSocket.value.emit('offer', {
        offer: offer,
        roomId: roomId,
        peerId: myPeerId
      })

    } catch (err) {
      console.error(err)
      ElMessage.error(`AI 连接失败: ${err.message}`)
      stopStreaming()
    }
  }

  const startStatsLoop = () => {
    if (statsTimer) clearInterval(statsTimer)
    prevBytesSent = 0
    prevTimestamp = performance.now()
    statsTimer = setInterval(async () => {
      if (!pc.value || pc.value.connectionState !== 'connected') return
      try {
        const reports = await pc.value.getStats()
        for (const report of reports.values()) {
          if (report.type === 'candidate-pair' && report.state === 'succeeded') {
            netStats.rtt = report.currentRoundTripTime ? Math.round(report.currentRoundTripTime * 1000) : 0
          }
          if (report.type === 'outbound-rtp' && report.kind === 'video') {
            const now = report.timestamp
            const bytes = report.bytesSent
            if (prevTimestamp > 0 && now > prevTimestamp) {
              netStats.bitrate = Math.round(((bytes - prevBytesSent) * 8) / (now - prevTimestamp))
            }
            netStats.fps = report.framesPerSecond || 0
            netStats.packetLoss = report.packetsSent ? ((report.retransmittedPacketsSent || 0) / report.packetsSent * 100).toFixed(2) : 0
            prevBytesSent = bytes
            prevTimestamp = now
          }
        }
      } catch (e) { }
    }, 1000)
  }

  const stopStreaming = () => {
    if (statsTimer) {
        clearInterval(statsTimer)
        statsTimer = null
    }
    if (pc.value) {
      pc.value.close()
      pc.value = null
    }
    isConnected.value = false
    isSending.value = false
    netStats.rtt = 0
    // 注意：这里千万不要 off 掉 socket 事件，也不要清空 resultsMap
    console.log("AI 推流已停止 (接收服务保持)");
  }

// 【核心修复】彻底断开 (离开房间用)
  const disconnectAll = () => {
    stopStreaming() // 先停推流
    
    // 再停接收
    for (const key in resultsMap) delete resultsMap[key];
    isReceiving.value = false
    
    if (aiSocket.value) {
      aiSocket.value.off('ai_result')
      aiSocket.value.off('answer')
      aiSocket.value.off('candidate')
      // 不调用 socket.disconnect()，交给 SocketStore 管理复用
    }
    console.log("AI 服务完全断开");
  }

  onUnmounted(() => { disconnectAll() })

  return {
    isConnected, isSending, isReceiving, resultsMap, netStats,
    connectAI, joinAIRoomOnly, disconnectAll, stopStreaming
  }
})