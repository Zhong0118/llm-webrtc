import { ref, computed, onUnmounted } from 'vue';
import { defineStore } from 'pinia';
import { ElMessage } from 'element-plus';
import { useSocketStore } from './useSocketStore';

const SERVER_PUSH_NAMESPACE = '/server_push';

export const useServerPushStore = defineStore('serverPush', () => {
  const socketStore = useSocketStore();
  const pushSocket = ref(null);

  const peerConnection = ref(null);
  const remoteStream = ref(null);
  const connectionState = ref('disconnected'); // 保持 'disconnected' 为初始状态
  const connectionStats = ref({});

  const isConnected = computed(() => connectionState.value === 'connected');

  function initPeerConnection() {
    if (peerConnection.value) { return; }
    console.log("Initializing ServerPush RTCPeerConnection (recvonly)...");
    try {
      peerConnection.value = new RTCPeerConnection({
        iceServers: [
          { urls: 'stun:stun.l.google.com:19302' },
          { urls: 'stun:stun1.l.google.com:19302' },
          { urls: "turn:openrelay.metered.ca:80", username: "openrelayproject", credential: "openrelayproject" },
          { urls: "turn:openrelay.metered.ca:443", username: "openrelayproject", credential: "openrelayproject" }
        ],
      });
      peerConnection.value.addTransceiver('video', { direction: 'recvonly' });

      peerConnection.value.onconnectionstatechange = () => {
        const newState = peerConnection.value?.connectionState ?? 'closed';
        connectionState.value = newState; // 实时更新状态
        if (newState === 'connected') ElMessage.success("Server stream connected");
        else if (newState === 'failed') ElMessage.error("Server stream connection failed");
        else if (newState === 'disconnected' || newState === 'closed') ElMessage.info("Server stream disconnected");
      };
      peerConnection.value.ontrack = (event) => {
        if (event.streams && event.streams[0]) {
          remoteStream.value = event.streams[0];
        }
      };
      
      // [V19-FIX] 修正 icecandidate 处理器
      peerConnection.value.onicecandidate = (event) => {
        const candidate = event.candidate ? event.candidate.toJSON() : null;
        if (pushSocket.value && pushSocket.value.connected) {
            // 发送完整的 candidate 对象 (JSON)
            pushSocket.value.emit('candidate', { 
                type: 'ice-candidate', 
                candidate: candidate 
            });
        }
      };

    } catch (err) {
      console.error("ServerPush PC init failed:", err);
      ElMessage.error(`Failed to initialize WebRTC receiver: ${err.message}`);
      cleanupConnection();
      throw err;
    }
  }

  const handleSignal = async (data) => {
    console.log("ServerPush received signal:", data);
    const signalType = data.type;
    
    // [V19-FIX] 确保 PC 存在
    if (!peerConnection.value) {
        console.warn("Received signal but PeerConnection is null. Ignoring.");
        return; 
    }

    try {
      if (signalType === 'answer') {
        if (data.answer) {
          await peerConnection.value.setRemoteDescription(new RTCSessionDescription(data.answer));
        }
      } else if (signalType === 'ice-candidate') {
        if (data.candidate) {
          // [V19-FIX] 后端发送的是完整的 candidate 对象
          const iceCandidateInit = {
            candidate: data.candidate,
            sdpMid: data.sdpMid,
            sdpMLineIndex: data.sdpMLineIndex
          };
          await peerConnection.value.addIceCandidate(new RTCIceCandidate(iceCandidateInit));
        } else {
          await peerConnection.value.addIceCandidate(null);
        }
      } else if (signalType === 'error') {
        ElMessage.error(`Server Push Signaling Error: ${data.message}`);
        cleanupConnection();
      }
    } catch (error) {
      console.error("Error handling ServerPush signal:", error);
    }
  };

  async function startConnection() {
    if (connectionState.value === 'connecting' || connectionState.value === 'connected') {
      return;
    }

    // [V19-FIX] 确保在 'connecting' 状态下开始
    connectionState.value = 'connecting';
    remoteStream.value = null;

    pushSocket.value = socketStore.getSocket(SERVER_PUSH_NAMESPACE);

    try {
      if (!pushSocket.value.connected) {
        console.log("Waiting for /server_push socket connection...");
        await new Promise((resolve, reject) => {
          const timeout = setTimeout(() => reject(new Error("Socket connection timeout (5s)")), 5000);
          
          pushSocket.value.once('connect', () => {
            clearTimeout(timeout);
            resolve();
          });
          
          pushSocket.value.once('connect_error', (err) => {
            clearTimeout(timeout);
            reject(err);
          });
        });
      }
      console.log("/server_push socket connected.");

      // Socket 已连接，现在初始化 WebRTC
      initPeerConnection(); // 创建 PC

      // 注册事件监听器
      pushSocket.value.on('answer', (data) => handleSignal({ type: 'answer', ...data }));
      pushSocket.value.on('candidate', (data) => handleSignal({ type: 'ice-candidate', ...data }));
      pushSocket.value.on('error', (data) => handleSignal({ type: 'error', ...data }));

      // 创建并发送 Offer
      const offer = await peerConnection.value.createOffer();
      await peerConnection.value.setLocalDescription(offer);
      pushSocket.value.emit('offer', { offer: offer.toJSON() }); // 发送 JSON 对象
    
    } catch (error) {
      console.error('Failed to start ServerPush connection:', error);
      ElMessage.error(`Connection failed: ${error.message}`);
      cleanupConnection(); // 失败时回滚
    }
  }

  function cleanupConnection() {
    console.log("Cleaning up ServerPush Store resources...");
    if (peerConnection.value) {
      peerConnection.value.close();
      peerConnection.value = null;
    }
    remoteStream.value = null;
    
    // [V19-FIX] 只有在未断开时才设置为 'disconnected'
    if (connectionState.value !== 'disconnected') {
        connectionState.value = 'disconnected';
    }

    if (pushSocket.value) {
      pushSocket.value.off('answer');
      pushSocket.value.off('candidate');
      pushSocket.value.off('error');
      // 不调用 disconnect()，让 socketStore 管理
      pushSocket.value = null;
    }
  }

  const stopConnection = cleanupConnection;
  onUnmounted(() => { cleanupConnection(); });

  return {
    remoteStream,
    connectionState,
    connectionStats,
    isConnected,
    startConnection,
    stopConnection,
    cleanupConnection
  };
});