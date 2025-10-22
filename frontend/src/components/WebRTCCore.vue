<template>
  <div class="webrtc-core">
    <el-card class="box-card">
      <template #header>
        <div class="card-header">
          <span>房间双人通话</span>
          <el-tag :type="connectionState === 'connected' ? 'success' : (connectionState === 'failed' ? 'danger' : 'info')">
            {{ connectionState }}
          </el-tag>
        </div>
      </template>
      
      <el-alert 
        title="使用说明" 
        type="info" 
        :closable="false"
        style="margin-bottom: 16px;"
      >
        <p><strong>房间ID：</strong>双方必须输入相同的房间ID才能在同一房间通话</p>
        <p><strong>我的ID：</strong>你在房间中的唯一标识，对方需要知道这个ID来呼叫你</p>
        <p><strong>对端ID：</strong>对方的ID，填写后可以主动呼叫对方（对方接到offer后会自动填充）</p>
        <p><strong>流程：</strong>1) 生成房间ID → 2) 复制邀请链接发给对方 → 3) 双方加入房间 → 4) 任一方发起呼叫</p>
        <p><strong>跨设备连接：</strong>确保其他设备可以访问 <code>{{ currentHost }}:8000</code>（后端服务器地址）</p>
      </el-alert>
      
      <el-form label-width="100px" class="room-form">
        <el-form-item label="房间ID">
          <el-input v-model="roomId" placeholder="双方必须相同的房间ID">
            <template #append>
              <el-button @click="generateRoomId">生成</el-button>
            </template>
          </el-input>
        </el-form-item>
        <el-form-item label="我的ID">
          <el-input v-model="myPeerId" placeholder="你的唯一标识" />
        </el-form-item>
        <el-form-item label="对端ID">
          <el-input v-model="targetPeerId" placeholder="对方的ID（可选，呼叫时需要）" />
        </el-form-item>
        
        <el-form-item>
          <el-space>
            <el-button type="primary" :disabled="joined" @click="joinRoom">加入房间</el-button>
            <el-button :disabled="!joined" @click="leaveRoom">离开房间</el-button>
            <el-button type="success" :disabled="!joined || calling || !targetPeerId" @click="startCall">呼叫</el-button>
            <el-button type="warning" :disabled="!calling" @click="hangup">挂断</el-button>
            <el-button @click="copyInviteLink" :disabled="!roomId">复制邀请链接</el-button>
          </el-space>
        </el-form-item>
      </el-form>
      
      <div class="videos">
        <el-card class="video-card" shadow="never">
          <template #header>
            <span>本地视频</span>
          </template>
          <video ref="localVideoEl" autoplay playsinline muted class="video" />
        </el-card>
        
        <el-card class="video-card" shadow="never">
          <template #header>
            <span>远端视频</span>
          </template>
          <video ref="remoteVideoEl" autoplay playsinline class="video" />
        </el-card>
      </div>

      <el-card class="stats-card" shadow="never" v-if="calling">
        <template #header>
          <span>连接统计</span>
        </template>
        <el-descriptions :column="3" size="small" border>
          <el-descriptions-item label="入方向码率(kbps)">{{ stats.inbound.bitrateKbps }}</el-descriptions-item>
          <el-descriptions-item label="入方向FPS">{{ stats.inbound.framesPerSecond }}</el-descriptions-item>
          <el-descriptions-item label="入方向丢包">{{ stats.inbound.packetsLost }}</el-descriptions-item>
          <el-descriptions-item label="出方向码率(kbps)">{{ stats.outbound.bitrateKbps }}</el-descriptions-item>
          <el-descriptions-item label="出方向FPS">{{ stats.outbound.framesPerSecond }}</el-descriptions-item>
          <el-descriptions-item label="ICE RTT(ms)">{{ stats.ice.roundTripTimeMs }}</el-descriptions-item>
          <el-descriptions-item label="本地候选">{{ stats.ice.localCandidateType }}</el-descriptions-item>
          <el-descriptions-item label="远端候选">{{ stats.ice.remoteCandidateType }}</el-descriptions-item>
        </el-descriptions>
      </el-card>
    </el-card>
  </div>
