import { ref, reactive, computed } from 'vue';
import { defineStore } from 'pinia';
import { ElMessage } from 'element-plus';
import { useSocketStore } from './useSocketStore';

const STREAMER_NAMESPACE = '/streamer'; // 后端命名空间

export const useStreamerStore = defineStore('streamer', () => {
  const socketStore = useSocketStore();
  const streamerSocket = ref(null); // 持有 /streamer 的 socket 连接

  // --- State ---
  const isAvailable = ref(true); // 默认乐观假设为 true
  const isRunning = ref(false);
  const statusText = ref('未知');
  const rtspUrl = ref('');
  const config = reactive({
    resolution: '640x480',
    fps: 30,
    crf: 28,
    preset: 'ultrafast',
    input_source: 'N/A', // 从后端更新
    ffmpeg_path: 'N/A'  // 从后端更新
  });
  const logs = ref([]);
  const error = ref(null);
  const delayInfo = reactive({ total_startup_ms: null });
  // let statusPollTimer = null; // 移除轮询

  // --- Computed ---
  const statusDisplay = computed(() => {
    if (!isAvailable.value) return { text: '不可用', type: 'danger' };
    if (error.value) return { text: '错误', type: 'danger' };
    if (statusText.value === '启动中...') return { text: '启动中...', type: 'warning' };
    if (statusText.value === '停止中...') return { text: '停止中...', type: 'warning' };
    if (isRunning.value) return { text: '运行中', type: 'success' };
    return { text: '已停止', type: 'info' };
  });

  // --- Actions ---

  // 辅助函数：执行 API 请求 (保持不变)
  async function apiRequest(endpoint, options = {}) {
    try {
      // 仍然使用 /api 路径，Vite 会代理
      const response = await fetch(`/api/rtsp${endpoint}`, options); 
      if (!response.ok) {
        let errorDetail = `HTTP error ${response.status}`;
        try {
          const errData = await response.json();
          errorDetail = errData.detail || errData.error || JSON.stringify(errData);
        } catch (_) {}
        throw new Error(errorDetail);
      }
      return await response.json();
    } catch (err) {
      console.error(`API请求失败 [${options.method || 'GET'} ${endpoint}]:`, err);
      error.value = err.message;
      if (err.message.includes('503')) {
          isAvailable.value = false;
          statusText.value = '模块不可用';
      } else {
          statusText.value = '状态获取失败';
      }
      throw err;
    }
  }

  // --- 实时更新处理器 ---
  const handleStatusUpdate = (data) => {
    console.log("实时状态更新:", data);
    isAvailable.value = true;
    isRunning.value = data.running;
    rtspUrl.value = data.config.rtsp_url;
    Object.assign(config, data.config || {});
    logs.value = data.log || [];
    Object.assign(delayInfo, data.delay_info || {});
    error.value = null;
    statusText.value = data.running ? '运行中' : '已停止';
  };
  const handleLogUpdate = (data) => {
    if (data && data.log_entry) {
        logs.value.push(data.log_entry);
        if (logs.value.length > 100) logs.value.shift();
    }
  };
  const handleError = (data) => {
    error.value = data.message || '未知推流错误';
    statusText.value = '错误';
    isRunning.value = false;
  };

  // --- 修正：连接到实时更新 ---
  async function listenForUpdates() {
    console.log("Connecting to streamer updates...");
    streamerSocket.value = socketStore.getSocket(STREAMER_NAMESPACE);
    
    if (!streamerSocket.value.connected) {
        try {
            await new Promise((resolve, reject) => {
                const timeout = setTimeout(() => reject(new Error("Streamer socket connection timeout")), 5000);
                streamerSocket.value.once('connect', () => {
                    clearTimeout(timeout);
                    resolve();
                });
                streamerSocket.value.once('connect_error', (err) => {
                    clearTimeout(timeout);
                    reject(err);
                });
            });
        } catch (err) {
            ElMessage.error(`Streamer 状态连接失败: ${err.message}`);
            isAvailable.value = false; // 无法连接到状态更新
            return;
        }
    }
    console.log("/streamer socket connected.");

    // 注册监听器
    streamerSocket.value.on('rtsp_status_update', handleStatusUpdate);
    streamerSocket.value.on('rtsp_log_update', handleLogUpdate);
    streamerSocket.value.on('rtsp_error', handleError);
    
    // 连接成功后，立即通过 HTTP 获取一次最新状态
    await fetchStatus();
  }

  function stopListening() {
    if (streamerSocket.value) {
        streamerSocket.value.off('rtsp_status_update', handleStatusUpdate);
        streamerSocket.value.off('rtsp_log_update', handleLogUpdate);
        streamerSocket.value.off('rtsp_error', handleError);
        // p2pSocket.value.disconnect(); // 不断开连接，由 socketStore 统一管理
        streamerSocket.value = null;
    }
  }

  // --- HTTP 控制 Actions (保持不变, 但移除了轮询) ---
  async function fetchStatus() {
     try {
       const data = await apiRequest('/status');
       handleStatusUpdate(data); // 使用我们的处理器来统一更新状态
     } catch(fetchError) {
        // apiRequest 内部已处理 error state
     }
  }
  
  // startStatusPolling 和 stopStatusPolling 已被移除

  async function startStream() {
    if (!isAvailable.value || isRunning.value) return;
    statusText.value = '启动中...';
    try {
      const response = await apiRequest('/control', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'start' }),
      });
      ElMessage.success(response.result || '推流启动指令已发送');
      // 不再需要 fetchStatus()，后端会通过 Socket.IO 自动推送更新
    } catch (startError) {
        ElMessage.error(`启动推流失败: ${startError.message}`);
        await fetchStatus(); // 出错时主动刷新一次
    }
  }

  async function stopStream() {
    if (!isAvailable.value || !isRunning.value) return;
    statusText.value = '停止中...';
    try {
      const response = await apiRequest('/control', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'stop' }),
      });
      ElMessage.success(response.result || '推流停止指令已发送');
    } catch (stopError) {
        ElMessage.error(`停止推流失败: ${stopError.message}`);
        await fetchStatus();
    }
  }

  async function updateConfig(newConfig) {
    if (!isAvailable.value) return;
    statusText.value = '更新配置中...';
    try {
      const response = await apiRequest('/control', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'set_params', ...newConfig }),
      });
      ElMessage.success(response.result || '配置更新指令已发送');
    } catch (updateError) {
        ElMessage.error(`更新配置失败: ${updateError.message}`);
        await fetchStatus();
    }
  }
  
  async function fetchLogs() { /* ... (保持不变) ... */ }

  return {
    isAvailable, isRunning, statusText, rtspUrl, config, logs, error, delayInfo,
    statusDisplay,
    fetchStatus,
    startStream, stopStream, updateConfig, fetchLogs,
    listenForUpdates, // 暴露给 StreamManager
    stopListening, // 暴露给 SimpleWebRTC
  };
});
