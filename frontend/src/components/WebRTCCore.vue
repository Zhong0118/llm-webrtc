<template>
  <div class="webrtc-core">
    <el-card class="box-card">
      <template #header>
        <div class="card-header">
          <div class="title-section">
            <span class="main-title">WebRTC P2P + AI 全栈分析系统</span>
            <el-tag :type="connectionStateType" v-if="p2pStore.joined" effect="dark" round>
              {{ p2pStore.connectionState === 'connected' ? 'P2P 链路已通' : p2pStore.connectionState }}
            </el-tag>
          </div>
          <div class="header-controls">
            <input type="file" ref="fileInput" accept="video/*" style="display: none" @change="handleFileSelected">
            <el-button size="small" @click="triggerSourceSwitch" :disabled="!p2pStore.joined">
              <el-icon style="margin-right: 4px">
                <VideoCamera />
              </el-icon>
              {{ isFileMode ? '切换回摄像头' : '切换本地文件' }}
            </el-button>
          </div>
        </div>
      </template>

      <div class="dashboard-section" v-if="p2pStore.connectionState === 'connected'">
        <div class="section-title">📡 P2P 链路监控 (Direct)</div>
        <div class="stats-grid">
          <div class="stat-card">
            <div class="stat-label">往返时延 (RTT)</div>
            <div class="stat-value">{{ p2pStore.stats.ice.roundTripTimeMs }} <span class="unit">ms</span></div>
          </div>
          <div class="stat-card">
            <div class="stat-label">接收带宽 (In)</div>
            <div class="stat-value">{{ p2pStore.stats.inbound.bitrateKbps }} <span class="unit">kbps</span></div>
          </div>
          <div class="stat-card">
            <div class="stat-label">发送带宽 (Out)</div>
            <div class="stat-value">{{ p2pStore.stats.outbound.bitrateKbps }} <span class="unit">kbps</span></div>
          </div>
          <div class="stat-card">
            <div class="stat-label">丢包率</div>
            <div class="stat-value">{{ p2pStore.stats.inbound.packetsLost }} <span class="unit">pkts</span></div>
          </div>

          <div class="stat-card">
            <div class="stat-label">AI启动耗时</div>
            <div class="stat-value">
              {{ aiStore.aiStartupTime > 0 ? aiStore.aiStartupTime.toFixed(0) : '-' }}
              <span class="unit">ms</span>
            </div>
          </div>
        </div>
      </div>

      <div class="dashboard-section" v-if="hasActiveResults">
        <div class="section-title">🤖 AI 引擎性能监控 (Server Side)</div>

        <div v-for="(result, peerId) in aiStore.resultsMap" :key="peerId">
          <div v-if="shouldShowData(peerId)" class="ai-stat-row">
            <div class="identity-tag">
              <el-tag size="small" :type="peerId === p2pStore.myPeerId ? 'danger' : 'warning'" effect="dark">
                {{ peerId === p2pStore.myPeerId ? 'Local AI' : `Remote AI (${peerId})` }}
              </el-tag>
            </div>

            <div class="ai-metrics">
              <el-tooltip content="AI 引擎冷启动耗时 (Warmup)" placement="top">
                <span class="metric">
                  启动: <strong>{{ aiStore.startupTimesMap[peerId] ? Math.round(aiStore.startupTimesMap[peerId]) : '-'
                    }}ms</strong>
                </span>
              </el-tooltip>

              <el-tooltip content="服务器当前的处理帧率" placement="top">
                <span class="metric">FPS: <strong>{{ result.fps || '-' }}</strong></span>
              </el-tooltip>

              <el-tooltip content="YOLO 模型纯推理耗时 (Infer)" placement="top">
                <span class="metric">推理: <strong>{{ result.inference_time }}ms</strong></span>
              </el-tooltip>

              <el-tooltip content="系统处理延迟 (近似同步偏差)" placement="top">
                <span class="metric" :style="{ color: result.d_an > 200 ? 'orange' : 'inherit' }">
                  延迟: <strong>{{ result.d_an }}ms</strong>
                </span>
              </el-tooltip>

              <el-tooltip content="从服务器发出到前端收到的网络延迟" placement="top">
                <span class="metric">传输延迟: <strong>{{ calculateDelay(result.send_time) }}ms</strong></span>
              </el-tooltip>

              <el-tooltip content="视频帧PTS (用于同步调试)" placement="top">
                <span class="metric">PTS: <strong>{{ result.pts }}</strong></span>
              </el-tooltip>

              <span class="metric">对象: <strong>{{ result.objects ? result.objects.length : 0 }}</strong></span>
            </div>
          </div>
        </div>
      </div>

      <div class="control-bar">
        <el-form :inline="true" size="default">
          <el-form-item label="房间 ID">
            <el-input v-model="roomIdComputed" placeholder="1001" style="width: 80px" :disabled="p2pStore.joined">
              <template #prefix>#</template>
            </el-input>
          </el-form-item>
          <el-form-item label="我的 ID">
            <el-input v-model="myPeerIdComputed" style="width: 90px" disabled />
          </el-form-item>
          <el-form-item label="目标 ID">
            <el-input v-model="targetPeerIdComputed" placeholder="对方 ID" style="width: 90px" />
          </el-form-item>
          <el-form-item>
            <el-button v-if="!p2pStore.joined" type="primary" @click="handleJoinRoom" :loading="joining">加入</el-button>
            <template v-else>
              <el-button v-if="!p2pStore.calling" type="success" @click="handleStartCall"
                :disabled="!p2pStore.targetPeerId">呼叫</el-button>
              <el-button v-else type="danger" @click="p2pStore.hangup">挂断</el-button>
              <el-button type="warning" @click="p2pStore.leaveRoom">离开</el-button>
            </template>
          </el-form-item>
        </el-form>
      </div>

      <div class="videos-grid">
        <el-card class="video-card" :body-style="{ padding: '0px' }">
          <div class="video-toolbar">
            <span class="video-label">Local (我) - {{ isFileMode ? '文件模式' : '摄像头' }}</span>
            <el-tag v-if="aiStore.isSending" size="small" type="danger" effect="plain">AI 推流中</el-tag>
          </div>

          <div class="video-wrapper">
            <video v-show="!isFileMode" ref="localVideoEl" autoplay playsinline muted class="video-element" />

            <video v-show="isFileMode" ref="fileVideoEl" controls loop playsinline class="video-element file-player" />

            <AIOverlay
              v-if="p2pStore.myPeerId && aiStore.resultsMap[p2pStore.myPeerId] && shouldShowData(p2pStore.myPeerId)"
              :result="aiStore.resultsMap[p2pStore.myPeerId]" :filter-peer-id="p2pStore.myPeerId"
              :video-element="isFileMode ? fileVideoEl : localVideoEl" />
          </div>
        </el-card>

        <el-card class="video-card" :body-style="{ padding: '0px' }">
          <div class="video-toolbar">
            <span class="video-label">Remote (对方)</span>
            <el-button size="small" :type="isRemoteAnalyzing ? 'danger' : 'warning'" @click="toggleRemoteAI"
              :loading="remoteLoading" :disabled="!p2pStore.targetPeerId" plain>
              {{ isRemoteAnalyzing ? '停止分析' : '分析对方' }}
            </el-button>
          </div>
          <div class="video-wrapper">
            <video ref="remoteVideoEl" autoplay playsinline class="video-element" />
            <AIOverlay
              v-if="p2pStore.targetPeerId && aiStore.resultsMap[p2pStore.targetPeerId] && shouldShowData(p2pStore.targetPeerId)"
              :result="aiStore.resultsMap[p2pStore.targetPeerId]" :filter-peer-id="p2pStore.targetPeerId"
              :video-element="remoteVideoEl" />
            <div v-if="!p2pStore.remoteStream" class="no-signal"><span>等待视频...</span></div>
          </div>
        </el-card>
      </div>

    </el-card>
  </div>
