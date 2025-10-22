<template>
  <div class="simple-webrtc">
    <h1>简化版WebRTC</h1>
    <WebRTCCore :server-url="serverUrl" />
  </div>
</template>

<script>
import WebRTCCore from '../components/WebRTCCore.vue'

export default {
  name: 'SimpleWebRTC',
  components: {
    WebRTCCore
  },
  data() {
    return {
      serverUrl: 'http://localhost:8000'
    }
  }
}
</script>

<style scoped>
.simple-webrtc {
  max-width: 1000px;
  margin: 0 auto;
  padding: 20px;
}

h1 {
  text-align: center;
  margin-bottom: 30px;
}
</style>