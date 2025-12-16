"""
AI Processor with X3D-S Model for Real-time Video Analysis
===========================================================

这个模块使用 X3D-S (Facebook AI) 进行视频动作识别，专门用于科研实验：
测试不同 chunk_size 和 stride 对延迟的影响。

X3D-S 优势：
- 轻量级：6.0 GFLOPs (比 ResNet3D 少 5x)
- 高精度：Kinetics-400 准确率 73.3%
- 适合 RTX 4060：显存占用 < 2GB
- 真正的 3D CNN：必须处理整个 chunk (C, T, H, W)

作者: AI Toolkit Assistant
日期: 2025-12-16
"""

import time
import logging
import torch
import torch.nn as nn
from collections import deque
from typing import Optional, Dict, Any, Tuple
import numpy as np
import cv2

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("AIProcessor_X3D")

class AIProcessorX3D:
    """
    基于 X3D-S 的视频动作识别处理器
    
    Attributes:
        device (str): 计算设备 ('cuda' 或 'cpu')
        model (nn.Module): X3D-S 模型实例
        config (Dict): 动态配置参数 (chunk_size, stride 等)
        chunk_buffer (deque): 存储预处理后的帧 Tensor
        pts_buffer (deque): 存储对应的 PTS 时间戳
        timestamp_buffer (deque): 存储帧到达的系统时间
    
    Methods:
        warmup(): CUDA 预热，消除首次推理延迟
        update_config(new_config): 动态调整实验参数
        process(frame, pts, time_base): 处理单帧并返回推理结果
    """
    
    def __init__(self):
        """
        初始化 X3D-S 模型和缓冲区
        
        针对 RTX 4060 Laptop (8GB VRAM) 优化：
        - 使用 X3D-S 而非 X3D-M（更轻量）
        - 批次大小固定为 1
        - 启用混合精度（FP16）加速
        """
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        logger.info(f"🚀 初始化 AI Processor (设备: {self.device})")
        
        # ============================================================
        # 1. 加载 X3D-S 模型
        # ============================================================
        try:
            # 动态导入 pytorchvideo（如果未安装会给出友好提示）
            try:
                import pytorchvideo.models.x3d as x3d
                from pytorchvideo.models.hub import x3d_s
            except ImportError:
                raise ImportError(
                    "❌ 缺少 pytorchvideo 库！请安装：\n"
                    "   pip install pytorchvideo\n"
                    "   pip install opencv-python"
                )
            
            logger.info("📥 加载 X3D-S 模型（Kinetics-400 预训练权重）...")
            
            # 加载预训练模型
            self.model = x3d_s(pretrained=True)
            self.model = self.model.to(self.device)
            self.model.eval()  # 设置为评估模式（关闭 Dropout/BatchNorm）
            
            # X3D-S 的类别名称（Kinetics-400 数据集）
            # 包含 'sign language interpretation' 等手势相关类别
            self.class_names = self._load_kinetics_labels()
            
            logger.info(f"✅ X3D-S 模型加载成功！支持 {len(self.class_names)} 个动作类别")
            
        except Exception as e:
            logger.error(f"❌ 模型加载失败: {e}")
            raise e
        
        # ============================================================
        # 2. 动态配置参数
        # ============================================================
        self.config = {
            "chunk_size": 13,      # X3D-S 默认输入帧数（13帧）
            "stride": 1,           # 滑动窗口步长
            "resize_h": 182,       # X3D 输入高度（标准尺寸）
            "resize_w": 182,       # X3D 输入宽度
            "crop_size": 182,      # 中心裁剪尺寸（X3D 使用 182x182）
            "simulate_delay": 0,   # 模拟额外延迟（毫秒）用于实验
            "enable_fp16": True    # 启用 FP16 混合精度（RTX 4060 支持）
        }
        
        # ============================================================
        # 3. 缓冲区初始化
        # ============================================================
        self.max_buffer = 50  # 最大缓冲帧数（防止内存泄漏）
        
        # Tensor 缓冲区（存储预处理后的帧，避免重复转换）
        self.chunk_buffer: deque = deque(maxlen=self.max_buffer)
        
        # PTS 缓冲区（视频帧的 RTP 时间戳，用于前端同步）
        self.pts_buffer: deque = deque(maxlen=self.max_buffer)
        
        # 系统时间缓冲区（用于计算延迟）
        self.timestamp_buffer: deque = deque(maxlen=self.max_buffer)
        
        # ============================================================
        # 4. 归一化参数（Kinetics 数据集统计值）
        # ============================================================
        # X3D 使用的标准归一化参数（与 ImageNet 稍有不同）
        self.mean = torch.tensor(
            [0.45, 0.45, 0.45],  # RGB 均值
            device=self.device
        ).view(3, 1, 1, 1)
        
        self.std = torch.tensor(
            [0.225, 0.225, 0.225],  # RGB 标准差
            device=self.device
        ).view(3, 1, 1, 1)
        
        # ============================================================
        # 5. 性能监控
        # ============================================================
        self.frame_count = 0  # 处理的总帧数
        self.inference_count = 0  # 推理次数
        self.last_infer_time = 0  # 上次推理时间（用于计算 FPS）
        
        logger.info("🎯 AI Processor 初始化完成！")
    
    def _load_kinetics_labels(self) -> list:
        """
        加载 Kinetics-400 数据集的类别标签
        
        Returns:
            list: 400 个动作类别的名称列表
        """
        # Kinetics-400 的标签（简化版，实际应从文件加载）
        # 这里只列出部分常见类别
        labels = [
            "abseiling", "air drumming", "answering questions", "applauding",
            "applying cream", "archery", "arm wrestling", "arranging flowers",
            # ... (省略中间 392 个)
            "sign language interpreting",  # 手语相关！
            "singing", "sipping cup", "skateboarding",
            # ... 
            "zumba"
        ]
        # 实际应该有 400 个，这里简化处理
        # 完整列表可从 pytorchvideo 官方仓库获取
        return labels if len(labels) == 400 else [f"class_{i}" for i in range(400)]
    
    def warmup(self) -> bool:
        """
        CUDA 预热：执行一次 dummy 推理
        
        目的：
        1. 触发 CUDA 初始化（首次调用 CUDA 会有 1-2 秒延迟）
        2. 分配显存（避免首帧推理时分配）
        3. JIT 编译优化路径
        
        Returns:
            bool: 预热是否成功
        """
        logger.info(f"🔥 开始预热 X3D-S 模型（设备: {self.device}）...")
        
        try:
            # 构造 dummy 输入：(Batch=1, C=3, T=13, H=182, W=182)
            dummy_input = torch.randn(
                1, 3, 
                self.config['chunk_size'],
                self.config['crop_size'],
                self.config['crop_size']
            ).to(self.device)
            
            # 执行一次推理（不计算梯度）
            with torch.no_grad():
                if self.config['enable_fp16'] and self.device == 'cuda':
                    # 使用 FP16 加速（RTX 4060 支持 Tensor Cores）
                    with torch.cuda.amp.autocast():
                        _ = self.model(dummy_input)
                else:
                    _ = self.model(dummy_input)
            
            # 同步 GPU（确保操作完成）
            if self.device == 'cuda':
                torch.cuda.synchronize()
            
            logger.info("✅ 预热完成！模型已就绪")
            return True
            
        except Exception as e:
            logger.error(f"❌ 预热失败: {e}")
            return False
    
    def update_config(self, new_config: Dict[str, Any]) -> None:
        """
        动态更新实验配置参数
        
        Args:
            new_config (Dict): 新的配置字典，例如：
                {
                    "chunk_size": 16,
                    "stride": 2,
                    "simulate_delay": 50
                }
        
        Note:
            更新配置后会清空缓冲区，避免混用不同配置的数据
        """
        logger.info(f"🔄 更新配置: {new_config}")
        
        # 更新配置
        self.config.update(new_config)
        
        # 重置缓冲区（避免旧数据污染）
        self.chunk_buffer.clear()
        self.pts_buffer.clear()
        self.timestamp_buffer.clear()
        
        logger.info(f"📊 当前配置: chunk_size={self.config['chunk_size']}, "
                   f"stride={self.config['stride']}")
    
    def _preprocess_frame(self, frame_obj) -> torch.Tensor:
        """
        将 aiortc VideoFrame 转换为 X3D 输入格式
        
        步骤：
        1. YUV -> RGB (aiortc 内部格式转换)
        2. Resize 到 182x182
        3. 中心裁剪（如果需要）
        4. 转为 Tensor (C, H, W)
        5. 归一化到 [0, 1]
        
        Args:
            frame_obj: aiortc 的 VideoFrame 对象
        
        Returns:
            torch.Tensor: 形状为 (3, H, W) 的预处理帧
        
        Raises:
            Exception: 帧转换失败时抛出异常
        """
        try:
            # 1. 转为 RGB ndarray (H, W, C)
            img = frame_obj.to_ndarray(format="rgb24")
            
            # 2. Resize（使用双线性插值）
            img_resized = cv2.resize(
                img, 
                (self.config['resize_w'], self.config['resize_h']),
                interpolation=cv2.INTER_LINEAR
            )
            
            # 3. 中心裁剪（X3D 标准操作）
            # 如果 resize 和 crop 尺寸相同，则跳过
            if self.config['crop_size'] < self.config['resize_h']:
                h, w = img_resized.shape[:2]
                crop_h, crop_w = self.config['crop_size'], self.config['crop_size']
                start_h = (h - crop_h) // 2
                start_w = (w - crop_w) // 2
                img_cropped = img_resized[start_h:start_h+crop_h, start_w:start_w+crop_w]
            else:
                img_cropped = img_resized
            
            # 4. 转为 Tensor: (H, W, C) -> (C, H, W)
            # 并归一化到 [0, 1]
            img_tensor = torch.from_numpy(img_cropped).permute(2, 0, 1).float() / 255.0
            
            return img_tensor
            
        except Exception as e:
            logger.error(f"❌ 帧预处理失败: {e}")
            raise e
    
    def _check_circuit_breaker(self, pts: int) -> bool:
        """
        熔断机制：检测是否发生严重丢包或网络断连
        
        原理：
        - RTP 时间戳（PTS）应该连续递增
        - 如果 PTS 跳跃过大（例如 > 0.5秒），说明中间丢了很多帧
        - 此时应清空缓冲区，避免用过时数据推理
        
        Args:
            pts (int): 当前帧的 PTS（RTP timestamp，单位：90kHz 时钟）
        
        Returns:
            bool: True 表示触发熔断（需要重置），False 表示正常
        """
        if len(self.pts_buffer) == 0:
            return False  # 第一帧，无需检查
        
        # 计算 PTS 差值（90kHz 时钟下，45000 ≈ 0.5秒）
        pts_gap = pts - self.pts_buffer[-1]
        
        # 阈值设置：根据帧率调整
        # 假设 30fps，正常帧间隔 = 90000/30 = 3000 ticks
        # 如果超过 5 帧的间隔（15000 ticks），认为异常
        threshold = 15000
        
        if pts_gap > threshold:
            logger.warning(
                f"⚠️ 检测到时间断层！PTS 跳跃 {pts_gap} ticks "
                f"(约 {pts_gap/90000:.2f}秒)，重置缓冲区"
            )
            return True
        
        return False
    
    def process(
        self, 
        frame, 
        pts: int, 
        time_base
    ) -> Optional[Dict[str, Any]]:
        """
        处理单帧视频：维护 Chunk 缓冲区并在满足条件时执行推理
        
        工作流程：
        1. 检查熔断条件（是否发生丢包）
        2. 预处理当前帧
        3. 将帧加入缓冲区
        4. 检查是否满足推理条件（chunk_size + stride）
        5. 如果满足，执行 3D CNN 推理
        6. 返回推理结果（包含延迟指标）
        
        Args:
            frame: aiortc VideoFrame 对象
            pts (int): 视频帧的 RTP 时间戳（用于前端同步）
            time_base: 视频流的时间基准（通常是 1/90000）
        
        Returns:
            Optional[Dict]: 推理结果字典，包含：
                - type: "ai_result"
                - pts: 当前帧的 PTS（视频同步锚点）
                - label: 识别的动作类别
                - confidence: 置信度分数
                - inference_ms: 纯推理耗时（毫秒）
                - d_an: 端到端延迟（从首帧到达到推理完成）
                - chunk_size: 使用的帧数
            
            如果未满足推理条件，返回 None
        """
        # ============================================================
        # Step 1: 熔断检查
        # ============================================================
        if self._check_circuit_breaker(pts):
            self.chunk_buffer.clear()
            self.pts_buffer.clear()
            self.timestamp_buffer.clear()
        
        # ============================================================
        # Step 2: 预处理当前帧
        # ============================================================
        try:
            tensor_frame = self._preprocess_frame(frame)
        except Exception as e:
            logger.error(f"帧处理失败: {e}")
            return None
        
        # ============================================================
        # Step 3: 数据入队
        # ============================================================
        arrival_time = time.time()  # 记录帧到达时间（用于延迟计算）
        
        self.chunk_buffer.append(tensor_frame)
        self.pts_buffer.append(pts)
        self.timestamp_buffer.append(arrival_time)
        self.frame_count += 1
        
        # ============================================================
        # Step 4: 检查推理条件
        # ============================================================
        target_size = self.config['chunk_size']
        stride = self.config['stride']
        
        # 条件 1: 缓冲区必须填满
        if len(self.chunk_buffer) < target_size:
            return None
        
        # 条件 2: 符合 stride 间隔（简化：每 stride 帧推理一次）
        # 实际可以用更复杂的滑动窗口逻辑
        if (self.frame_count % stride) != 0:
            return None
        
        # ============================================================
        # Step 5: 准备推理输入
        # ============================================================
        # 取缓冲区最后的 target_size 帧
        clip_frames = list(self.chunk_buffer)[-target_size:]
        clip_pts = list(self.pts_buffer)[-target_size:]
        clip_timestamps = list(self.timestamp_buffer)[-target_size:]
        
        # Stack: (T, C, H, W)
        input_tensor = torch.stack(clip_frames).to(self.device)
        
        # Permute: (C, T, H, W) - X3D 的标准输入格式
        input_tensor = input_tensor.permute(1, 0, 2, 3)
        
        # Add batch dimension: (1, C, T, H, W)
        input_tensor = input_tensor.unsqueeze(0)
        
        # Normalize
        input_tensor = (input_tensor - self.mean) / self.std
        
        # ============================================================
        # Step 6: 执行推理
        # ============================================================
        infer_start = time.time()
        
        try:
            with torch.no_grad():
                if self.config['enable_fp16'] and self.device == 'cuda':
                    # 使用混合精度（RTX 4060 支持）
                    with torch.cuda.amp.autocast():
                        preds = self.model(input_tensor)
                else:
                    preds = self.model(input_tensor)
            
            # 同步 GPU（确保推理完成）
            if self.device == 'cuda':
                torch.cuda.synchronize()
            
            # 获取 Top-1 预测
            top_score, top_class = torch.max(preds, 1)
            class_id = top_class.item()
            confidence = torch.softmax(preds, dim=1)[0, class_id].item()
            
            # 获取类别名称
            label = self.class_names[class_id] if class_id < len(self.class_names) else f"class_{class_id}"
            
        except Exception as e:
            logger.error(f"推理失败: {e}")
            return None
        
        infer_end = time.time()
        
        # ============================================================
        # Step 7: 模拟额外延迟（用于实验）
        # ============================================================
        simulate_delay = self.config.get('simulate_delay', 0)
        if simulate_delay > 0:
            time.sleep(simulate_delay / 1000.0)
        
        # ============================================================
        # Step 8: 计算延迟指标
        # ============================================================
        # D_an: 从 Chunk 第一帧到达到推理结束的总时间
        # 这代表用户感知的"服务器处理延迟"
        chunk_start_time = clip_timestamps[0]
        d_an = (infer_end - chunk_start_time) * 1000  # 转为毫秒
        
        # 纯推理时间（不含排队等待）
        inference_time = (infer_end - infer_start) * 1000
        
        # 计算推理 FPS
        fps = 0
        if self.last_infer_time > 0:
            delta = infer_end - self.last_infer_time
            if delta > 0:
                fps = 1.0 / delta
        self.last_infer_time = infer_end
        
        self.inference_count += 1
        
        # ============================================================
        # Step 9: 滑动窗口（清理缓冲区）
        # ============================================================
        # 根据 stride 移除已处理的帧
        # 如果 stride < chunk_size，会保留部分帧（重叠窗口）
        for _ in range(min(len(self.chunk_buffer), stride)):
            self.chunk_buffer.popleft()
            self.pts_buffer.popleft()
            self.timestamp_buffer.popleft()
        
        # ============================================================
        # Step 10: 返回结果
        # ============================================================
        result = {
            "type": "ai_result",
            
            # === 视频同步信息 ===
            "pts": clip_pts[-1],  # 锚定到 Chunk 最后一帧（最新帧）
            "pts_start": clip_pts[0],  # Chunk 起始帧（用于调试）
            "timestamp": clip_pts[-1],  # 兼容前端字段
            "time_base_num": time_base.numerator if time_base else 1,
            "time_base_den": time_base.denominator if time_base else 90000,
            
            # === AI 识别结果 ===
            "label": label,
            "confidence": round(confidence, 4),
            "objects": [{  # 兼容前端格式（原 YOLO 返回 objects 列表）
                "label": label,
                "confidence": round(confidence, 4)
            }],
            
            # === 性能指标（科研用）===
            "inference_time": round(inference_time, 2),  # 纯推理耗时
            "d_an": round(d_an, 2),  # 端到端延迟（含排队）
            "process_time": round(d_an, 2),  # 别名（兼容旧代码）
            "fps": round(fps, 1),  # 推理帧率
            "chunk_size": target_size,  # 使用的帧数
            
            # === 调试信息 ===
            "frame_id": self.frame_count,
            "inference_id": self.inference_count,
            "send_time": infer_end * 1000  # 毫秒时间戳（前端用）
        }
        
        # 定期打印日志（每 10 次推理）
        if self.inference_count % 10 == 0:
            logger.info(
                f"📊 推理 #{self.inference_count} | "
                f"动作: {label[:20]} | "
                f"置信度: {confidence:.2%} | "
                f"延迟: {d_an:.1f}ms | "
                f"FPS: {fps:.1f}"
            )
        
        return result


