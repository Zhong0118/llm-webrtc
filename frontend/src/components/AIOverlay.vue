<template>
  <div class="ai-overlay-container">
    <div v-if="shouldShow" class="bounding-boxes-layer">
      <div
        v-for="(obj, index) in result.objects"
        :key="index"
        class="bounding-box"
        :style="getBoxStyle(obj.bbox)"
      >
        <span class="box-label">{{ obj.label }} {{ (obj.confidence * 100).toFixed(0) }}%</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue';

const props = defineProps({
  result: Object,       // AI 结果 { peerId: 'xxx', objects: [...] }
  filterPeerId: String, // 当前视频框对应的 PeerID
  videoElement: Object  // 视频 DOM 元素 (用于缩放)
});

// 核心过滤逻辑：只有当结果属于当前视频框的人时，才显示
const shouldShow = computed(() => {
  if (!props.result || !props.result.peerId || !props.filterPeerId) return false;
  return props.result.peerId === props.filterPeerId;
});

const getBoxStyle = (bbox) => {
  // bbox: [x, y, w, h] 原始坐标 (假设模型基于 640x480)
  const refW = 640; 
  const refH = 480;

  if (!props.videoElement) return {};

  const video = props.videoElement;
  const clientW = video.clientWidth;
  const clientH = video.clientHeight;
  
  // 简单的缩放映射
  const scaleX = clientW / refW;
  const scaleY = clientH / refH;

  return {
    left: `${bbox[0] * scaleX}px`,
    top: `${bbox[1] * scaleY}px`,
    width: `${bbox[2] * scaleX}px`,
    height: `${bbox[3] * scaleY}px`
  };
};
</script>

<style scoped>
.ai-overlay-container {
  position: absolute;
  top: 0; left: 0; width: 100%; height: 100%;
  pointer-events: none;
  overflow: hidden;
  z-index: 10; /* 确保在视频之上 */
}

.bounding-box {
  position: absolute;
  border: 2px solid #00ff00;
  box-shadow: 0 0 4px rgba(0, 255, 0, 0.5);
}

.box-label {
  position: absolute;
  top: -22px; left: -2px;
  background-color: #00ff00;
  color: #000;
  font-size: 12px;
  font-weight: bold;
  padding: 1px 4px;
  white-space: nowrap;
}
</style>