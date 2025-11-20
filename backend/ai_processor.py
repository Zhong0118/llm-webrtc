# backend/ai_processor.py
import time
import logging
import numpy as np
import torch
from ultralytics import YOLO

logger = logging.getLogger("AIProcessor")

class AIProcessor:
    def __init__(self):
        self.frame_count = 0
        
        # 1. 加载模型 (自动下载 yolov8n.pt)
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        logger.info(f"🚀 Loading YOLO model on {self.device}...")
        try:
            self.model = YOLO('yolov8n.pt') 
            self.model.to(self.device)
            # 预热
            self.model(np.zeros((640, 640, 3), dtype=np.uint8), verbose=False)
            logger.info("✅ YOLO model loaded successfully")
        except Exception as e:
            logger.error(f"❌ Failed to load YOLO: {e}")
            self.model = None

        # FPS 计算相关
        self.fps_start_time = time.time()
        self.fps_frame_counter = 0
        self.current_fps = 0.0

    def process(self, frame):
        """
        frame: aiortc 的 VideoFrame 对象
        """
        total_start = time.time()
        self.frame_count += 1
        self.fps_frame_counter += 1
        
        # --- 1. 计算 FPS ---
        now = time.time()
        if now - self.fps_start_time >= 1.0:
            self.current_fps = self.fps_frame_counter / (now - self.fps_start_time)
            self.fps_frame_counter = 0
            self.fps_start_time = now

        if self.model is None:
            return {"error": "Model not loaded"}

        # --- 2. 格式转换 (YUV -> BGR) ---
        # WebRTC frame 转为 OpenCV 格式
        img = frame.to_ndarray(format="bgr24")
        
        # --- 3. YOLO 推理 ---
        infer_start = time.time()
        # imgsz=640 是标准尺寸，如果你同学用 320 觉得快，你也可以改这里
        results = self.model(img, imgsz=640, conf=0.4, verbose=False)
        infer_end = time.time()
        
        inference_time_ms = (infer_end - infer_start) * 1000
        
        # --- 4. 解析结果 ---
        detections = []
        if results:
            result = results[0]
            boxes = result.boxes
            if len(boxes) > 0:
                # 提取数据 (参考你同学的逻辑)
                xyxy = boxes.xyxy.cpu().numpy()
                conf = boxes.conf.cpu().numpy()
                cls = boxes.cls.cpu().numpy().astype(int)

                for i in range(len(boxes)):
                    # 这里的 conf 已经在 model 参数里过滤过一次了，但在循环里再判断一次也无妨
                    if conf[i] < 0.4: 
                        continue
                        
                    x1, y1, x2, y2 = map(int, xyxy[i])
                    label = self.model.names[cls[i]]
                    
                    detections.append({
                        "label": label,
                        "confidence": float(conf[i]),
                        "bbox": [x1, y1, x2, y2] # 前端 AIOverlay 需要这个格式
                    })

        # --- 5. 计算总耗时 ---
        total_end = time.time()
        process_time_ms = (total_end - total_start) * 1000

        # --- 6. 返回丰富的数据 ---
        return {
            "type": "yolo_detection",
            "timestamp": total_end,         # 发送时间
            "frame_id": self.frame_count,
            "fps": round(self.current_fps, 1),         # 后端处理 FPS
            "inference_time": round(inference_time_ms, 1), # 纯推理耗时
            "process_time": round(process_time_ms, 1),     # 总处理耗时 (含解码转换)
            "objects": detections
        }