<template>
  <div class="simple-webrtc">
    <h1>WebRTC Application (P2P)</h1>

    <WebRTCCore v-if="currentMode === 'p2p'" />

    <!-- 模式选择 -->
    <!-- <el-radio-group v-model="currentMode" @change="handleModeChange" style="margin-bottom: 20px;">
      <el-radio-button label="p2p">双人通话 (P2P)</el-radio-button>
      <el-radio-button label="serverPush">观看服务器直播</el-radio-button>
    </el-radio-group>

    <StreamManager style="margin-bottom: 20px; max-width: 70%;"/>

    <div class="viewing-area">
      <WebRTCCore v-if="currentMode === 'p2p'" />
      
      <ServerPushViewer v-if="currentMode === 'serverPush'" />
    </div> -->

  </div>
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted } from 'vue';
import WebRTCCore from '../components/WebRTCCore.vue';
import ServerPushViewer from '../components/ServerPushViewer.vue'; // 确保您已创建此组件
import StreamManager from '../components/StreamManager.vue';
import { useP2PStore } from '@/stores/useP2PStore';
import { useServerPushStore } from '@/stores/useServerPushStore';
import { useSocketStore } from '@/stores/useSocketStore';

const currentMode = ref('p2p'); // 默认模式

const p2pStore = useP2PStore();
const serverPushStore = useServerPushStore();
const socketStore = useSocketStore();

// --- 修正：使用 watch 来正确处理清理逻辑 ---
watch(currentMode, (newMode, oldMode) => {
  console.log(`Switching mode FROM: ${oldMode} TO: ${newMode}`);
  
  // 清理上一个模式 (oldMode) 的资源
  if (oldMode === 'p2p') {
    console.log("Cleaning up P2P resources...");
    p2pStore.cleanup();
  } else if (oldMode === 'serverPush') {
    console.log("Cleaning up Server Push Viewer resources...");
    serverPushStore.stopConnection(); // 确保 serverPushStore 有 'stopConnection' 或 'cleanup' 方法
  }
});

onMounted(() => {
  // socketStore.connect(); // <-- 不再需要，getSocket 会按需连接
  socketStore.initialize(); // <-- 初始化 base URL
  console.log("SimpleWebRTC mounted.");
});

onUnmounted(() => {
  console.log(`SimpleWebRTC unmounting in mode: ${currentMode.value}, cleaning up...`);
  // 清理当前激活的模式
  if (currentMode.value === 'p2p') {
    p2pStore.cleanup();
  } else if (currentMode.value === 'serverPush') {
    serverPushStore.stopConnection();
  }
  
  socketStore.disconnectAll(); // <-- 调用新的清理方法
});
</script>

<style scoped>
.simple-webrtc {
  max-width: 100%;
  margin: 0 auto;
  padding: 20px;
}
h1 {
  text-align: center;
  margin-bottom: 30px;
}
.viewing-area {
  margin-top: 20px;
}
</style>
