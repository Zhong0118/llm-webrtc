import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useWebRTCStore = defineStore('webrtc', () => {
  // 状态
  const peerConnection = ref(null)
  const remoteStream = ref(null)
  const connectionState = ref('disconnected')
  const connectionStats = ref({})
  const wsConnection = ref(null)
  
  // 计算属性
  const isConnected = computed(() => connectionState.value === 'connected')
  
  // 初始化WebRTC连接
  function initPeerConnection() {
    peerConnection.value = new RTCPeerConnection({
      iceServers: [
        { urls: 'stun:stun.l.google.com:19302' }
      ],
      iceCandidatePoolSize: 8
    })
    
    // 为服务端下发视频做准备：添加 recvonly 的视频收发器
    try {
      peerConnection.value.addTransceiver('video', { direction: 'recvonly' })
    } catch (e) {
      console.warn('添加视频收发器失败:', e)
    }
    
    // 监听 ICE 候选并通过信令发送（使用 toJSON 保证字段齐全）
    peerConnection.value.onicecandidate = (event) => {
      sendSignalingMessage({
        type: 'ice-candidate',
        candidate: event.candidate ? event.candidate.toJSON() : null,
      })
    }
    
    // 监听连接状态变化
    peerConnection.value.onconnectionstatechange = () => {
      connectionState.value = peerConnection.value.connectionState
    }
    
    // 监听远程流
    peerConnection.value.ontrack = (event) => {
      remoteStream.value = event.streams[0]
    }
  }
  
  // 初始化WebSocket连接
  function initWebSocket(serverUrl) {
    const isSecure = window.location.protocol === 'https:'
    const scheme = isSecure ? 'wss' : 'ws'
    // 使用 Vite 代理：HTTPS 页面走当前 host，HTTP 页面直连后端
    let wsUrl = ''
    if (isSecure) {
      wsUrl = `${scheme}://${window.location.host}/ws`
    } else {
      const host = serverUrl.replace(/^https?:\/\//, '')
      wsUrl = `${scheme}://${host}/ws`
    }
    wsConnection.value = new WebSocket(wsUrl)
    
    wsConnection.value.onopen = async () => {
      console.log('WebSocket连接已建立')
      connectionState.value = 'connecting'
      // 前端生成并发送 offer
      const offer = await peerConnection.value.createOffer()
      await peerConnection.value.setLocalDescription(offer)
      sendSignalingMessage({ type: 'offer', offer })
    }
    
    wsConnection.value.onmessage = async (event) => {
      const message = JSON.parse(event.data)
      
      if (message.type === 'answer') {
        await peerConnection.value.setRemoteDescription(new RTCSessionDescription(message.answer))
      } else if (message.type === 'ice-candidate') {
        if (message.candidate) {
          await peerConnection.value.addIceCandidate(new RTCIceCandidate(message.candidate))
        } else {
          await peerConnection.value.addIceCandidate(null)
        }
      }
    }
    
    wsConnection.value.onerror = (error) => {
      console.error('WebSocket错误:', error)
      connectionState.value = 'failed'
    }
    
    wsConnection.value.onclose = () => {
      console.log('WebSocket连接已关闭')
      if (isConnected.value) {
        stopConnection()
      }
    }
  }
  
  // 发送信令消息
  function sendSignalingMessage(message) {
    if (wsConnection.value && wsConnection.value.readyState === WebSocket.OPEN) {
      wsConnection.value.send(JSON.stringify(message))
    }
  }
  
  // 开始连接
  function startConnection(serverUrl) {
    if (peerConnection.value) {
      stopConnection()
    }
    
    initPeerConnection()
    initWebSocket(serverUrl)
  }
  
  // 停止连接
  function stopConnection() {
    if (peerConnection.value) {
      peerConnection.value.close()
      peerConnection.value = null
    }
    
    if (wsConnection.value) {
      wsConnection.value.close()
      wsConnection.value = null
    }
    
    remoteStream.value = null
    connectionState.value = 'disconnected'
    connectionStats.value = {}
  }
  
  // 获取连接统计信息
  async function getConnectionStats() {
    if (peerConnection.value && isConnected.value) {
      const stats = await peerConnection.value.getStats()
      const statsObj = {}
      
      stats.forEach(report => {
        if (report.type === 'inbound-rtp' && report.kind === 'video') {
          statsObj.bytesReceived = report.bytesReceived
          statsObj.packetsReceived = report.packetsReceived
          statsObj.packetsLost = report.packetsLost
          statsObj.jitter = report.jitter
          statsObj.framesDecoded = report.framesDecoded
          statsObj.framesDropped = report.framesDropped
        }
      })
      
      connectionStats.value = statsObj
    }
  }
  
  return {
    // 状态
    remoteStream,
    connectionState,
    connectionStats,
    isConnected,
    
    // 方法
    startConnection,
    stopConnection,
    getConnectionStats
  }
})