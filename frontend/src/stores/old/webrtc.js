/**
 * @file webrtc.js
 * @description WebRTC AI视频分析系统的核心状态管理模块
 * @author AI Assistant
 * @version 1.0.0
 * @created 2025
 * /

/**
 * WebRTC状态管理Store
 * 使用Pinia的组合式API风格定义，管理整个WebRTC应用的状态
 * 
 * @returns {Object} 返回包含状态、计算属性和方法的对象
 */

import { ref, computed } from 'vue'
import { defineStore } from 'pinia'

export const useWebRTCStore = defineStore('webrtc', () => {
  // 初始化连接标志
  const isInitializing = ref(false)
  /**
   * 连接状态
   * @type {Ref<string>}
   * @description 表示当前WebRTC连接的状态'disconnected': 未连接（初始状态）'connecting': 连接中（正在建立连接）'connected': 已连接（可以进行音视频通话）
   */
  const connectionState = ref('disconnected')
  const isConnected = computed(() => connectionState.value === 'connected')

  // 房间管理状态
  const roomId = ref(null)
  const clientCount = ref(0)
  const isRoomReady = ref(false)

  // 本地媒体流
  const localStream = ref(null)
  const hasLocalStream = computed(() => !!localStream.value)

  // 远程媒体流
  const remoteStream = ref(null)
  const hasRemoteStream = computed(() => !!remoteStream.value)

    /**
   * 通话活跃状态检查
   * @type {ComputedRef<boolean>}
   * @description 检查视频通话是否处于活跃状态（双方都有视频流）
   * @returns {boolean} true表示通话活跃，false表示通话未建立
   * 
   * 用途：
   * - 判断是否可以进行AI分析
   * - 控制通话相关功能的启用
   * - 用于整体通话状态显示
   */
  const isCallActive = computed(() => hasLocalStream.value && hasRemoteStream.value)

  
  /**
   * WebRTC点对点连接对象
   * @type {Ref<RTCPeerConnection|null>}
   * @description WebRTC的核心对象，负责建立浏览器间的直接连接
   * - null: 未创建连接
   * - RTCPeerConnection: 活跃的P2P连接对象
   * 功能：处理媒体流传输、ICE候选交换、连接状态管理
   */
  const peerConnection = ref(null)
  
  /**
   * Socket.IO连接对象
   * @type {Ref<Socket|null>}
   * @description 与信令服务器的WebSocket连接
   * - null: 未连接到信令服务器
   * - Socket: 活跃的Socket连接
   * 作用：交换SDP信令、ICE候选、传输AI分析数据
   */
  const socket = ref(null)
  
  // 可用设备列表
  const availableDevices = ref({
    cameras: [],      // 存储所有摄像头设备
    microphones: [],  // 存储所有麦克风设备
    speakers: []      // 存储所有扬声器设备
  })

    // 可用设备数量统计
  const deviceCount = computed(() => {
    const { cameras, microphones, speakers } = availableDevices.value
    return cameras.length + microphones.length + speakers.length
  })
  
  // 当前选中的设备
  const selectedDevices = ref({
    camera: null,      // 当前使用的摄像头ID
    microphone: null,  // 当前使用的麦克风ID
    speaker: null      // 当前使用的扬声器ID
  })
  
  // 媒体流参数
  const streamSettings = ref({
    video: {
      enabled: true,    // 启用视频流
      width: 1280,      // 1280像素宽度（高清）
      height: 720,      // 720像素高度（720p）
      frameRate: 30     // 30帧每秒（流畅度）
    },
    audio: {
      enabled: true,           // 启用音频流
      echoCancellation: true,  // 开启回声消除（防止扬声器声音被麦克风捕获）
      noiseSuppression: true   // 开启噪声抑制（减少背景噪音）
    }
  })

  // 手语翻译结果（轻量方案）
  const signLanguageResults = ref([])
  const latestSignLanguage = computed(() => {
    const arr = signLanguageResults.value
    return arr.length ? arr[arr.length - 1] : null
  })

  // AI分析配置参数
  const analysisSettings = ref({
    interval: 2000,
    faceDetection: true,
    objectDetection: true,
    emotionAnalysis: false,
    confidenceThreshold: 0.5,  // 置信度阈值
    maxResults: 200  // 最大结果保存数量
  })
  const maxResults = computed(() => analysisSettings.value.maxResults || 200)

  /**
   * 错误信息集合
   * @type {Ref<Array>}
   * @description 存储系统运行过程中产生的各种错误信息
   * 
   * 每个错误对象包含：
   * - id: 错误唯一标识符
   * - type: 错误类型（'connection', 'media', 'analysis', 'system'等）
   * - message: 错误描述信息
   * - timestamp: 错误发生时间
   * - level: 错误级别（'error', 'warning', 'info'）
   * - details: 详细错误信息（可选）
   */
  const errors = ref([])

  // 流媒体传输状态
  const isStreamingState = ref(false)
  
  // AI分析功能开关
  const isAnalysisEnabled = ref(true)
  
  // 帧过滤器开关 控制是否启用视频帧过滤功能 提供视频美化功能 可能影响AI分析的准确性 增加视频处理的计算开销
  const isFrameFilterEnabled = ref(false)

  // WebRTC统计信息
  const statistics = ref({
    video: {
      codec: null,
      resolution: null,
      frameRate: 0,
      bitrate: 0
    },
    audio: {
      codec: null,
      bitrate: 0
    },
    connection: {
      latency: 0,
      packetLoss: 0
    }
  })

  // ==================== VLC推流状态管理 ====================
  
  /**
   * VLC推流状态
   * @type {Ref<Object>}
   * @description 管理VLC推流的状态信息
   */
  const vlcStreamState = ref({
    isAvailable: false,      // VLC模块是否可用
    isStreaming: false,      // 是否正在推流
    status: 'stopped',       // 推流状态: 'stopped', 'starting', 'streaming', 'stopping', 'error'
    config: null,            // 当前推流配置
    logs: [],               // 推流日志
    error: null,            // 错误信息
    lastUpdate: null        // 最后更新时间
  })

  /**
   * VLC推流配置
   * @type {Ref<Object>}
   * @description VLC推流的配置参数
   */
  const vlcStreamConfig = ref({
    input_source: 'Integrated Camera',  // 输入源（摄像头名称或文件路径）
    rtsp_url: 'rtsp://localhost:8554/mystream',  // RTSP推流地址
    resolution: '640x480',             // 分辨率
    fps: 30,                           // 帧率
    crf: 28,                           // 视频质量（CRF值）
    preset: 'ultrafast',               // 编码预设
    ffmpeg_path: 'ffmpeg'              // FFmpeg路径
  })

  /**
   * 视频源类型
   * @type {Ref<string>}
   * @description 当前使用的视频源类型
   * - 'webrtc': 使用WebRTC摄像头
   * - 'vlc': 使用VLC推流
   */
  const videoSourceType = ref('webrtc')

  // VLC推流状态计算属性
  const isVlcAvailable = computed(() => vlcStreamState.value.isAvailable)
  const isVlcStreaming = computed(() => vlcStreamState.value.isStreaming)
  const vlcStatus = computed(() => vlcStreamState.value.status)
  const vlcError = computed(() => vlcStreamState.value.error)


  const initializeWebRTC = async () => {
    // 防止重复初始化
    if (isInitializing.value) return
    // 设置初始化状态
    isInitializing.value = true
    connectionState.value = 'connecting'
    try {
      // 初始化Socket连接
      await connectSocket()
      // 获取用户媒体
      await getUserMedia()
      // 标记连接成功
      connectionState.value = 'connected'
    } catch (error) {
      console.error('WebRTC初始化失败:', error)
      connectionState.value = 'disconnected'
      throw error
    } finally {
      isInitializing.value = false
    }
  }
  
  const connectSocket = async () => {
    // 动态导入Socket.IO客户端
    const { io } = await import('socket.io-client')
    
    return new Promise((resolve, reject) => {
      try {
        // 如果已有连接，先断开
        if (socket.value) {
          socket.value.disconnect()
          socket.value = null
        }
        // Socket.IO连接配置
        const socketOptions = {
          // 传输方式配置
          transports: ['websocket', 'polling'], // WebSocket优先，降级到polling
          upgrade: true, // 允许传输升级
          // 连接配置
          timeout: 10000, // 连接超时10秒
          forceNew: true, // 强制创建新连接
          // 重连配置
          reconnection: true, // 启用自动重连
          reconnectionAttempts: 5, // 最大重连次数
          reconnectionDelay: 1000, // 重连延迟1秒
          reconnectionDelayMax: 5000, // 最大重连延迟5秒
          // 其他配置
          autoConnect: true, // 自动连接
          randomizationFactor: 0.5 // 重连延迟随机化因子
        }
        // 创建Socket连接
        console.log('正在连接Socket服务器...')
        socket.value = io(socketOptions)

        socket.value.on('connect', () => {
          console.log('✅ Socket连接成功', {
            id: socket.value.id,
            transport: socket.value.io.engine.transport.name,
            upgraded: socket.value.io.engine.upgraded
          })
          // 更新连接状态
          setConnectionState('connected')
          // 清除连接错误
          errors.value = errors.value.filter(error => error.type !== 'socket')
          resolve()
        })
        socket.value.on('connect_error', (error) => {
          console.error('❌ Socket连接错误:', error)
          errors.value.push({
            type: 'socket',
            message: `连接失败: ${error.message}`,
            timestamp: new Date().toISOString(),
            details: error
          })
          setConnectionState('disconnected')
          reject(new Error(`Socket连接失败: ${error.message}`))
        })

        socket.value.on('disconnect', (reason) => {
          console.warn('⚠️ Socket连接断开:', reason)
          setConnectionState('disconnected')
          // 记录断开原因
          errors.value.push({
            type: 'socket',
            message: `连接断开: ${reason}`,
            timestamp: new Date().toISOString(),
            details: { reason }
          })
        })
        socket.value.on('reconnect_attempt', (attemptNumber) => {
          console.log(`🔄 Socket重连尝试 ${attemptNumber}/5`)
          setConnectionState('connecting')
        })
        socket.value.on('reconnect', (attemptNumber) => {
          console.log(`✅ Socket重连成功，尝试次数: ${attemptNumber}`)
          setConnectionState('connected')
          errors.value = errors.value.filter(error => 
            error.type !== 'socket' || !error.message.includes('重连')
          )
        })
        socket.value.on('reconnect_failed', () => {
          console.error('❌ Socket重连失败，已达到最大重连次数')
          errors.value.push({
            type: 'socket',
            message: '重连失败，请检查网络连接或服务器状态',
            timestamp: new Date().toISOString(),
            details: { maxAttempts: 5 }
          })
          setConnectionState('failed')
        })

        // todo 需要在后端服务器配置相关方法

        socket.value.on('webrtc_offer', async (offer) => {
          console.log('📨 收到WebRTC Offer')
          try {
            await handleWebRTCOffer(offer)
          } catch (error) {
            console.error('处理WebRTC Offer失败:', error)
          }
        })
        socket.value.on('webrtc_answer', async (answer) => {
          console.log('📨 收到WebRTC Answer')
          try {
            await handleWebRTCAnswer(answer)
          } catch (error) {
            console.error('处理WebRTC Answer失败:', error)
          }
        })
        socket.value.on('ice_candidate', async (candidate) => {
          console.log('📨 收到ICE候选')
          try {
            await handleICECandidate(candidate)
          } catch (error) {
            console.error('处理ICE候选失败:', error)
          }
        })
        // 已去除通用AI分析结果通道，前端不再记录物体/人脸等统计
        // 如需恢复，可重新监听 'analysis_result' 并调用对应处理
        // 手语翻译结果（占位）
        socket.value.on('sign_language_translation', (result) => {
          console.log('🤟 收到手语翻译结果', result)
          addSignLanguageResult(result)
        })
        socket.value.on('system_message', (message) => {
          console.log('📢 系统消息:', message)
        })
        
        // 房间管理事件
        socket.value.on('room_joined', (data) => {
          console.log('🏠 已加入房间:', data)
          roomId.value = data.room_id
          clientCount.value = data.client_count
        })
        
        socket.value.on('room_ready', (data) => {
          console.log('✅ 房间准备就绪:', data)
          isRoomReady.value = true
        })
        
        // 设置连接超时
        const connectTimeout = setTimeout(() => {
          if (socket.value && !socket.value.connected) {
            console.error('❌ Socket连接超时')
            socket.value.disconnect()
            reject(new Error('Socket连接超时'))
          }
        }, socketOptions.timeout)
        socket.value.on('connect', () => {
          clearTimeout(connectTimeout)
        })
      } catch (error) {
        console.error('❌ Socket初始化失败:', error)
        reject(error)
      }
    })
  }
  
  const getUserMedia = async () => {
    try {
      // 根据当前设置请求用户媒体
      const stream = await navigator.mediaDevices.getUserMedia({
        video: streamSettings.value.video,
        audio: streamSettings.value.audio
      })
      // 保存到本地流状态
      localStream.value = stream
      console.log('获取到本地媒体流:', stream)
      return stream
    } catch (error) {
      console.error('获取用户媒体失败:', error)
      throw error
    }
  }

  const setConnectionState = (state) => {
    connectionState.value = state
  }

  const setLocalStream = (stream) => {
    localStream.value = stream
  }
  
  const setRemoteStream = (stream) => {
    remoteStream.value = stream
  }
  
  const updateDevices = async () => {
    try {
      const devices = await navigator.mediaDevices.enumerateDevices()
      availableDevices.value = {
        cameras: devices.filter(device => device.kind === 'videoinput'),
        microphones: devices.filter(device => device.kind === 'audioinput'),
        speakers: devices.filter(device => device.kind === 'audiooutput')
      }
    } catch (error) {
      console.error('获取设备列表失败:', error)
    }
  }
  
  /**
   * 添加手语翻译结果
   * @function addSignLanguageResult
   * @param {Object} result - { text, confidence, source, timestamp }
   */
  const addSignLanguageResult = (result) => {
    signLanguageResults.value.push({
      ...result,
      id: Date.now(),
      localTime: new Date().toLocaleString()
    })
    if (signLanguageResults.value.length > maxResults.value) {
      signLanguageResults.value.shift()
    }
  }

  /**
   * 清空手语翻译结果
   */
  const clearSignLanguageResults = () => {
    signLanguageResults.value = []
  }
  
  /**
   * 清空错误信息
   */
  const clearErrors = () => {
    errors.value = []
  }
  
  /**
   * 更新AI分析设置
   * @function updateAnalysisSettings
   * @param {Object} settings - 新的分析设置对象
   * @description 更新AI分析的配置参数
   * 
   * 可配置的设置包括：
   * @param {number} settings.interval - 分析间隔时间（毫秒）
   * @param {boolean} settings.faceDetection - 是否启用人脸检测
   * @param {boolean} settings.objectDetection - 是否启用物体检测
   * @param {boolean} settings.emotionAnalysis - 是否启用情感分析
   * @param {number} settings.confidenceThreshold - 置信度阈值（0-1）
   * @param {number} settings.maxResults - 最大结果保存数量
   * 
   * 用途：
   * - 调整分析频率和性能
   * - 开关不同的检测功能
   * - 设置结果过滤条件
   * - 控制内存使用量
   */
  const updateAnalysisSettings = (settings) => {
    Object.assign(analysisSettings.value, settings)
  }
  
  // ==================== WebRTC信令处理函数 ====================
  
  /**
   * 处理WebRTC Offer信令
   * @async
   * @function handleWebRTCOffer
   * @param {RTCSessionDescription} offer - 接收到的WebRTC Offer
   * @description 处理来自远程对等端的连接请求
   * 
   * 处理流程：
   * 1. 创建PeerConnection（如果不存在）
   * 2. 设置远程描述（Remote Description）
   * 3. 创建应答（Answer）
   * 4. 设置本地描述（Local Description）
   * 5. 通过Socket发送Answer给对方
   * 
   * 用途：
   * - 响应远程连接请求
   * - 建立WebRTC通信通道
   * - 交换媒体能力信息
   */
  const handleWebRTCOffer = async (offer) => {
    try {
      // 确保有PeerConnection
      if (!peerConnection.value) {
        await createPeerConnection()
      }
      
      // 设置远程描述
      await peerConnection.value.setRemoteDescription(new RTCSessionDescription(offer))
      console.log('✅ 设置远程描述成功')
      
      // 创建应答
      const answer = await peerConnection.value.createAnswer()
      await peerConnection.value.setLocalDescription(answer)
      console.log('✅ 创建并设置本地应答成功')
      
      // 发送应答给对方
      if (socket.value && socket.value.connected) {
        socket.value.emit('webrtc_answer', answer)
        console.log('📤 发送WebRTC Answer')
      } else {
        throw new Error('Socket未连接，无法发送Answer')
      }
      
    } catch (error) {
      console.error('❌ 处理WebRTC Offer失败:', error)
      errors.value.push({
        type: 'webrtc',
        message: `处理Offer失败: ${error.message}`,
        timestamp: new Date().toISOString(),
        details: error
      })
      throw error
    }
  }
  
  /**
   * 处理WebRTC Answer信令
   * @async
   * @function handleWebRTCAnswer
   * @param {RTCSessionDescription} answer - 接收到的WebRTC Answer
   * @description 处理来自远程对等端的连接应答
   * 
   * 处理流程：
   * 1. 验证PeerConnection存在
   * 2. 设置远程描述（Remote Description）
   * 3. 完成WebRTC连接建立
   * 
   * 用途：
   * - 完成WebRTC握手过程
   * - 建立媒体传输通道
   * - 确认连接参数
   */
  const handleWebRTCAnswer = async (answer) => {
    try {
      // 验证PeerConnection存在
      if (!peerConnection.value) {
        throw new Error('PeerConnection不存在，无法处理Answer')
      }
      
      // 设置远程描述
      await peerConnection.value.setRemoteDescription(new RTCSessionDescription(answer))
      console.log('✅ 设置远程应答描述成功')
      
    } catch (error) {
      console.error('❌ 处理WebRTC Answer失败:', error)
      errors.value.push({
        type: 'webrtc',
        message: `处理Answer失败: ${error.message}`,
        timestamp: new Date().toISOString(),
        details: error
      })
      throw error
    }
  }
  
  /**
   * 处理ICE候选信令
   * @async
   * @function handleICECandidate
   * @param {RTCIceCandidate} candidate - 接收到的ICE候选
   * @description 处理网络连接候选信息，用于NAT穿透
   * 
   * 处理流程：
   * 1. 验证PeerConnection存在
   * 2. 添加ICE候选到PeerConnection
   * 3. 尝试建立最佳网络路径
   * 
   * 用途：
   * - 实现NAT穿透
   * - 寻找最佳网络路径
   * - 建立直接P2P连接
   * - 处理网络变化
   */
  const handleICECandidate = async (candidate) => {
    try {
      // 验证PeerConnection存在
      if (!peerConnection.value) {
        console.warn('⚠️ PeerConnection不存在，忽略ICE候选')
        return
      }
      
      // 添加ICE候选
      await peerConnection.value.addIceCandidate(new RTCIceCandidate(candidate))
      console.log('✅ 添加ICE候选成功')
      
    } catch (error) {
      console.error('❌ 处理ICE候选失败:', error)
      errors.value.push({
        type: 'webrtc',
        message: `处理ICE候选失败: ${error.message}`,
        timestamp: new Date().toISOString(),
        details: error
      })
      // ICE候选失败不抛出错误，因为可能有多个候选
    }
  }
  
  /**
   * 创建WebRTC对等连接
   * @async
   * @function createPeerConnection
   * @description 创建并配置WebRTC PeerConnection对象
   * 
   * 配置内容：
   * 1. ICE服务器配置（STUN/TURN）
   * 2. 事件监听器设置
   * 3. 媒体流处理
   * 4. 连接状态监控
   * 
   * 用途：
   * - 建立P2P连接基础
   * - 配置网络穿透
   * - 设置媒体传输
   * - 监控连接状态
   */
  const createPeerConnection = async () => {
    try {
      // WebRTC配置
      const rtcConfig = {
        iceServers: [
          { urls: 'stun:stun.l.google.com:19302' },
          { urls: 'stun:stun1.l.google.com:19302' },
          // 如果需要TURN服务器，可以在这里添加
          // { 
          //   urls: 'turn:your-turn-server.com:3478',
          //   username: 'username',
          //   credential: 'password'
          // }
        ],
        iceCandidatePoolSize: 10
      }
      
      // 创建PeerConnection
      peerConnection.value = new RTCPeerConnection(rtcConfig)
      console.log('✅ PeerConnection创建成功')
      
      // ==================== 事件监听器 ====================
      
      /**
       * ICE候选事件
       */
      peerConnection.value.onicecandidate = (event) => {
        if (event.candidate && socket.value && socket.value.connected) {
          console.log('📤 发送ICE候选')
          socket.value.emit('ice_candidate', event.candidate)
        }
      }
      
      /**
       * 远程流接收事件
       */
      peerConnection.value.ontrack = (event) => {
        console.log('📨 接收到远程媒体流')
        setRemoteStream(event.streams[0])
      }
      
      /**
       * 连接状态变化事件
       */
      peerConnection.value.onconnectionstatechange = () => {
        const state = peerConnection.value.connectionState
        console.log('🔄 PeerConnection状态变化:', state)
        
        switch (state) {
          case 'connected':
            console.log('✅ WebRTC连接建立成功')
            connectionState.value = 'connected'
            break
          case 'disconnected':
            console.warn('⚠️ WebRTC连接断开')
            connectionState.value = 'disconnected'
            break
          case 'failed':
            console.error('❌ WebRTC连接失败')
            connectionState.value = 'failed'
            errors.value.push({
              type: 'webrtc',
              message: 'WebRTC连接失败',
              timestamp: new Date().toISOString(),
              details: { connectionState: state }
            })
            break
          case 'closed':
            console.log('🔒 WebRTC连接已关闭')
            connectionState.value = 'disconnected'
            break
        }
      }
      
      /**
       * ICE连接状态变化事件
       */
      peerConnection.value.oniceconnectionstatechange = () => {
        const state = peerConnection.value.iceConnectionState
        console.log('🧊 ICE连接状态:', state)
        
        if (state === 'failed' || state === 'disconnected') {
          // ICE连接失败，可能需要重新连接
          console.warn('⚠️ ICE连接问题，状态:', state)
        }
      }

      
    } catch (error) {
      console.error('❌ 创建PeerConnection失败:', error)
      errors.value.push({
        type: 'webrtc',
        message: `创建PeerConnection失败: ${error.message}`,
        timestamp: new Date().toISOString(),
        details: error
      })
      throw error
    }
  }
  
  /**
   * 开始视频通话
   * @async
   * @function startCall
   * @description 启动WebRTC视频通话的完整流程
   * 
   * 执行步骤：
   * 1. 初始化Socket连接（如果未连接）
   * 2. 获取用户媒体流（摄像头、麦克风）
   * 3. 创建PeerConnection并配置H.264编解码器
   * 4. 添加本地流到PeerConnection
   * 5. 创建并发送Offer信令
   * 
   * 用途：
   * - 发起视频通话
   * - 建立WebRTC连接
   * - 配置媒体传输
   */
  const startCall = async () => {
    try {
      console.log('🚀 开始启动视频通话...')
      
      // 1. 确保Socket连接
      if (!socket.value || !socket.value.connected) {
        console.log('📡 初始化Socket连接...')
        await connectSocket()
      }

      // 2. 获取用户媒体流
      console.log('📹 获取用户媒体流...')
      const stream = await getUserMedia()
      
      // 3. 创建PeerConnection
      console.log('🔗 创建PeerConnection...')
      await createPeerConnection()

      // 4. 添加本地流到PeerConnection

      console.log('📤 添加本地流到PeerConnection...')
      stream.getTracks().forEach(track => {
        peerConnection.value.addTrack(track, stream)
      })
      // 5. 配置H.264编解码器
      console.log('⚙️ 配置H.264编解码器...')
      await configureCodecs()



      // 6. 创建并发送Offer
      console.log('📋 创建WebRTC Offer...')
      const offer = await peerConnection.value.createOffer({
        offerToReceiveAudio: true,
        offerToReceiveVideo: true
      })
      
      await peerConnection.value.setLocalDescription(offer)
      console.log('✅ 设置本地描述成功')

      // 7. 发送Offer到服务器
      if (socket.value && socket.value.connected) {
        socket.value.emit('webrtc_offer', offer)
        console.log('📤 发送WebRTC Offer到服务器')
      } else {
        throw new Error('Socket未连接，无法发送Offer')
      }

      // 8. 更新状态
      isStreamingState.value = true
      console.log('✅ 视频通话启动成功')

    } catch (error) {
      console.error('❌ 启动视频通话失败:', error)
      errors.value.push({
        type: 'webrtc',
        message: `启动通话失败: ${error.message}`,
        timestamp: new Date().toISOString(),
        details: error
      })
      throw error
    }
  }

  /**
   * 配置H.264编解码器
   * @async
   * @function configureCodecs
   * @description 为WebRTC连接配置首选的H.264视频编解码器和AAC音频编解码器
   * 
   * 配置内容：
   * 1. 检测浏览器支持的编解码器
   * 2. 优先选择H.264视频编解码器
   * 3. 优先选择AAC音频编解码器
   * 4. 应用编解码器配置到PeerConnection
   * 
   * 用途：
   * - 优化视频质量和压缩率
   * - 确保跨平台兼容性
   * - 减少带宽占用
   */
  const configureCodecs = async () => {
    try {
      if (!peerConnection.value) {
        throw new Error('PeerConnection不存在，无法配置编解码器');
      }

      // 找到负责发送视频的收发器 (Transceiver)
      const videoTransceiver = peerConnection.value.getTransceivers().find(
        t => t.sender && t.sender.track && t.sender.track.kind === 'video'
      );

      if (videoTransceiver && typeof videoTransceiver.setCodecPreferences === 'function') {
        // 获取浏览器支持的所有视频编解码器能力
        const capabilities = RTCRtpSender.getCapabilities('video');
        
        if (capabilities && capabilities.codecs) {
          // 从支持列表中筛选出所有的 H.264 相关的编解码器
          const preferredCodecs = capabilities.codecs.filter(
            codec => codec.mimeType.toLowerCase() === 'video/h264'
          );
          
          // 如果找到了 H.264 编解码器，就设置偏好
          if (preferredCodecs.length > 0) {
            console.log('✅ 设置H.264为首选编解码器...');
            // 调用新的API来设置偏好
            videoTransceiver.setCodecPreferences(preferredCodecs);
          } else {
            console.warn('⚠️ 浏览器不支持H.264，将使用默认编解码器。');
          }
        }
      } else {
        console.warn('⚠️ 无法找到视频收发器或浏览器不支持 setCodecPreferences API。');
      }
    } catch (error) {
      console.error('❌ 配置编解码器失败:', error);
      // 同样，配置失败不应中断通话
      errors.value.push({
        type: 'webrtc',
        message: `编解码器配置失败: ${error.message}`,
        timestamp: new Date().toISOString(),
        details: error,
        level: 'warning'
      });
    }
  };

  /**
   * 开始统计信息收集
   * @function startStatsCollection
   * @description 开始收集WebRTC连接的实时统计信息
   * 
   * 收集的统计信息：
   * - 视频帧率 (frameRate)
   * - 传输码率 (bitrate)
   * - 视频分辨率 (resolution)
   * - 使用的编解码器 (codec)
   * - 网络延迟 (latency)
   * 
   * 用途：
   * - 监控连接质量
   * - 性能分析和优化
   * - 用户体验评估
   */
  const startStatsCollection = () => {
    if (!peerConnection.value) {
      console.warn('⚠️ PeerConnection不存在，无法收集统计信息')
      return
    }

    const statsInterval = setInterval(async () => {
      try {
        // 检查连接状态
        if (!peerConnection.value || peerConnection.value.connectionState !== 'connected') {
          clearInterval(statsInterval)
          return
        }

        // 获取统计报告
        const statsReport = await peerConnection.value.getStats()
        const newStats = {
          frameRate: 0,
          bitrate: 0,
          resolution: '',
          codec: '',
          latency: 0
        }

        statsReport.forEach(stat => {
          // 视频接收统计
          if (stat.type === 'inbound-rtp' && stat.kind === 'video') {
            newStats.frameRate = stat.framesPerSecond || 0
            newStats.bitrate = Math.round((stat.bytesReceived * 8) / 1000) // kbps
            newStats.codec = stat.codecId || ''
          }
          
          // 视频轨道统计
          if (stat.type === 'track' && stat.kind === 'video') {
            if (stat.frameWidth && stat.frameHeight) {
              newStats.resolution = `${stat.frameWidth}x${stat.frameHeight}`
            }
          }
          
          // 网络延迟统计
          if (stat.type === 'candidate-pair' && stat.state === 'succeeded') {
            newStats.latency = stat.currentRoundTripTime ? 
              Math.round(stat.currentRoundTripTime * 1000) : 0 // ms
          }
        })

        
      } catch (error) {
        console.error('❌ 收集统计信息失败:', error)
        clearInterval(statsInterval)
      }
    }, 1000) // 每秒更新一次

    console.log('📊 开始收集WebRTC统计信息')
  }

  /**
   * 停止视频通话
   * @function stopCall
   * @description 停止当前的视频通话并清理相关资源
   * 
   * 执行步骤：
   * 1. 停止本地媒体流
   * 2. 关闭PeerConnection
   * 3. 断开Socket连接
   * 4. 重置状态变量
   * 
   * 用途：
   * - 主动结束通话
   * - 释放系统资源
   * - 重置应用状态
   */
  const stopCall = () => {
    try {
      console.log('🛑 停止视频通话...')

      // 停止本地媒体流
      if (localStream.value) {
        localStream.value.getTracks().forEach(track => {
          track.stop()
          console.log(`🔇 停止${track.kind}轨道`)
        })
        localStream.value = null
      }

      // 清理远程媒体流
      if (remoteStream.value) {
        remoteStream.value.getTracks().forEach(track => track.stop())
        remoteStream.value = null
      }

      // 关闭PeerConnection
      if (peerConnection.value) {
        peerConnection.value.close()
        peerConnection.value = null
        console.log('🔒 关闭PeerConnection')
      }

      // 断开Socket连接
      if (socket.value) {
        socket.value.disconnect()
        socket.value = null
        console.log('📡 断开Socket连接')
      }

      // 重置状态
      isStreamingState.value = false
      connectionState.value = 'disconnected'
      console.log('✅ 视频通话已停止')

    } catch (error) {
      console.error('❌ 停止通话时发生错误:', error)
      errors.value.push({
        type: 'webrtc',
        message: `停止通话失败: ${error.message}`,
        timestamp: new Date().toISOString(),
        details: error
      })
    }
  }

  /**
   * 清理和释放所有资源
   * @function cleanup
   * @description 完全清理WebRTC系统，释放所有占用的资源
   * 
   * 清理内容：
   * 1. 停止并释放本地媒体流（摄像头、麦克风）
   * 2. 停止并释放远程媒体流
   * 3. 关闭WebRTC对等连接
   * 4. 断开Socket连接
   * 5. 重置连接状态
   * 
   * 用途：
   * - 应用关闭时的资源清理
   * - 通话结束后的状态重置
   * - 错误恢复时的完全重置
   * - 防止内存泄漏和资源占用
   * 
   * 注意：调用此方法后需要重新初始化才能使用WebRTC功能
   */
  const cleanup = () => {
    // 使用stopCall来清理资源，避免代码重复
    stopCall()
  }

  // ==================== VLC推流管理函数 ====================

  /**
   * 获取VLC推流状态
   * @returns {Promise<void>}
   */
  const getVlcStatus = async () => {
    try {
      const response = await fetch('/api/vlc/status')
      if (response.ok) {
        const data = await response.json()
        vlcStreamState.value = {
          ...vlcStreamState.value,
          isAvailable: data.available,
          isStreaming: data.streaming,
          status: data.status,
          config: data.config,
          error: data.error,
          lastUpdate: new Date()
        }
      }
    } catch (error) {
      console.error('获取VLC状态失败:', error)
      vlcStreamState.value.error = error.message
    }
  }

  /**
   * 启动VLC推流
   * @returns {Promise<boolean>}
   */
  const startVlcStream = async () => {
    try {
      vlcStreamState.value.status = 'starting'
      vlcStreamState.value.error = null
      
      const response = await fetch('/api/vlc/start', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(vlcStreamConfig.value)
      })
      
      if (response.ok) {
        const data = await response.json()
        vlcStreamState.value.isStreaming = true
        vlcStreamState.value.status = 'streaming'
        console.log('VLC推流启动成功')
        return true
      } else {
        const error = await response.json()
        vlcStreamState.value.error = error.error
        vlcStreamState.value.status = 'error'
        console.error('VLC推流启动失败:', error.error)
        return false
      }
    } catch (error) {
      console.error('启动VLC推流时出错:', error)
      vlcStreamState.value.error = error.message
      vlcStreamState.value.status = 'error'
      return false
    }
  }

  /**
   * 停止VLC推流
   * @returns {Promise<boolean>}
   */
  const stopVlcStream = async () => {
    try {
      vlcStreamState.value.status = 'stopping'
      
      const response = await fetch('/api/vlc/stop', {
        method: 'POST'
      })
      
      if (response.ok) {
        vlcStreamState.value.isStreaming = false
        vlcStreamState.value.status = 'stopped'
        vlcStreamState.value.error = null
        console.log('VLC推流已停止')
        return true
      } else {
        const error = await response.json()
        vlcStreamState.value.error = error.error
        vlcStreamState.value.status = 'error'
        console.error('VLC推流停止失败:', error.error)
        return false
      }
    } catch (error) {
      console.error('停止VLC推流时出错:', error)
      vlcStreamState.value.error = error.message
      vlcStreamState.value.status = 'error'
      return false
    }
  }

  /**
   * 更新VLC推流配置
   * @param {Object} newConfig - 新的配置参数
   * @returns {Promise<boolean>}
   */
  const updateVlcConfig = async (newConfig) => {
    try {
      const response = await fetch('/api/vlc/config', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(newConfig)
      })
      
      if (response.ok) {
        vlcStreamConfig.value = { ...vlcStreamConfig.value, ...newConfig }
        console.log('VLC配置更新成功')
        return true
      } else {
        const error = await response.json()
        console.error('VLC配置更新失败:', error.error)
        return false
      }
    } catch (error) {
      console.error('更新VLC配置时出错:', error)
      return false
    }
  }

  /**
   * 获取VLC推流日志
   * @returns {Promise<void>}
   */
  const getVlcLogs = async () => {
    try {
      const response = await fetch('/api/vlc/logs')
      if (response.ok) {
        const data = await response.json()
        vlcStreamState.value.logs = data.logs || []
      }
    } catch (error) {
      console.error('获取VLC日志失败:', error)
    }
  }

  /**
   * 切换视频源类型
   * @param {string} sourceType - 视频源类型 ('webrtc' 或 'vlc')
   */
  const switchVideoSource = async (sourceType) => {
    if (sourceType === videoSourceType.value) return
    
    try {
      if (sourceType === 'vlc') {
        // 切换到VLC推流
        if (!vlcStreamState.value.isAvailable) {
          throw new Error('VLC模块不可用')
        }
        
        // 停止WebRTC
        if (isStreamingState.value) {
          stopCall()
        }
        
        videoSourceType.value = 'vlc'
        console.log('已切换到VLC推流源')
        
      } else if (sourceType === 'webrtc') {
        // 切换到WebRTC
        // 停止VLC推流
        if (vlcStreamState.value.isStreaming) {
          await stopVlcStream()
        }
        
        videoSourceType.value = 'webrtc'
        console.log('已切换到WebRTC摄像头源')
      }
    } catch (error) {
      console.error('切换视频源失败:', error)
      throw error
    }
  }

  return {
    
    isInitializing,
    connectionState,
    localStream,
    remoteStream,
    peerConnection,
    socket,
    availableDevices,
    selectedDevices,
    streamSettings,
    analysisSettings,
    errors,
    isStreamingState,
    isAnalysisEnabled,
    isFrameFilterEnabled,
    statistics,
    signLanguageResults,
    latestSignLanguage,
    roomId,
    clientCount,
    isRoomReady,
    
    
    isConnected,
    hasLocalStream,
    hasRemoteStream,
    isCallActive,
    deviceCount,
    maxResults,
    
    
    initializeWebRTC,
    connectSocket,
    getUserMedia,
    setConnectionState,
    setLocalStream,
    setRemoteStream,
    updateDevices,
    clearSignLanguageResults,
    clearErrors,
    updateAnalysisSettings,
    cleanup,
    
    handleWebRTCOffer,
    handleWebRTCAnswer,
    handleICECandidate,
    createPeerConnection,
    startCall,
    stopCall,
    configureCodecs,
    startStatsCollection,

    // VLC推流相关状态
    vlcStreamState,
    vlcStreamConfig,
    videoSourceType,
    isVlcAvailable,
    isVlcStreaming,
    vlcStatus,
    vlcError,
    
    // VLC推流相关方法
    getVlcStatus,
    startVlcStream,
    stopVlcStream,
    updateVlcConfig,
    getVlcLogs,
    switchVideoSource

  }

})