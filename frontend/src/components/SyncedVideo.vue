<template>
  <div class="synced-player">
    <video 
      ref="sourceVideo" 
      autoplay playsinline muted 
      style="display: none;" 
    />
    
    <canvas ref="renderCanvas" width="640" height="480" />
    
    <div class="debug-info">Buffer: {{ bufferSize }}ms | Delay: {{ targetDelay }}ms</div>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue';

const props = defineProps(['stream', 'aiResultsMap']);
const sourceVideo = ref(null);
const renderCanvas = ref(null);
const bufferSize = ref(0);

// 配置：目标延迟 (比如 200ms，让视频故意慢 0.2s 等 AI)
const targetDelay = 200; 
// 帧缓冲区: [{ bitmap: ImageBitmap, timestamp: number }]
const frameBuffer = [];

// 1. 启动循环：从 Video 抓取帧存入 Buffer
const startCaptureLoop = () => {
  const video = sourceVideo.value;
  
  const capture = async () => {
    if (video.readyState >= 2) {
      // 创建高性能位图
      const bitmap = await createImageBitmap(video);
      frameBuffer.push({
        bitmap: bitmap,
        timestamp: performance.now() // 记录采集时间
      });
      
      // 简单的内存保护
      if (frameBuffer.length > 60) {
         const old = frameBuffer.shift();
         old.bitmap.close(); // 务必释放内存
      }
    }
    // WebRTC 也是按帧率来的，用 requestVideoFrameCallback 最准
    if (video.requestVideoFrameCallback) {
      video.requestVideoFrameCallback(capture);
    } else {
      requestAnimationFrame(capture);
    }
  };
  capture();
};

// 2. 启动循环：从 Buffer 取出“过期”帧进行渲染
const startRenderLoop = () => {
  const ctx = renderCanvas.value.getContext('2d');
  
  const render = () => {
    const now = performance.now();
    
    // 寻找“应该播放”的那一帧
    // 规则：帧的时间戳 < 当前时间 - 目标延迟
    while (frameBuffer.length > 0) {
      const frame = frameBuffer[0];
      if (now - frame.timestamp >= targetDelay) {
        // 这一帧“成熟”了，可以播了
        // A. 画视频
        ctx.drawImage(frame.bitmap, 0, 0);
        
        // B. 画 AI 框 (同步核心)
        // 在这里去 aiStore 里找 timestamp 匹配的结果
        // drawAIBox(ctx, frame.timestamp);
        
        // 移除并释放
        frameBuffer.shift();
        frame.bitmap.close(); 
      } else {
        // 还没到时间，等着
        break;
      }
    }
    
    // 更新调试信息
    if(frameBuffer.length > 0) {
       bufferSize.value = Math.round(now - frameBuffer[0].timestamp);
    }
    
    requestAnimationFrame(render);
  };
  render();
};

watch(() => props.stream, (s) => {
  if (sourceVideo.value && s) {
    sourceVideo.value.srcObject = s;
    sourceVideo.value.play().then(() => {
      startCaptureLoop();
      startRenderLoop();
    });
  }
});
</script>