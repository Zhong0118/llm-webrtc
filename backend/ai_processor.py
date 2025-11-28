# backend/ai_processor.py (科研升级版)
import time
import logging
import numpy as np
from collections import deque
import torch
from ultralytics import YOLO
import random

logger = logging.getLogger("AIProcessor")

class AIProcessor:
    def __init__(self):
        self.frame_count = 0
        
        # 1. 模型加载 (YOLO 仅作演示，实际可替换为手语模型)
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        logger.info(f"🚀 Loading model on {self.device}...")
        self.model = YOLO('yolov8n.pt') 
        self.model.to(self.device)

        # 2. [科研核心] 动态配置参数
        # 这些参数现在可以通过前端或测试脚本动态修改，不用重启服务器
        self.config = {
            "chunk_size": 1,      # 默认单帧 (实时)
            "stride": 1,          # 步长
            "simulate_drift": 80   # 模拟额外耗时
        }
        
        # 时序缓冲区
        self.chunk_buffer = deque(maxlen=30) 
        self.timestamp_buffer = deque(maxlen=30)
        self.pts_buffer = deque(maxlen=30)
        self.last_infer_time = 0

    def update_config(self, new_config):
        """供测试脚本动态调整实验参数"""
        self.config.update(new_config)
        # 重置缓冲区以适应新配置
        self.chunk_buffer.clear()
        self.timestamp_buffer.clear()
        self.pts_buffer.clear()
        logger.info(f"🧪 实验参数更新: {self.config}")

    def warmup(self):
        """
        预热
        执行一次空推理，完成 CUDA 初始化、显存申请和 JIT 编译。
        解决 '首帧延迟 7秒' 的问题。
        """
        logger.info(f"🔥 AI Engine Warming up on {self.device}...")
        try:
            # 创建一个 640x640 的全黑 dummy frame
            dummy_input = np.zeros((640, 640, 3), dtype=np.uint8)
            # 执行一次推理 (这次会很慢)
            self.model(dummy_input, verbose=False)
            logger.info("✅ AI Engine Ready! (Warmup completed)")
        except Exception as e:
            logger.error(f"❌ Warmup failed: {e}")
            return False
        return True

    def _apply_simulated_delay(self):
        """在推理后注入额外延迟，便于模拟高负载场景"""
        simulate_delay_ms = max(0, self.config.get("simulate_drift", 0))
        if simulate_delay_ms:
            time.sleep(simulate_delay_ms / 1000.0)
        return simulate_delay_ms

    def process(self, frame, pts, time_base):
        """
        1. 输入增加了 pts (RTP时间戳) 和 time_base (时间基准)
        2. 维护两套时间轴：SystemTime 用于计算性能延迟，PTS 用于前端视觉同步
        3. 增加了 '熔断机制' 应对网络丢包
        """
        # --- 1. 完整性检查 (熔断机制) ---
        # 如果当前帧和上一帧的 PTS 差值过大（例如超过 0.5秒），说明中间发生了严重丢包或卡顿
        # 此时必须清空缓冲区
        if len(self.pts_buffer) > 0:
            # 90000 是常见的视频时钟频率，0.5秒约等于 45000
            # 这里的阈值可以根据实际 fps 调整，比如 fps=30，帧间隔 3000，阈值设为 15000 (5帧丢包)
            time_gap = pts - self.pts_buffer[-1]
            if time_gap > 45000: 
                logger.warning(f"⚠️ [Flow Break] 检测到时间断层 ({time_gap} ticks), 重置 Chunk")
                self.chunk_buffer.clear()
                self.timestamp_buffer.clear()
                self.pts_buffer.clear()

        # --- 2. 数据入队 ---
        try:
            img = frame.to_ndarray(format="bgr24")
        except Exception as e:
            logger.error(f"Frame conversion failed: {e}")
            return None
        
        self.chunk_buffer.append(img)
        self.timestamp_buffer.append(time.time()) # System Time: 用于计算 D_an (延迟)
        self.pts_buffer.append(pts)               # RTP PTS: 用于前端 <video> 同步
        
        self.frame_count += 1
        
        # --- 3. Chunking 策略 ---
        target_size = self.config['chunk_size']
        stride = self.config['stride']
        
        should_infer = (len(self.chunk_buffer) >= target_size) and \
                       (self.frame_count % stride == 0)
        
        if not should_infer:
            return None 

        # --- 4. 开始推理 ---

        # *模拟网络抖动
        jitter = random.uniform(0.03, 0.1) 
        time.sleep(jitter)


        infer_start = time.time()
        
        # 选取最具代表性的一帧 (通常是 Chunk 的最后一帧，也就是最新的一帧)
        target_img = self.chunk_buffer[-1] 
        target_pts = self.pts_buffer[-1]     # <--- 关键：这是这帧画面的"身份证"
        
        results = self.model(target_img, verbose=False)

        # !人为注入额外延迟，用于模拟高负载/高延迟场景
        # self._apply_simulated_delay()
        
        infer_end = time.time()

        fps = 0
        if self.last_infer_time > 0:
            delta = infer_end - self.last_infer_time
            if delta > 0:
                fps = 1.0 / delta
        self.last_infer_time = infer_end
        
        # --- 5. 科研指标计算 ---
        # D_an: 从 Chunk 第一帧到达服务器(SystemTime) 到 推理结束(SystemTime)
        # 这代表了用户感知的"服务器处理总耗时" (含排队等待时间)
        chunk_arrival_time = self.timestamp_buffer[0]
        d_an = (infer_end - chunk_arrival_time) * 1000
        
        # 收集结果
        detections = []
        mean_conf = 0
        if results:
            for box in results[0].boxes:
                conf = float(box.conf[0].cpu().numpy())
                mean_conf += conf
                detections.append({
                    "label": self.model.names[int(box.cls[0])],
                    "bbox": box.xyxy[0].cpu().numpy().astype(int).tolist(),
                    "confidence": round(conf, 2)
                })
            if len(results[0].boxes) > 0:
                mean_conf /= len(results[0].boxes)

        # 推理完成后，根据 Stride 滑动窗口
        # 如果是实时性优先，通常推理完就清空，或者只保留后半部分
        # 这里演示简单清空
        self.chunk_buffer.clear()
        self.timestamp_buffer.clear()
        self.pts_buffer.clear()




        return {
            "type": "ai_result",
            "frame_id": self.frame_count,      # 仅供调试用的计数器

            "pts": target_pts,                 # 1. 视频身份证 (用于画框同步)
            "send_time": infer_end * 1000,     # 2. 发送时间戳 (毫秒，用于前端算延迟)
            
            # --- [严谨同步的核心] ---
            "timestamp": target_pts,           # RTP PTS (例如 23481902)
            "time_base_num": time_base.numerator,
            "time_base_den": time_base.denominator,
            
            # --- [科研数据] ---
            "d_an": round(d_an, 2),            # 全链路服务器延迟
            "mean_confidence": round(mean_conf, 4),
            "fps": round(fps, 1),              # 3. 补全 FPS
            "inference_time": round((infer_end - infer_start) * 1000, 2),
            "process_time": round((infer_end - chunk_arrival_time) * 1000, 2), # 总处理耗时
            "objects": detections
            
        }