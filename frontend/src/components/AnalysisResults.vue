<template>
  <div class="analysis-results">
    <el-card class="results-card">
      <template #header>
        <div class="card-header">
          <span>
            <el-icon><DataAnalysis /></el-icon>
            AI分析结果
          </span>
          <div class="header-actions">
            <el-badge :value="analysisCount" class="item">
              <el-button size="small" @click="clearResults">
                <el-icon><Delete /></el-icon>
                清空
              </el-button>
            </el-badge>
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

      <!-- 最新结果概览 -->
      <div v-if="latestAnalysis" class="latest-result">
        <el-alert
          :title="`最新检测: ${latestAnalysis.localTime}`"
          type="success"
          :closable="false"
        >
          <template #default>
            <div class="latest-content">
              <div v-if="latestAnalysis.faces && latestAnalysis.faces.length > 0">
                <strong>人脸检测:</strong> 发现 {{ latestAnalysis.faces.length }} 张人脸
              </div>
              <div v-if="latestAnalysis.objects && latestAnalysis.objects.length > 0">
                <strong>物体检测:</strong> {{ latestAnalysis.objects.map(obj => obj.label).join(', ') }}
              </div>
              <div v-if="latestAnalysis.confidence">
                <strong>置信度:</strong> {{ (latestAnalysis.confidence * 100).toFixed(1) }}%
              </div>
            </div>
          </template>
        </el-alert>
      </div>

      <!-- 统计信息 -->
      <div class="statistics">
        <el-row :gutter="20">
          <el-col :span="6">
            <el-statistic title="总检测次数" :value="analysisCount" />
          </el-col>
          <el-col :span="6">
            <el-statistic title="人脸检测" :value="faceDetectionCount" />
          </el-col>
          <el-col :span="6">
            <el-statistic title="物体检测" :value="objectDetectionCount" />
          </el-col>
          <el-col :span="6">
            <el-statistic title="平均置信度" :value="averageConfidence" suffix="%" />
          </el-col>
        </el-row>
      </div>

      <!-- 结果列表 -->
      <div class="results-list" ref="resultsListRef">
        <el-timeline>
          <el-timeline-item
            v-for="result in displayResults"
            :key="result.id"
            :timestamp="result.localTime"
            placement="top"
          >
            <el-card class="result-item">
              <div class="result-content">
                <!-- 人脸检测结果 -->
                <div v-if="result.faces && result.faces.length > 0" class="detection-section">
                  <h4>
                    <el-icon><User /></el-icon>
                    人脸检测 ({{ result.faces.length }})
                  </h4>
                  <div class="faces-grid">
                    <el-tag
                      v-for="(face, index) in result.faces"
                      :key="index"
                      class="face-tag"
                      :type="getFaceTagType(face.confidence)"
                    >
                      人脸 {{ index + 1 }} - {{ (face.confidence * 100).toFixed(1) }}%
                    </el-tag>
                  </div>
                </div>

                <!-- 物体检测结果 -->
                <div v-if="result.objects && result.objects.length > 0" class="detection-section">
                  <h4>
                    <el-icon><Box /></el-icon>
                    物体检测 ({{ result.objects.length }})
                  </h4>
                  <div class="objects-grid">
                    <el-tag
                      v-for="(obj, index) in result.objects"
                      :key="index"
                      class="object-tag"
                      :type="getObjectTagType(obj.confidence)"
                    >
                      {{ obj.label }} - {{ (obj.confidence * 100).toFixed(1) }}%
                    </el-tag>
                  </div>
                </div>

                <!-- 其他分析结果 -->
                <div v-if="result.emotions && result.emotions.length > 0" class="detection-section">
                  <h4>
                    <el-icon><Sunny /></el-icon>
                    情感分析
                  </h4>
                  <div class="emotions-grid">
                    <el-tag
                      v-for="(emotion, index) in result.emotions"
                      :key="index"
                      class="emotion-tag"
                      type="warning"
                    >
                      {{ emotion.emotion }} - {{ (emotion.confidence * 100).toFixed(1) }}%
                    </el-tag>
                  </div>
                </div>

                <!-- 处理时间 -->
                <div class="processing-info">
                  <el-text size="small" type="info">
                    <el-icon><Timer /></el-icon>
                    处理时间: {{ result.processingTime || 'N/A' }}ms
                  </el-text>
                </div>
              </div>
            </el-card>
          </el-timeline-item>
        </el-timeline>

        <!-- 加载更多 -->
        <div v-if="hasMoreResults" class="load-more">
          <el-button @click="loadMoreResults" :loading="loading">
            加载更多
          </el-button>
        </div>

        <!-- 空状态 -->
        <el-empty v-if="analysisCount === 0" description="暂无分析结果" />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import { useWebRTCStore } from '@/stores/webrtc'
import {
  DataAnalysis,
  Delete,
  Sort,
  User,
  Box,
  Sunny,
  Timer
} from '@element-plus/icons-vue'

const store = useWebRTCStore()
const resultsListRef = ref(null)
const autoScroll = ref(true)
const loading = ref(false)
const pageSize = 20
const currentPage = ref(1)

// 从store获取数据
const { analysisResults, latestAnalysis, analysisCount } = store

// 计算属性
const displayResults = computed(() => {
  const endIndex = currentPage.value * pageSize
  return analysisResults.slice(0, endIndex)
})

const hasMoreResults = computed(() => {
  return analysisResults.length > displayResults.value.length
})

const faceDetectionCount = computed(() => {
  return analysisResults.filter(result => 
    result.faces && result.faces.length > 0
  ).length
})

const objectDetectionCount = computed(() => {
  return analysisResults.filter(result => 
    result.objects && result.objects.length > 0
  ).length
})

const averageConfidence = computed(() => {
  if (analysisResults.length === 0) return 0
  
  const totalConfidence = analysisResults.reduce((sum, result) => {
    return sum + (result.confidence || 0)
  }, 0)
  
  return (totalConfidence / analysisResults.length * 100).toFixed(1)
})

// 监听新结果，自动滚动
watch(latestAnalysis, () => {
  if (autoScroll.value) {
    nextTick(() => {
      scrollToBottom()
    })
  }
})

// 方法
const clearResults = () => {
  store.clearAnalysisResults()
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

const getFaceTagType = (confidence) => {
  if (confidence > 0.8) return 'success'
  if (confidence > 0.6) return 'warning'
  return 'danger'
}

const getObjectTagType = (confidence) => {
  if (confidence > 0.8) return 'success'
  if (confidence > 0.6) return 'warning'
  return 'danger'
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

.statistics {
  margin-bottom: 20px;
  padding: 15px;
  background: #f8f9fa;
  border-radius: 6px;
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