</template>

<script setup>
import { ref, watch, computed, nextTick } from 'vue';
import { useP2PStore } from '@/stores/useP2PStore';
import { useAIStore } from '@/stores/useAIStore';
import { useSocketStore } from '@/stores/useSocketStore';
import AIOverlay from './AIOverlay.vue';
import { ElMessage } from 'element-plus';
import { VideoCamera } from '@element-plus/icons-vue';

const p2pStore = useP2PStore();
const aiStore = useAIStore();
const socketStore = useSocketStore();

// DOM Refs
const localVideoEl = ref(null);
const remoteVideoEl = ref(null);
const fileInput = ref(null);
const fileVideoEl = ref(null);

// UI States
const remoteLoading = ref(false);
const joining = ref(false);
const shouldAnalyzeRemote = ref(false);
const isFileMode = ref(false); // 标记当前是否为文件模式

// Computed
const roomIdComputed = computed({ get: () => p2pStore.roomId, set: (v) => p2pStore.roomId = v });
const myPeerIdComputed = computed({ get: () => p2pStore.myPeerId, set: (v) => p2pStore.myPeerId = v });
const targetPeerIdComputed = computed({ get: () => p2pStore.targetPeerId, set: (v) => p2pStore.targetPeerId = v });
const connectionStateType = computed(() => {
  if (p2pStore.connectionState === 'connected') return 'success';
  if (['connecting', 'checking'].includes(p2pStore.connectionState)) return 'warning';
  return 'info';
});
const hasActiveResults = computed(() => Object.keys(aiStore.resultsMap).length > 0);

