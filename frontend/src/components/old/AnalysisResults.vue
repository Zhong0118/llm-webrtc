<template>
  <div class="analysis-results">
    <el-card class="results-card">
      <template #header>
        <div class="card-header">
          <span>
            <el-icon><DataAnalysis /></el-icon>
            手语翻译（轻量）
          </span>
          <div class="header-actions">
            <el-button size="small" @click="clearSL">
              <el-icon><Delete /></el-icon>
              清空
            </el-button>
            <el-button 
              size="small" 
              :type="autoScroll ? 'primary' : 'default'"
              @click="toggleAutoScroll"
            >
              <el-icon><Sort /></el-icon>
              {{ autoScroll ? '停止滚动' : '自动滚动' }}
            </el-button>
          </div>
        </div>
      </template>
      <!-- 手语翻译结果列表 -->
      <div class="results-list" ref="resultsListRef">
        <el-timeline>
          <el-timeline-item
            v-for="result in displaySL"
            :key="result.id"
            :timestamp="result.localTime"
            placement="top"
          >
            <el-card class="result-item">
              <div class="result-content">
                <!-- 手语翻译文本 -->
                <div class="detection-section">
                  <h4>
                    <el-icon><Sunny /></el-icon>
                    翻译
                  </h4>
                  <div class="emotions-grid">
                    <el-tag :type="(result.confidence||0) > 0.6 ? 'success' : 'info'">
                      {{ result.text }}
                    </el-tag>
                    <el-text size="small" type="info" style="margin-left:10px;">
                      置信度: {{ ((result.confidence||0) * 100).toFixed(0) }}%
                    </el-text>
                  </div>
                </div>
              </div>
            </el-card>
          </el-timeline-item>
        </el-timeline>
        <!-- 空状态 -->
        <el-empty v-if="slCount === 0" description="暂无手语翻译结果" />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import { useWebRTCStore } from '@/stores/old/webrtc'
import { storeToRefs } from 'pinia'
import {
  DataAnalysis,
  Delete,
  Sort,
  Sunny
} from '@element-plus/icons-vue'

const store = useWebRTCStore()
const resultsListRef = ref(null)
const autoScroll = ref(true)
const loading = ref(false)
const pageSize = 20
const currentPage = ref(1)

// 从store获取手语翻译数据（保持响应性）
const { signLanguageResults, latestSignLanguage } = storeToRefs(store)

// 时间格式化，保证 timestamp 为字符串避免 UI 内部调用 toString 出错
const formatTimestamp = (ts) => {
  if (!ts) return ''
  try {
    const d = typeof ts === 'number' || typeof ts === 'string' ? new Date(ts) : ts
    return d.toLocaleString()
  } catch {
    return ''
  }
}

// 计算属性
const displaySL = computed(() => {
  const endIndex = currentPage.value * pageSize
  return (signLanguageResults.value || [])
    .slice(0, endIndex)
    .map(r => ({
      ...r,
      localTime: r.localTime || formatTimestamp(r.timestamp)
    }))
})

const slCount = computed(() => (signLanguageResults.value || []).length)

// 监听新结果，自动滚动
watch(latestSignLanguage, () => {
  if (autoScroll.value) {
    nextTick(() => {
      scrollToBottom()
    })
  }
})

// 方法
const clearSL = () => {
  store.clearSignLanguageResults()
  currentPage.value = 1
}

const toggleAutoScroll = () => {
  autoScroll.value = !autoScroll.value
}

const loadMoreResults = () => {
  loading.value = true
  setTimeout(() => {
    currentPage.value++
    loading.value = false
  }, 500)
}

const scrollToBottom = () => {
  if (resultsListRef.value) {
    resultsListRef.value.scrollTop = resultsListRef.value.scrollHeight
  }
}
</script>

<style scoped>
.analysis-results {
  height: 100%;
}

.results-card {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}

.latest-result {
  margin-bottom: 20px;
}

.latest-content {
  display: flex;
  flex-direction: column;
  gap: 5px;
}


.results-list {
  flex: 1;
  overflow-y: auto;
  max-height: 600px;
}

.result-item {
  margin-bottom: 10px;
}

.result-content {
  display: flex;
  flex-direction: column;
  gap: 15px;
}

.detection-section h4 {
  margin: 0 0 10px 0;
  display: flex;
  align-items: center;
  gap: 5px;
  color: #409eff;
}

.faces-grid,
.objects-grid,
.emotions-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.face-tag,
.object-tag,
.emotion-tag {
  margin: 0;
}

.processing-info {
  display: flex;
  align-items: center;
  gap: 5px;
  padding-top: 10px;
  border-top: 1px solid #eee;
}

.load-more {
  text-align: center;
  padding: 20px;
}

/* 滚动条样式 */
.results-list::-webkit-scrollbar {
  width: 6px;
}

.results-list::-webkit-scrollbar-track {
  background: #f1f1f1;
  border-radius: 3px;
}

.results-list::-webkit-scrollbar-thumb {
  background: #c1c1c1;
  border-radius: 3px;
}

.results-list::-webkit-scrollbar-thumb:hover {
  background: #a8a8a8;
}
</style>