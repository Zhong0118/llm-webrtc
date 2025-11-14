// src/components/ServerPushViewer.vue
<template>
  <div class="server-push-viewer">
    <el-card>
      <template #header>
         <div class="card-header">
           <span>观看服务器直播 (Socket.IO)</span>
           <el-tag :type="connectionStateType" style="float: right;">
             {{ store.connectionState }}
           </el-tag>
         </div>
      </template>

      <SimpleVideoDisplay
        :stream="store.remoteStream"
        :connection-state="store.connectionState"
      />

      <div style="margin-top: 20px;">
        <el-button
          type="primary"
          @click="startWatching"
          :disabled="store.isConnected || store.connectionState === 'connecting'"
          :loading="store.connectionState === 'connecting'"
        >
          {{ store.connectionState === 'connecting' ? '连接中...' : '开始观看' }}
        </el-button>
        <el-button
          type="danger"
          @click="stopWatching"
          :disabled="!store.isConnected && store.connectionState !== 'connecting'"
        >
          停止观看
        </el-button>
         </div>

       </el-card>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, computed } from 'vue';
import { useServerPushStore } from '@/stores/useServerPushStore';
import SimpleVideoDisplay from './SimpleVideoDisplay.vue';
import { useSocketStore } from '@/stores/useSocketStore';
import { ElMessage } from 'element-plus';

const store = useServerPushStore();
const socketStore = useSocketStore(); // 虽然我们不再检查 .isConnected，但保留它没问题

const startWatching = async () => {
  
  // --- 【已修复】 ---
  //
  // 删除了那个错误的 'if (!socketStore.isConnected)' 检查。
  //
  // 原因是：useServerPushStore.js 自己的 startConnection()
  // 内部已经包含了正确的连接和等待逻辑。
  // 我们应该直接调用它，而不是在这里错误地阻止它。
  //
  // ----------------
  
  try {
    // 现在这个函数会“真正”被执行了
    await store.startConnection(); 
  } catch (error) {
    console.error("Error initiating watch:", error);
  }
};

const stopWatching = () => {
  store.stopConnection();
};

const connectionStateType = computed(() => {
    switch (store.connectionState) {
        case 'connected': return 'success';
        case 'connecting': case 'checking': return 'warning';
        case 'failed': return 'danger';
        case 'disconnected':
        case 'new':
        case 'closed':
        default: return 'info';
    }
});

// Clean up store connection when component is unmounted
onUnmounted(() => {
  store.stopConnection(); // Call the store's cleanup
});
</script>

<style scoped>
.server-push-viewer { width: 100%; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
</style>