// 状态判断
const isRemoteAnalyzing = computed(() => {
  const hasData = p2pStore.targetPeerId && !!aiStore.resultsMap[p2pStore.targetPeerId];
  return shouldAnalyzeRemote.value || hasData;
});

// 延迟计算
const calculateDelay = (sendTime) => {
  if (!sendTime) return 0;
  // 现在 sendTime 是服务器的系统时间 (毫秒)
  // 假设服务器和客户端都使用 NTP 同步，或者容忍少许时钟偏差
  const now = Date.now();
  const delay = now - sendTime;
  return Math.max(0, delay); // 防止负数
};
// 视频流绑定
watch(() => p2pStore.localStream, (s) => {
  // 只有在不是文件模式时，才把流赋给 localVideoEl (摄像头)
  if (localVideoEl.value && s && !isFileMode.value) {
    localVideoEl.value.srcObject = s;
  }
}, { immediate: true });

watch(() => p2pStore.remoteStream, (s) => { if (remoteVideoEl.value && s) remoteVideoEl.value.srcObject = s; }, { immediate: true });

// --- 视频源切换逻辑 ---

const triggerSourceSwitch = () => {
  if (isFileMode.value) {
    switchToCamera();
  } else {
    if (fileInput.value) fileInput.value.value = '';
    fileInput.value.click();
  }
};

const switchToCamera = async () => {
  try {
    await p2pStore.startLocalPreview();
    if (p2pStore.localStream) {
      await p2pStore.switchVideoStream(p2pStore.localStream);
    }
    // 暂停文件
    if (fileVideoEl.value) {
      fileVideoEl.value.pause();
      fileVideoEl.value.src = "";
    }
    isFileMode.value = false;
    ElMessage.success("已切换回摄像头");
  } catch (e) {
    ElMessage.error("切回摄像头失败: " + e.message);
  }
};

const handleFileSelected = async (e) => {
  const file = e.target.files[0];
  if (!file) return;

  const v = fileVideoEl.value;

  // 1. 先清理旧资源
  if (v.src && v.src.startsWith('blob:')) URL.revokeObjectURL(v.src);

  // 2. 先切换 UI 模式，让视频元素渲染出来
  isFileMode.value = true;

  // [关键修复] 等待 Vue 完成 DOM 更新，确保 <video> 不再是 display: none
  await nextTick();

  const url = URL.createObjectURL(file);
  v.src = url;

  ElMessage.info("正在解析视频...");

  // 定义启动逻辑
  const startCapture = async () => {
    try {
      // 尝试播放
      await v.play();

      // 捕获流
      const stream = v.captureStream ? v.captureStream() : (v.mozCaptureStream ? v.mozCaptureStream() : null);

      if (!stream) {
        throw new Error("浏览器不支持 captureStream");
      }

      // 检查轨道 (带重试)
      let retries = 0;
      const checkTracks = () => {
        const tracks = stream.getVideoTracks();
        if (tracks.length > 0) {
          console.log("成功捕获文件视频轨道:", tracks[0]);
          // 成功！切换 P2P 流
          p2pStore.switchVideoStream(stream);
          ElMessage.success("视频源已切换 (可拖动进度)");
        } else {
          if (retries < 30) { // 增加到 3秒
            retries++;
            // console.log(`等待视频轨道... ${retries}`);
            setTimeout(checkTracks, 100);
          } else {
            // [关键修改] 即使捕获失败，也不要关闭播放器 (isFileMode = false)
            // 这样用户至少可以在本地看视频
            ElMessage.error("⚠️ 警告: 视频画面无法传给对方 (轨道捕获超时)");
            console.error("Capture stream has no video tracks after timeout");
          }
        }
      };
      checkTracks();

    } catch (err) {
      console.error("视频启动失败:", err);
      ElMessage.error("视频启动失败: " + err.message);
      // 只有播放都失败了，才关掉播放器
      // isFileMode.value = false; 
    }
  };

  // 绑定事件
  v.oncanplay = () => {
    // 防止重复触发
    v.oncanplay = null;
    startCapture();
  };

  v.onerror = () => {
    ElMessage.error("视频文件解码错误");
  };
};

// 远程 AI 控制
const toggleRemoteAI = async () => {
  if (!p2pStore.targetPeerId) { ElMessage.warning("无目标用户"); return; }
  const p2pSocket = socketStore.getSocket('/p2p');
  remoteLoading.value = true;

  if (isRemoteAnalyzing.value) {
    p2pSocket.emit('signal', { type: 'control', action: 'stop-ai', roomId: p2pStore.roomId, to: p2pStore.targetPeerId });
    shouldAnalyzeRemote.value = false;
    if (aiStore.resultsMap[p2pStore.targetPeerId]) delete aiStore.resultsMap[p2pStore.targetPeerId];
    ElMessage.info("已停止");
    remoteLoading.value = false;
  } else {
    try {
      await aiStore.joinAIRoomOnly(p2pStore.roomId);
      p2pSocket.emit('signal', { type: 'control', action: 'start-ai', roomId: p2pStore.roomId, to: p2pStore.targetPeerId });
      shouldAnalyzeRemote.value = true;
      ElMessage.success(`已请求开启`);
      setTimeout(() => { remoteLoading.value = false; }, 500);
    } catch (e) { remoteLoading.value = false; ElMessage.error(e.message); }
  }
};

