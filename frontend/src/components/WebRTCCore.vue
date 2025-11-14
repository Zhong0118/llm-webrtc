<template>
  <div class="webrtc-core">
    <el-card class="box-card">
      <template #header>
        <div class="card-header">
          <span>房间双人通话 (Socket.IO Refactored)</span>
          <el-tag :type="connectionStateType" v-if="store.joined">
            {{ store.connectionState }}
          </el-tag>
          <el-tag type="info" v-else>未加入房间</el-tag>
        </div>
      </template>

      <!-- (Alert 和 Form 保持不变) -->
      <el-alert title="使用说明" type="info" :closable="false" style="margin-bottom: 16px;">
        <p>1. 输入或生成一个房间ID。</p>
        <p>2. 输入你的唯一 Peer ID。</p>
        <p>3. 点击 "加入房间"。成功后，复制邀请链接发给对方。</p>
        <p>4. 对方加入后，输入对方的 Peer ID，点击 "呼叫"。</p>
        <p><strong>跨设备连接：</strong>确保其他设备可访问 <code>{{ currentHost }}:33335</code></p>
      </el-alert>
      <el-form label-width="100px" class="room-form">
        <el-form-item label="房间ID">
          <el-input v-model="roomIdComputed" placeholder="双方必须相同" :disabled="store.joined">
            <template #append>
              <el-button @click="generateRoomId" :disabled="store.joined">生成</el-button>
            </template>
          </el-input>
        </el-form-item>
        <el-form-item label="我的ID">
          <el-input v-model="myPeerIdComputed" placeholder="你的唯一标识" :disabled="store.joined" />
        </el-form-item>
        <el-form-item label="对端ID">
          <el-input v-model="targetPeerIdComputed" placeholder="呼叫目标的ID" />
          <el-text v-if="store.otherPeerId" size="small" type="info" style="margin-left: 10px;">
            房间成员: {{ store.otherPeerId }}
          </el-text>
        </el-form-item>
        <el-form-item>
          <el-space>
            <el-button type="primary" :disabled="store.joined" @click="handleJoinRoom">加入房间</el-button>
            <el-button :disabled="!store.joined" @click="store.leaveRoom">离开房间</el-button>
            <el-button type="success" :disabled="!store.joined || store.calling || !store.targetPeerId"
              @click="handleStartCall">呼叫</el-button>
            <el-button type="warning" :disabled="!store.calling && store.connectionState === 'disconnected'"
              @click="store.hangup">挂断</el-button>
            <el-button @click="copyInviteLink" :disabled="!store.roomId">复制邀请链接</el-button>
          </el-space>
        </el-form-item>
      </el-form>
      <!-- (视频区域保持不变) -->
      <div class="videos">
        <el-card class="video-card" shadow="never">
          <template #header><span>本地视频</span></template>
          <video ref="localVideoEl" autoplay playsinline muted class="video" />
        </el-card>
        <el-card class="video-card" shadow="never">
          <template #header><span>远端视频</span></template>
          <video ref="remoteVideoEl" autoplay playsinline class="video" />
        </el-card>
      </div>

      <!-- [ 关键修复 ]：修改 v-if 条件 -->
      <el-card class="stats-card" shadow="never"
        v-if="store.joined && store.connectionState !== 'disconnected' && store.connectionState !== 'closed'">
        <template #header><span>连接统计</span></template>
        <el-descriptions :column="3" size="small" border>
          <el-descriptions-item label="入方向码率(kbps)">{{ store.stats.inbound.bitrateKbps }}</el-descriptions-item>
          <el-descriptions-item label="入方向FPS">{{ store.stats.inbound.framesPerSecond }}</el-descriptions-item>
          <el-descriptions-item label="入方向丢包">{{ store.stats.inbound.packetsLost }}</el-descriptions-item>
          <el-descriptions-item label="出方向码率(kbps)">{{ store.stats.outbound.bitrateKbps }}</el-descriptions-item>
          <el-descriptions-item label="出方向FPS">{{ store.stats.outbound.framesPerSecond }}</el-descriptions-item>
          <el-descriptions-item label="ICE RTT(ms)">{{ store.stats.ice.roundTripTimeMs }}</el-descriptions-item>
          <el-descriptions-item label="本地候选">{{ store.stats.ice.localCandidateType }}</el-descriptions-item>
          <el-descriptions-item label="远端候选">{{ store.stats.ice.remoteCandidateType }}</el-descriptions-item>
        </el-descriptions>
      </el-card>
      <!-- [ 修复结束 ] -->

    </el-card>
  </div>
</template>

<script setup>
// ( <script setup> 区域保持 V20 不变 )
import { ref, watch, onMounted, computed } from 'vue';
import { useP2PStore } from '@/stores/useP2PStore';
import { ElMessage } from 'element-plus';

const store = useP2PStore();
const localVideoEl = ref(null);
const remoteVideoEl = ref(null);
const currentHost = computed(() => window.location.hostname);

watch(() => store.localStream, (newStream) => {
  if (localVideoEl.value) {
    localVideoEl.value.srcObject = newStream;
  }
});
watch(() => store.remoteStream, (newStream) => {
  if (remoteVideoEl.value) {
    remoteVideoEl.value.srcObject = newStream;
  }
});

const roomIdComputed = computed({
  get: () => store.roomId,
  set: (value) => { store.roomId = value; }
});
const myPeerIdComputed = computed({
  get: () => store.myPeerId,
  set: (value) => { store.myPeerId = value; }
});
const targetPeerIdComputed = computed({
  get: () => store.targetPeerId,
  set: (value) => { store.targetPeerId = value; }
});

const handleJoinRoom = () => {
  store.joinRoom(roomIdComputed.value, myPeerIdComputed.value);
};
const handleStartCall = () => {
  store.startCall(targetPeerIdComputed.value);
};
const generateRoomId = () => {
  store.roomId = Math.random().toString(36).slice(2, 8).toUpperCase();
  ElMessage.success(`Generated Room ID: ${store.roomId}`);
};
const inviteUrl = () => `${window.location.origin}${window.location.pathname}?mode=p2p&room=${encodeURIComponent(store.roomId)}&target=${encodeURIComponent(store.myPeerId)}`;
const copyInviteLink = async () => {
  if (!store.roomId) {
    ElMessage.warning('请先生成或填写房间ID')
    return
  }
  try {
    await navigator.clipboard.writeText(inviteUrl())
    ElMessage.success('邀请链接已复制到剪贴板')
  } catch (_) {
    ElMessage.info(`邀请链接：${inviteUrl()}`)
  }
};
const connectionStateType = computed(() => {
  switch (store.connectionState) {
    case 'connected': return 'success';
    case 'connecting': case 'checking': return 'warning';
    case 'failed': return 'danger';
    default: return 'info';
  }
});

onMounted(() => {
  const params = new URLSearchParams(window.location.search);
  const rid = params.get('room');
  const tid = params.get('target');

  if (rid && !store.roomId) {
    store.roomId = rid;
    ElMessage.info(`Room ID from URL: ${rid}`);
  }
  if (tid && !store.targetPeerId) {
    store.targetPeerId = tid;
    ElMessage.info(`Target ID from URL: ${tid}`);
  }

  if (store.roomId && store.myPeerId) {
    console.log("Attempting auto-join from URL params...");
    handleJoinRoom();
  }
});
</script>

<style scoped>
/* ( <style> 区域保持 V20 不变 ) */
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