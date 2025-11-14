// HTTP客户端配置
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { getApiBase } from './config.js'

// 创建axios实例
const http = axios.create({
  baseURL: getApiBase(),
  timeout: 10000, // 10秒超时
  headers: {
    'Content-Type': 'application/json'
  }
})

// 请求拦截器
http.interceptors.request.use(
  (config) => {
    // 可以在这里添加认证token等
    console.log('发送请求:', config.method?.toUpperCase(), config.url)
    return config
  },
  (error) => {
    console.error('请求错误:', error)
    return Promise.reject(error)
  }
)

// 响应拦截器
http.interceptors.response.use(
  (response) => {
    console.log('收到响应:', response.status, response.config.url)
    return response
  },
  (error) => {
    console.error('响应错误:', error)
    
    // 统一错误处理
    let message = '请求失败'
    
    if (error.response) {
      // 服务器返回错误状态码
      const { status, data } = error.response
      switch (status) {
        case 400:
          message = data?.message || '请求参数错误'
          break
        case 401:
          message = '未授权访问'
          break
        case 403:
          message = '禁止访问'
          break
        case 404:
          message = '请求的资源不存在'
          break
        case 500:
          message = '服务器内部错误'
          break
        case 502:
          message = '网关错误'
          break
        case 503:
          message = '服务不可用'
          break
        default:
          message = data?.message || `HTTP ${status}: ${error.response.statusText}`
      }
    } else if (error.request) {
      // 网络错误
      message = '网络连接失败，请检查网络设置'
    } else {
      // 其他错误
      message = error.message || '未知错误'
    }
    
    // 显示错误消息（可选，根据需要启用）
    // ElMessage.error(message)
    
    // 创建标准化的错误对象
    const standardError = new Error(message)
    standardError.status = error.response?.status
    standardError.data = error.response?.data
    standardError.originalError = error
    
    return Promise.reject(standardError)
  }
)

// 便捷方法
export const httpGet = (url, config = {}) => http.get(url, config)
export const httpPost = (url, data = {}, config = {}) => http.post(url, data, config)
export const httpPut = (url, data = {}, config = {}) => http.put(url, data, config)
export const httpDelete = (url, config = {}) => http.delete(url, config)
export const httpPatch = (url, data = {}, config = {}) => http.patch(url, data, config)

// 导出axios实例
export default http