# ============================================================
# 模块测试（仅当直接运行此文件时执行）
# ============================================================
if __name__ == "__main__":
    """
    简单的单元测试：模拟帧输入并验证输出
    """
    import sys
    
    # 创建 mock 帧对象
    class MockFrame:
        """模拟 aiortc VideoFrame"""
        def __init__(self, pts: int):
            self.pts = pts
            
        def to_ndarray(self, format="rgb24"):
            # 返回随机 RGB 图像 (720p)
            return np.random.randint(0, 255, (720, 1280, 3), dtype=np.uint8)
    
    # 创建 mock 时间基准
    class MockTimeBase:
        numerator = 1
        denominator = 90000
    
    print("=" * 60)
    print("🧪 AI Processor X3D 单元测试")
    print("=" * 60)
    
    # 1. 初始化处理器
    try:
        processor = AIProcessorX3D()
    except ImportError as e:
        print(f"\n❌ {e}")
        sys.exit(1)
    
    # 2. 预热
    if not processor.warmup():
        print("❌ 预热失败")
        sys.exit(1)
    
    # 3. 更新配置（测试小 chunk）
    processor.update_config({
        "chunk_size": 8,
        "stride": 4
    })
    
    # 4. 模拟 20 帧输入
    print("\n📹 模拟视频流输入（30fps）...")
    time_base = MockTimeBase()
    
    for i in range(20):
        # PTS 按 30fps 递增（90000 / 30 = 3000 ticks per frame）
        pts = i * 3000
        frame = MockFrame(pts)
        
        result = processor.process(frame, pts, time_base)
        
        if result:
            print(f"\n✅ 第 {i+1} 帧触发推理:")
            print(f"   动作: {result['label']}")
            print(f"   置信度: {result['confidence']:.2%}")
            print(f"   延迟: {result['d_an']:.1f}ms")
            print(f"   Chunk: {result['chunk_size']} 帧")
    
    print("\n" + "=" * 60)
    print(f"✅ 测试完成！共处理 {processor.frame_count} 帧，"
          f"执行 {processor.inference_count} 次推理")
    print("=" * 60)