const shouldShowData = (peerId) => {
  // 情况 1: 数据属于我自己
  if (peerId === p2pStore.myPeerId) {
    // 只有当我【正在推流】时才显示
    // 这样一旦 stopStreaming() 执行，isSending 变 false，数据立马消失
    return aiStore.isSending;
  }
  // 情况 2: 数据属于对方
  if (peerId === p2pStore.targetPeerId) {
    // 只有当我【有意图分析对方】时才显示
    // 这样一旦我点击停止 (shouldAnalyzeRemote = false)，数据立马消失
    // 哪怕 Map 里还有残留的幽灵数据，也会被这个条件拦截
    return shouldAnalyzeRemote.value;
  }
  return false;
};

const handleJoinRoom = async () => { joining.value = true; try { await p2pStore.joinRoom(roomIdComputed.value, myPeerIdComputed.value); } finally { joining.value = false; } };
const handleStartCall = () => p2pStore.startCall(targetPeerIdComputed.value);



// fnMap(todo) vue中p2p的计算同步偏差
const calculateSyncDrift = (result) => {
  // 这是一个非常高阶的科研指标
  // 也就是：当前看到的画面时间 vs AI 标注的画面时间
  // 需要前端能获取当前 video 正在播放的 RTP timestamp (需要 Chrome 实验性 API)
  // 现阶段，我们先展示后端的纯处理耗时即可。
  return "--";
}

</script>

<style scoped>
.webrtc-core {
  max-width: 90%;
  margin: 0 auto;
  padding: 20px;
  font-family: sans-serif;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.title-section {
  display: flex;
  align-items: center;
  gap: 15px;
}

.main-title {
  font-size: 18px;
  font-weight: 600;
  color: #303133;
}

/* Dashboard Styles */
.dashboard-section {
  background: #f8f9fa;
  padding: 15px;
  border-radius: 8px;
  margin-bottom: 20px;
  border: 1px solid #ebeef5;
}

.section-title {
  font-size: 14px;
  font-weight: bold;
  color: #606266;
  margin-bottom: 10px;
  border-left: 4px solid #409eff;
  padding-left: 8px;
}

/* P2P Grid */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 15px;
}

.stat-card {
  background: white;
  padding: 10px;
  border-radius: 6px;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
  text-align: center;
}

.stat-label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 4px;
}

.stat-value {
  font-size: 18px;
  font-weight: bold;
  color: #303133;
}

.unit {
  font-size: 12px;
  font-weight: normal;
  color: #909399;
}

/* AI Grid */
.ai-stat-row {
  display: flex;
  align-items: center;
  background: white;
  padding: 10px;
  border-radius: 6px;
  margin-bottom: 8px;
  justify-content: space-between;
}

.ai-metrics {
  display: flex;
  gap: 20px;
  font-size: 14px;
  font-family: monospace;
}

.metric strong {
  color: #409eff;
}

.upload-metrics {
  font-size: 12px;
  color: #909399;
  display: flex;
  gap: 15px;
  background: #f0f9eb;
  padding: 4px 8px;
  border-radius: 4px;
}

.control-bar {
  margin-bottom: 20px;
  background: #f5f7fa;
  padding: 15px 15px 0 15px;
  border-radius: 6px;
}

.videos-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
}

.video-card {
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  overflow: hidden;
}

.video-toolbar {
  padding: 10px 15px;
  background: #f5f7fa;
  border-bottom: 1px solid #e4e7ed;
  display: flex;
  justify-content: space-between;
  align-items: center;
  height: 40px;
}

.video-label {
  font-weight: 600;
  color: #606266;
}

.video-wrapper {
  position: relative;
  aspect-ratio: 16 / 9;
  background-color: #000;
}

.video-element {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
}

.file-player {
  background: #000;
}

.no-signal {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  color: #909399;
}

.is-loading .stat-value {
  font-size: 16px;
  /* 加载时字号稍微小点 */
}

/* 如果你想给 loading 加个旋转动画，虽然 ElementPlus 的 icon 自带旋转 */
@keyframes rotate {
  from {
    transform: rotate(0deg);
  }

  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 768px) {
  .videos-grid {
    grid-template-columns: 1fr;
  }

  .stats-grid {
    grid-template-columns: 1fr 1fr;
  }
}
</style>