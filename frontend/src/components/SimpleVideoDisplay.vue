<template>
  <div class="video-container">
    <video ref="videoElement" autoplay playsinline></video>
    <div v-if="connectionState !== 'connected'" class="connection-overlay">
      <div class="connection-status">{{ connectionStateMessage }}</div>
    </div>
  </div>
</template>

<script>
import { ref, onMounted, watch } from 'vue'

export default {
  name: 'SimpleVideoDisplay',
  props: {
    stream: {
      type: Object,
      default: null
    },
    connectionState: {
      type: String,
      default: 'disconnected'
    }
  },
  setup(props) {
    const videoElement = ref(null)
    const connectionStateMessage = ref('未连接')
    
    // 监听流变化
    watch(() => props.stream, (newStream) => {
      if (videoElement.value && newStream) {
        videoElement.value.srcObject = newStream
      }
    })
    
    // 监听连接状态变化
    watch(() => props.connectionState, (newState) => {
      switch (newState) {
        case 'new':
        case 'connecting':
          connectionStateMessage.value = '正在连接...'
          break
        case 'connected':
          connectionStateMessage.value = '已连接'
          break
        case 'disconnected':
          connectionStateMessage.value = '已断开连接'
          break
        case 'failed':
          connectionStateMessage.value = '连接失败'
          break
        default:
          connectionStateMessage.value = '未知状态'
      }
    })
    
    onMounted(() => {
      if (videoElement.value && props.stream) {
        videoElement.value.srcObject = props.stream
      }
    })
    
    return {
      videoElement,
      connectionStateMessage
    }
  }
}
</script>

<style scoped>
.video-container {
  position: relative;
  width: 100%;
  height: 0;
  padding-bottom: 56.25%; /* 16:9 宽高比 */
  background-color: #000;
  border-radius: 8px;
  overflow: hidden;
}

video {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.connection-overlay {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  display: flex;
  justify-content: center;
  align-items: center;
  background-color: rgba(0, 0, 0, 0.7);
}

.connection-status {
  color: white;
  font-size: 1.5rem;
  padding: 10px 20px;
  background-color: rgba(0, 0, 0, 0.5);
  border-radius: 4px;
}
</style>