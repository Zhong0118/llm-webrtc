<template>
  <div class="connection-status">
    <div class="status-indicator" :class="connectionStateClass">
      <span>状态: {{ connectionStateText }}</span>
    </div>
    <div class="stats-container" v-if="hasStats">
      <div class="stat-item">
        <span>接收字节: {{ formatBytes(stats.bytesReceived) }}</span>
      </div>
      <div class="stat-item">
        <span>接收包数: {{ stats.packetsReceived || 0 }}</span>
      </div>
      <div class="stat-item">
        <span>丢包数: {{ stats.packetsLost || 0 }}</span>
      </div>
      <div class="stat-item">
        <span>抖动: {{ formatJitter(stats.jitter) }}</span>
      </div>
    </div>
  </div>
</template>

<script>
import { computed } from 'vue'

export default {
  name: 'ConnectionStatus',
  props: {
    connectionState: {
      type: String,
      default: 'disconnected'
    },
    stats: {
      type: Object,
      default: () => ({})
    }
  },
  setup(props) {
    // 连接状态文本
    const connectionStateText = computed(() => {
      switch (props.connectionState) {
        case 'new': return '初始化'
        case 'connecting': return '连接中'
        case 'connected': return '已连接'
        case 'disconnected': return '已断开'
        case 'failed': return '连接失败'
        case 'closed': return '已关闭'
        default: return '未知'
      }
    })
    
    // 连接状态样式类
    const connectionStateClass = computed(() => {
      switch (props.connectionState) {
        case 'connected': return 'status-connected'
        case 'connecting': return 'status-connecting'
        case 'failed': return 'status-failed'
        default: return 'status-disconnected'
      }
    })
    
    // 是否有统计数据
    const hasStats = computed(() => {
      return Object.keys(props.stats).length > 0
    })
    
    // 格式化字节数
    const formatBytes = (bytes) => {
      if (!bytes) return '0 B'
      const k = 1024
      const sizes = ['B', 'KB', 'MB', 'GB']
      const i = Math.floor(Math.log(bytes) / Math.log(k))
      return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
    }
    
    // 格式化抖动
    const formatJitter = (jitter) => {
      if (!jitter) return '0 ms'
      return (jitter * 1000).toFixed(2) + ' ms'
    }
    
    return {
      connectionStateText,
      connectionStateClass,
      hasStats,
      formatBytes,
      formatJitter
    }
  }
}
</script>

<style scoped>
.connection-status {
  width: 100%;
  margin-top: 20px;
  padding: 15px;
  border-radius: 8px;
  background-color: #f5f5f5;
}

.status-indicator {
  padding: 8px 12px;
  border-radius: 4px;
  font-weight: bold;
  margin-bottom: 10px;
}

.status-connected {
  background-color: #4CAF50;
  color: white;
}

.status-connecting {
  background-color: #2196F3;
  color: white;
}

.status-disconnected {
  background-color: #9E9E9E;
  color: white;
}

.status-failed {
  background-color: #F44336;
  color: white;
}

.stats-container {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
}

.stat-item {
  padding: 8px;
  background-color: #e0e0e0;
  border-radius: 4px;
}
</style>