</template>

<script>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { ElMessage } from 'element-plus'

export default {
  name: 'WebRTCCore',
  setup() {
    const roomId = ref('')
    const myPeerId = ref(Math.random().toString(36).slice(2, 10))
    const targetPeerId = ref('')
    const joined = ref(false)
    const calling = ref(false)
    const connectionState = ref('disconnected')

    const localVideoEl = ref(null)
    const remoteVideoEl = ref(null)

    const pc = ref(null)
    const localStream = ref(null)
    const remoteStream = ref(null)

    // 计算当前主机地址，用于显示服务器信息
    const currentHost = computed(() => {
      return window.location.hostname
    })
    const stats = ref({
      inbound: { bitrateKbps: 0, framesPerSecond: 0, bytesReceived: 0, packetsReceived: 0, packetsLost: 0, jitter: 0 },
      outbound: { bitrateKbps: 0, framesPerSecond: 0, bytesSent: 0, packetsSent: 0 },
      ice: { localCandidateType: '', remoteCandidateType: '', roundTripTimeMs: 0 }
    })
    let statsTimer = null
    const prev = { inboundBytes: 0, inboundTimestamp: 0, inboundFrames: 0, outboundBytes: 0, outboundTimestamp: 0, outboundFrames: 0 }

    let ws = null

    const initPeer = async () => {
      pc.value = new RTCPeerConnection({
        iceServers: [
          { urls: 'stun:stun.l.google.com:19302' }
        ],
        iceCandidatePoolSize: 8
      })

      pc.value.onconnectionstatechange = () => {
        connectionState.value = pc.value.connectionState
      }

      pc.value.ontrack = (event) => {
        remoteStream.value = event.streams[0]
        if (remoteVideoEl.value) {
          remoteVideoEl.value.srcObject = remoteStream.value
        }
      }

      pc.value.onicecandidate = (event) => {
        const candidate = event.candidate ? event.candidate.toJSON() : null
        if (ws && ws.readyState === WebSocket.OPEN && joined.value && targetPeerId.value) {
          ws.send(JSON.stringify({
            type: 'ice-candidate',
            roomId: roomId.value,
            from: myPeerId.value,
            to: targetPeerId.value,
            candidate
          }))
        }
      }

      try {
        localStream.value = await navigator.mediaDevices.getUserMedia({ video: true, audio: true })
        if (localVideoEl.value) {
          localVideoEl.value.srcObject = localStream.value
        }
        localStream.value.getTracks().forEach(t => pc.value.addTrack(t, localStream.value))
      } catch (err) {
        ElMessage.error(`获取摄像头/麦克风失败: ${err}`)
      }
    }

    const updateStats = async () => {
      if (!pc.value) return
      const reports = await pc.value.getStats()
      let inboundRtp = null
      let outboundRtp = null
      let selectedPair = null
      const reportMap = new Map()
      reports.forEach(r => reportMap.set(r.id, r))
      reports.forEach(report => {
        if (report.type === 'inbound-rtp' && report.kind === 'video') inboundRtp = report
        if (report.type === 'outbound-rtp' && report.kind === 'video') outboundRtp = report
        if (report.type === 'candidate-pair' && (report.selected || report.nominated || report.state === 'succeeded')) selectedPair = report
      })
      if (inboundRtp) {
        const nowBytes = inboundRtp.bytesReceived || 0
        const ts = inboundRtp.timestamp || performance.now()
        const deltaMs = prev.inboundTimestamp ? (ts - prev.inboundTimestamp) : 0
        const deltaBytes = prev.inboundTimestamp ? (nowBytes - prev.inboundBytes) : 0
        stats.value.inbound.bytesReceived = nowBytes
        stats.value.inbound.packetsReceived = inboundRtp.packetsReceived || 0
        stats.value.inbound.packetsLost = inboundRtp.packetsLost || 0
        stats.value.inbound.jitter = inboundRtp.jitter || 0
        stats.value.inbound.framesPerSecond = inboundRtp.framesPerSecond || (prev.inboundTimestamp ? Math.max(0, Math.round(((inboundRtp.framesDecoded || 0) - prev.inboundFrames) / (deltaMs / 1000))) : 0)
        stats.value.inbound.bitrateKbps = deltaMs > 0 ? Math.max(0, Math.round((deltaBytes * 8) / deltaMs)) : 0
        prev.inboundFrames = inboundRtp.framesDecoded || prev.inboundFrames
        prev.inboundBytes = nowBytes
        prev.inboundTimestamp = ts
      }
      if (outboundRtp) {
        const nowBytes = outboundRtp.bytesSent || 0
        const ts = outboundRtp.timestamp || performance.now()
        const deltaMs = prev.outboundTimestamp ? (ts - prev.outboundTimestamp) : 0
        const deltaBytes = prev.outboundTimestamp ? (nowBytes - prev.outboundBytes) : 0
        stats.value.outbound.bytesSent = nowBytes
        stats.value.outbound.packetsSent = outboundRtp.packetsSent || 0
        stats.value.outbound.framesPerSecond = outboundRtp.framesPerSecond || (prev.outboundTimestamp ? Math.max(0, Math.round(((outboundRtp.framesEncoded || 0) - prev.outboundFrames) / (deltaMs / 1000))) : 0)
        stats.value.outbound.bitrateKbps = deltaMs > 0 ? Math.max(0, Math.round((deltaBytes * 8) / deltaMs)) : 0
        prev.outboundFrames = outboundRtp.framesEncoded || prev.outboundFrames
        prev.outboundBytes = nowBytes
        prev.outboundTimestamp = ts
      }
      if (selectedPair) {
        stats.value.ice.roundTripTimeMs = Math.round(((selectedPair.currentRoundTripTime || 0) * 1000))
        const local = reportMap.get(selectedPair.localCandidateId)
        const remote = reportMap.get(selectedPair.remoteCandidateId)
        stats.value.ice.localCandidateType = local ? local.candidateType : ''
        stats.value.ice.remoteCandidateType = remote ? remote.candidateType : ''
      }
    }

    const startStats = () => {
      if (statsTimer) return
      statsTimer = setInterval(updateStats, 1000)
    }

    const stopStats = () => {
      if (statsTimer) {
        clearInterval(statsTimer)
        statsTimer = null
      }
    }

    const generateRoomId = () => {
      roomId.value = Math.random().toString(36).slice(2, 8).toUpperCase()
      ElMessage.success(`已生成房间ID：${roomId.value}`)
    }

    const inviteUrl = () => {
      // 使用当前页面的完整URL作为基础
      const baseUrl = `${window.location.protocol}//${window.location.host}${window.location.pathname}`
      return `${baseUrl}?room=${encodeURIComponent(roomId.value)}&target=${encodeURIComponent(myPeerId.value)}`
    }
    
    const copyInviteLink = async () => {
      if (!roomId.value) {
        ElMessage.warning('请先生成或填写房间ID')
        return
      }
      try {
        await navigator.clipboard.writeText(inviteUrl())
        ElMessage.success('邀请链接已复制到剪贴板')
      } catch (_) {
        ElMessage.info(`邀请链接：${inviteUrl()}`)
      }
    }

    const joinRoom = async () => {
      if (joined.value) return
      if (!roomId.value || !roomId.value.trim()) {
        ElMessage.warning('请先填写或生成房间ID')
        return
      }
      
      // 动态获取WebSocket地址 - 根据当前访问协议自动选择ws或wss
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const host = window.location.hostname // 动态获取当前主机地址
      const port = '8000' // 后端端口
      const wsUrl = `${protocol}//${host}:${port}/ws-room`
      
      ws = new WebSocket(wsUrl)

      ws.onopen = async () => {
        ws.send(JSON.stringify({ type: 'join', roomId: roomId.value, peerId: myPeerId.value }))
        await initPeer()
        joined.value = true
        startStats()
        ElMessage.success(`已加入房间：${roomId.value}`)
      }

      ws.onmessage = async (event) => {
        const message = JSON.parse(event.data)
        if (message.type === 'joined') {
          // room ack
        } else if (message.type === 'offer') {
          const fromPeer = message.from
          targetPeerId.value = fromPeer
          ElMessage.info(`收到来自 ${fromPeer} 的呼叫`)
          await pc.value.setRemoteDescription(new RTCSessionDescription(message.offer))
          const answer = await pc.value.createAnswer()
          await pc.value.setLocalDescription(answer)
          ws.send(JSON.stringify({ type: 'answer', roomId: roomId.value, from: myPeerId.value, to: fromPeer, answer }))
          calling.value = true
        } else if (message.type === 'answer') {
          await pc.value.setRemoteDescription(new RTCSessionDescription(message.answer))
          calling.value = true
          ElMessage.success('通话已建立')
        } else if (message.type === 'ice-candidate') {
          const candidate = message.candidate
          await pc.value.addIceCandidate(candidate ? new RTCIceCandidate(candidate) : null)
        } else if (message.type === 'error') {
          ElMessage.error(message.message || '信令错误')
        }
      }

      ws.onclose = () => {
        joined.value = false
        calling.value = false
        stopStats()
        ElMessage.warning('已断开房间连接')
      }

      ws.onerror = (error) => {
        console.error('WebSocket错误:', error)
        ElMessage.error(`WebSocket连接错误，请确保后端服务器在 ${host}:${port} 运行`)
      }
    }

    const startCall = async () => {
      if (!pc.value || !joined.value || !targetPeerId.value) {
        ElMessage.warning('请先加入房间并填写对端ID')
        return
      }
      const offer = await pc.value.createOffer()
      await pc.value.setLocalDescription(offer)
      ws.send(JSON.stringify({ type: 'offer', roomId: roomId.value, from: myPeerId.value, to: targetPeerId.value, offer }))
      ElMessage.info(`正在呼叫 ${targetPeerId.value}...`)
    }

    const hangup = () => {
      if (pc.value) {
        pc.value.getSenders().forEach(s => s.track && s.track.stop())
        pc.value.close()
        pc.value = null
      }
      calling.value = false
      stopStats()
      ElMessage.info('通话已结束')
    }

    const leaveRoom = () => {
      hangup()
      if (ws) {
        ws.close()
        ws = null
      }
      joined.value = false
    }

    onMounted(() => {
      const params = new URLSearchParams(window.location.search)
      const rid = params.get('room')
      const tid = params.get('target')
      if (rid) {
        roomId.value = rid
        ElMessage.info(`从链接中获取房间ID：${rid}`)
      }
      if (tid) {
        targetPeerId.value = tid
        ElMessage.info(`从链接中获取对端ID：${tid}`)
      }
    })

    onUnmounted(() => {
      leaveRoom()
    })

    return {
      roomId,
      myPeerId,
      targetPeerId,
      joined,
      calling,
      connectionState,
      localVideoEl,
      remoteVideoEl,
      stats,
      currentHost,
      joinRoom,
      leaveRoom,
      startCall,
      hangup,
      generateRoomId,
      copyInviteLink
    }
  }
}
</script>

<style scoped>
.webrtc-core {
  width: 100%;
  max-width: 1100px;
  margin: 0 auto;
  padding: 24px;
}

.box-card {
  border-radius: 10px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.room-form {
  margin-top: 8px;
}

.videos {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-top: 12px;
}

.video-card {
  border-radius: 10px;
}

.video {
  width: 100%;
  background: #000;
  border-radius: 8px;
  aspect-ratio: 16 / 9;
  object-fit: cover;
}

.stats-card {
  margin-top: 12px;
}
</style>