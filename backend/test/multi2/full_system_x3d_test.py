"""
Full System X3D Benchmark Test
================================

这个脚本测试不同 chunk_size 和 stride 策略对系统延迟的影响。

改进点（相比原版）：
1. ✅ 修复丢包模拟逻辑（正确跳过帧）
2. ✅ 使用 X3D-S 模型（真正的时序建模）
3. ✅ 优化数据分析（使用 pd.merge 而非 merge_asof）
4. ✅ 添加详细注释

测试架构：
    Client A (Sender)  ──P2P Stream──→  Client B (Receiver)
         │                                      │
         └──AI Stream──→ AI Server              │
                             │                  │
                             └──AI Result───────┘

测试目标：
- 测量 Visual Drift (视觉漂移)：AI 结果到达时间 - P2P 视频到达时间
- 测量 Server Processing Time (服务器处理时间)
- 测量 Match Rate (匹配率)：AI 能跟上多少帧

作者: AI Toolkit Assistant
日期: 2025-12-16
"""

import asyncio
import socketio
import time
import logging
import pandas as pd
import uuid
import random
from typing import List, Dict, Any
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCIceCandidate, VideoStreamTrack
from aiortc.contrib.media import MediaPlayer, MediaBlackhole

# ============================================================
# 日志配置
# ============================================================
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("X3D_SystemTest")

# 屏蔽 aiortc 的详细日志
logging.getLogger("aioice").setLevel(logging.WARNING)
logging.getLogger("aiortc").setLevel(logging.WARNING)

# ============================================================
# 实验配置
# ============================================================
import os
from pathlib import Path

SERVER_URL = "https://localhost:33335"  
# 使用绝对路径确保找到视频文件
VIDEO_FILE = str(Path(__file__).parent / "part1_small.mp4")   

# 网格化实验参数
# 你可以修改下面两个列表来控制组合范围
CHUNK_LIST = [13, 16, 24, 32]
DEFAULT_STRIDE_MODE = "frames"  # 可改为 "pts"

def _stride_candidates(chunk: int):
    """给定 chunk，返回推荐的 stride 候选集合（去重/升序）"""
    cands = {chunk, max(1, chunk // 2), max(1, chunk // 3)}
    return sorted(cands)

def build_experiments():
    exps = []
    for c in CHUNK_LIST:
        for s in _stride_candidates(c):
            # Realtime 档（无计算抖动）
            exps.append({
                "profile": "realtime",
                "desc": f"RT chunk{c}-stride{s}",
                "preset": "realtime",
                "chunk_size": c,
                "stride": s,
                "stride_mode": DEFAULT_STRIDE_MODE,
                "simulate_delay_mean_ms": 0.0,
                "simulate_delay_std_ms": 0.0,
            })
            # Stress 档（30±10ms 计算抖动）
            exps.append({
                "profile": "stress",
                "desc": f"ST chunk{c}-stride{s}",
                "preset": "stress",
                "chunk_size": c,
                "stride": s,
                "stride_mode": DEFAULT_STRIDE_MODE,
                "simulate_delay_mean_ms": 30.0,
                "simulate_delay_std_ms": 10.0,
            })
    return exps

EXPERIMENTS = build_experiments()

# 丢包率配置
PACKET_LOSS_RATE = 0.10  # 10% 丢包率（模拟真实网络）
# 可选：网络抖动（在接收端模拟不稳定到达）。
# 建议使用小幅均值 + 波动，避免阻塞过长。
JITTER_MEAN_MS = 20      # 平均抖动 20ms
JITTER_STD_MS = 10       # 抖动标准差 10ms

# 实验时长（秒）
EXPERIMENT_DURATION = 30  # 每个配置运行 30 秒

# ============================================================
# MetricsVideoSink: 接收端帧记录器
# ============================================================
class MetricsVideoSink(VideoStreamTrack):
    """
    Client B 的视频接收 Track
    
    功能：
    1. 记录每一帧的 PTS（视频时间戳）
    2. 记录帧到达的系统时间
    3. 模拟网络丢包
    
    Attributes:
        track: 原始视频轨道
        received_data: 记录的帧数据 [{pts, p2p_arrival_time}, ...]
        loss_rate: 丢包率（0.0 - 1.0）
    """
    
    def __init__(self, track: VideoStreamTrack, loss_rate: float = 0.0,
                 jitter_mean_ms: float = 0.0, jitter_std_ms: float = 0.0):
        super().__init__()
        self.track = track
        self.received_data: List[Dict] = []
        self.loss_rate = loss_rate
        self.total_frames = 0  # 总接收帧数（含丢弃）
        self.dropped_frames = 0  # 丢弃的帧数
        self.jitter_mean_ms = jitter_mean_ms
        self.jitter_std_ms = jitter_std_ms
    
    async def recv(self):
        """
        接收一帧视频
        
        Returns:
            frame: 视频帧对象
        """
        frame = await self.track.recv()
        self.total_frames += 1
        
        # 可选：在记录前模拟网络抖动（仅影响测量，不影响 WebRTC 渲染）
        if self.jitter_mean_ms or self.jitter_std_ms:
            # 采用正态分布抖动，避免负值
            import math
            delay_ms = max(0.0, random.gauss(self.jitter_mean_ms, self.jitter_std_ms))
            await asyncio.sleep(delay_ms / 1000.0)  # 使用非阻塞休眠

        # 记录到达时间（在丢包判断之前，用于真实性）
        arrival_time = time.time()
        
        # ✅ 修复：正确的丢包逻辑
        # 如果随机数 < 丢包率，则丢弃这一帧（不记录）
        if random.random() < self.loss_rate:
            self.dropped_frames += 1
            # 注意：仍然返回帧给 WebRTC（否则链路会断），但不记录数据
            return frame
        
        # 正常帧：记录数据
        self.received_data.append({
            "pts": frame.pts,
            "p2p_arrival_time": arrival_time
        })
        
        return frame


# ============================================================
# DualClientBenchmark: 双客户端测试框架
# ============================================================
class DualClientBenchmark:
    """
    模拟 Client A 和 Client B 进行端到端测试
    
    工作流程：
    1. Client A 向 AI Server 发送视频流
    2. Client A 通过 P2P 向 Client B 发送视频流
    3. Client B 记录 P2P 视频帧的到达时间
    4. Client B 记录 AI 结果的到达时间
    5. 分析两者的时间差（Visual Drift）
    """
    
    def __init__(self):
        # Socket.IO 客户端
        self.sio_a = socketio.AsyncClient()  # Sender (Client A)
        self.sio_b = socketio.AsyncClient()  # Receiver (Client B)
        
        # 测试标识
        self.room_id = f"x3d_test_{uuid.uuid4().hex[:8]}"
        self.peer_a_id = "client_A_sender"
        self.peer_b_id = "client_B_receiver"
        
        # WebRTC 连接
        self.pc_a_to_ai: RTCPeerConnection = None  # A -> AI Server
        self.pc_a_p2p: RTCPeerConnection = None    # A -> B (Sender)
        self.pc_b_p2p: RTCPeerConnection = None    # A -> B (Receiver)
        
        # 媒体
        self.player_ai: MediaPlayer = None
        self.player_p2p: MediaPlayer = None
        self.metrics_sink: MetricsVideoSink = None
        
        # 数据收集
        self.ai_results: List[Dict] = []
        self.is_running = False
        
        # 结果汇总
        self.results_df = pd.DataFrame()
    
    # ========================================================
    # Socket.IO 信令处理
    # ========================================================
    async def setup_signaling(self):
        """配置 Socket.IO 事件监听器"""
        
        # --- Client A 监听器 ---
        @self.sio_a.on('answer', namespace='/ai_analysis')
        async def on_ai_answer(data):
            """收到 AI Server 的 SDP Answer"""
            if self.pc_a_to_ai:
                desc = RTCSessionDescription(
                    sdp=data['answer']['sdp'], 
                    type=data['answer']['type']
                )
                await self.pc_a_to_ai.setRemoteDescription(desc)
        
        @self.sio_a.on('candidate', namespace='/ai_analysis')
        async def on_ai_candidate(data):
            """收到 AI Server 的 ICE Candidate"""
            if self.pc_a_to_ai:
                c = data['candidate']
                candidate = RTCIceCandidate(
                    component=1,
                    foundation=c.get('foundation', ''),
                    ip=c.get('address', c.get('ip', '')),
                    port=c.get('port', 0),
                    priority=c.get('priority', 0),
                    protocol=c.get('protocol', 'udp'),
                    type=c.get('type', 'host'),
                    sdpMid=c.get('sdpMid'),
                    sdpMLineIndex=c.get('sdpMLineIndex')
                )
                await self.pc_a_to_ai.addIceCandidate(candidate)
        
        @self.sio_a.on('signal', namespace='/p2p')
        async def on_p2p_signal_a(data):
            """处理 P2P 信令（Client A 收到 Answer）"""
            if data.get('type') == 'answer' and self.pc_a_p2p:
                answer = RTCSessionDescription(
                    sdp=data['answer']['sdp'],
                    type=data['answer']['type']
                )
                await self.pc_a_p2p.setRemoteDescription(answer)
        
        # --- Client B 监听器 ---
        @self.sio_b.on('signal', namespace='/p2p')
        async def on_p2p_signal_b(data):
            """处理 P2P 信令（Client B 收到 Offer）"""
            if data.get('type') == 'offer':
                await self.handle_p2p_offer(data)
        
        @self.sio_b.on('ai_result', namespace='/ai_analysis')
        async def on_ai_result(data):
            """收到 AI 分析结果（广播到房间）"""
            if not self.is_running:
                return
            
            # 记录 AI 结果的到达时间
            self.ai_results.append({
                "pts": data.get('pts'),
                "ai_arrival_time": time.time(),
                "label": data.get('label', 'unknown'),
                "confidence": data.get('confidence', 0),
                "d_an": data.get('d_an', 0),  # 服务器处理时间
                "inference_time": data.get('inference_time', 0),
                "chunk_size": data.get('chunk_size', 0)
            })
    
    # ========================================================
    # WebRTC 连接建立
    # ========================================================
    async def connect_sockets(self):
        """连接到服务器并加入房间"""
        logger.info(f"📡 连接到服务器: {SERVER_URL}")
        
        await self.sio_a.connect(SERVER_URL, namespaces=['/p2p', '/ai_analysis'])
        await self.sio_b.connect(SERVER_URL, namespaces=['/p2p', '/ai_analysis'])
        
        # 加入房间
        await self.sio_a.emit('join', {
            'roomId': self.room_id, 
            'peerId': self.peer_a_id
        }, namespace='/p2p')
        
        await self.sio_b.emit('join', {
            'roomId': self.room_id, 
            'peerId': self.peer_b_id
        }, namespace='/p2p')
        
        await self.sio_a.emit('join', {
            'roomId': self.room_id
        }, namespace='/ai_analysis')
        
        await self.sio_b.emit('join', {
            'roomId': self.room_id
        }, namespace='/ai_analysis')
        
        await asyncio.sleep(1)  # 等待加入完成
        logger.info("✅ 已加入房间")
    
    async def start_ai_stream(self):
        """建立 Client A -> AI Server 的连接"""
        logger.info("📡 建立 A -> AI Server 连接...")
        
        self.pc_a_to_ai = RTCPeerConnection()
        
        @self.pc_a_to_ai.on("icecandidate")
        async def on_ice(event):
            if event.candidate:
                await self.sio_a.emit('candidate', {
                    'candidate': event.candidate
                }, namespace='/ai_analysis')
        
        # 添加视频轨道
        self.player_ai = MediaPlayer(VIDEO_FILE, 
            options={"stream_loop": "-1"})
        self.pc_a_to_ai.addTrack(self.player_ai.video)
        
        # 创建 Offer
        offer = await self.pc_a_to_ai.createOffer()
        await self.pc_a_to_ai.setLocalDescription(offer)
        
        # 发送 Offer
        await self.sio_a.emit('offer', {
            'offer': {
                'sdp': self.pc_a_to_ai.localDescription.sdp,
                'type': self.pc_a_to_ai.localDescription.type
            },
            'roomId': self.room_id,
            'peerId': self.peer_a_id
        }, namespace='/ai_analysis')
    
    async def start_p2p_stream(self):
        """建立 Client A -> Client B 的 P2P 连接"""
        logger.info("🔗 建立 A -> B P2P 连接...")
        
        self.pc_a_p2p = RTCPeerConnection()
        self.pc_b_p2p = RTCPeerConnection()
        
        # A 端 ICE
        @self.pc_a_p2p.on("icecandidate")
        async def on_ice_a(event):
            if event.candidate:
                await self.sio_a.emit('signal', {
                    'type': 'candidate',
                    'candidate': event.candidate,
                    'roomId': self.room_id,
                    'to': self.peer_b_id
                }, namespace='/p2p')
        
        # B 端 ICE
        @self.pc_b_p2p.on("icecandidate")
        async def on_ice_b(event):
            if event.candidate:
                await self.sio_b.emit('signal', {
                    'type': 'candidate',
                    'candidate': event.candidate,
                    'roomId': self.room_id,
                    'to': self.peer_a_id
                }, namespace='/p2p')
        
        # B 端接收 Track
        @self.pc_b_p2p.on("track")
        def on_track(track):
            logger.info(f"📹 B 端收到视频轨道: {track.kind}")
            if track.kind == "video":
                # 用 MetricsVideoSink 包装，记录帧数据
                self.metrics_sink = MetricsVideoSink(
                    track,
                    loss_rate=PACKET_LOSS_RATE,
                    jitter_mean_ms=JITTER_MEAN_MS,
                    jitter_std_ms=JITTER_STD_MS
                )
                # 创建消费任务
                asyncio.create_task(self.consume_track())
        
        # A 添加轨道
        self.player_p2p = MediaPlayer(
            VIDEO_FILE, 
            options={"stream_loop": "-1"}
        )
        self.pc_a_p2p.addTrack(self.player_p2p.video)
        
        # A 创建 Offer
        offer = await self.pc_a_p2p.createOffer()
        await self.pc_a_p2p.setLocalDescription(offer)
        
        # 发送 Offer
        await self.sio_a.emit('signal', {
            'type': 'offer',
            'offer': {
                'sdp': self.pc_a_p2p.localDescription.sdp,
                'type': self.pc_a_p2p.localDescription.type
            },
            'roomId': self.room_id,
            'to': self.peer_b_id
        }, namespace='/p2p')
    
    async def handle_p2p_offer(self, data):
        """Client B 处理 P2P Offer"""
        offer_desc = RTCSessionDescription(
            sdp=data['offer']['sdp'],
            type=data['offer']['type']
        )
        await self.pc_b_p2p.setRemoteDescription(offer_desc)
        
        answer = await self.pc_b_p2p.createAnswer()
        await self.pc_b_p2p.setLocalDescription(answer)
        
        await self.sio_b.emit('signal', {
            'type': 'answer',
            'answer': {
                'sdp': self.pc_b_p2p.localDescription.sdp,
                'type': self.pc_b_p2p.localDescription.type
            },
            'roomId': self.room_id,
            'to': self.peer_a_id
        }, namespace='/p2p')
    
    async def consume_track(self):
        """消费 P2P 视频流（驱动 MetricsVideoSink）"""
        try:
            while self.is_running:
                await self.metrics_sink.recv()
        except Exception as e:
            logger.debug(f"Track 消费结束: {e}")
    
    # ========================================================
    # 实验执行
    # ========================================================
    async def run_single_experiment(self, config: Dict, duration: int = 30):
        """
        运行单个实验配置
        
        Args:
            config: 实验配置字典 {chunk_size, stride, desc}
            duration: 实验时长（秒）
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"🧪 开始实验: {config['desc']}")
        logger.info(f"   Chunk Size: {config['chunk_size']}, Stride: {config['stride']}")
        logger.info(f"{'='*60}")
        
        # 1. 更新 AI 配置
        await self.sio_a.emit('update_config', config, namespace='/ai_analysis')
        await asyncio.sleep(0.5)
        
        # 2. 重置数据
        self.is_running = True
        self.ai_results = []
        if self.metrics_sink:
            self.metrics_sink.received_data = []
            self.metrics_sink.total_frames = 0
            self.metrics_sink.dropped_frames = 0
        
        # 3. 同时启动 P2P 和 AI 流
        logger.info("📡 启动视频流...")
        await asyncio.gather(
            self.start_p2p_stream(),
            self.start_ai_stream()
        )
        
        # 4. 等待 AI 首帧（预热）
        logger.info("⏳ 等待 AI 引擎预热...")
        start_wait = time.time()
        while not self.ai_results:
            await asyncio.sleep(0.1)
            if time.time() - start_wait > 30:
                logger.error("❌ AI 预热超时")
                return
        
        warmup_time = time.time() - start_wait
        logger.info(f"✅ AI 已就绪（预热耗时: {warmup_time:.1f}s）")
        
        # 5. 正式收集数据
        logger.info(f"📊 收集数据中（{duration}秒）...")
        await asyncio.sleep(duration)
        
        # 6. 停止
        self.is_running = False
        await self.cleanup_connections()
        
        # 7. 分析数据
        self.analyze_data(config)
        
        logger.info(f"✅ 实验完成: {config['desc']}\n")
    
    async def cleanup_connections(self):
        """清理 WebRTC 连接"""
        if self.pc_a_to_ai:
            await self.pc_a_to_ai.close()
        if self.pc_a_p2p:
            await self.pc_a_p2p.close()
        if self.pc_b_p2p:
            await self.pc_b_p2p.close()
        
        self.pc_a_to_ai = None
        self.pc_a_p2p = None
        self.pc_b_p2p = None
    
    # ========================================================
    # 数据分析
    # ========================================================
    def analyze_data(self, config: Dict):
        """
        分析实验数据
        
        计算指标：
        1. Visual Drift: AI 结果到达时间 - P2P 视频到达时间
        2. Match Rate: AI 能匹配到多少 P2P 帧
        3. Server Processing Time: 服务器处理延迟
        """
        if not self.metrics_sink or not self.metrics_sink.received_data:
            logger.warning("⚠️ 没有 P2P 数据")
            return
        
        if not self.ai_results:
            logger.warning("⚠️ 没有 AI 结果")
            return
        
        # 转为 DataFrame
        df_p2p = pd.DataFrame(self.metrics_sink.received_data)
        df_ai = pd.DataFrame(self.ai_results)
        
        # 确保 PTS 类型一致
        df_p2p['pts'] = df_p2p['pts'].astype(int)
        df_ai['pts'] = df_ai['pts'].astype(int)
        
        # 排序
        df_p2p = df_p2p.sort_values('pts').reset_index(drop=True)
        df_ai = df_ai.sort_values('pts').reset_index(drop=True)
        
        # ✅ 改进：使用 inner join（精确匹配 PTS）
        merged = pd.merge(
            df_ai,
            df_p2p,
            on='pts',
            how='inner',  # 只保留匹配的
            suffixes=('_ai', '_p2p')
        )
        
        if merged.empty:
            logger.warning("⚠️ 没有匹配的帧（AI 和 P2P 无交集）")
            return
        
        # 计算 Visual Drift
        merged['drift'] = (merged['ai_arrival_time'] - merged['p2p_arrival_time']) * 1000  # 毫秒
        
        # 统计指标
        avg_drift = merged['drift'].mean()
        std_drift = merged['drift'].std()
        max_drift = merged['drift'].max()
        min_drift = merged['drift'].min()
        
        avg_d_an = merged['d_an'].mean()
        avg_inference = merged['inference_time'].mean()
        
        match_count = len(merged)
        total_ai = len(df_ai)
        total_p2p = len(df_p2p)
        
        # 打印结果
        logger.info(f"\n📈 实验结果:")
        logger.info(f"   匹配帧数: {match_count} / {total_ai} AI帧 / {total_p2p} P2P帧")
        logger.info(f"   平均漂移: {avg_drift:.1f} ms (±{std_drift:.1f})")
        logger.info(f"   漂移范围: [{min_drift:.1f}, {max_drift:.1f}] ms")
        logger.info(f"   服务器延迟: {avg_d_an:.1f} ms")
        logger.info(f"   纯推理时间: {avg_inference:.1f} ms")
        
        if self.metrics_sink:
            loss_rate = self.metrics_sink.dropped_frames / max(self.metrics_sink.total_frames, 1)
            logger.info(f"   模拟丢包率: {loss_rate:.1%}")
        
        # 保存到结果表
        result_row = {
            "desc": config['desc'],
            "chunk_size": config['chunk_size'],
            "stride": config['stride'],
            "stride_mode": config.get('stride_mode', 'frames'),
            "profile": config.get('profile', 'custom'),
            "simulate_mean_ms": config.get('simulate_delay_mean_ms', 0.0),
            "simulate_std_ms": config.get('simulate_delay_std_ms', 0.0),
            "avg_drift": avg_drift,
            "std_drift": std_drift,
            "max_drift": max_drift,
            "min_drift": min_drift,
            "avg_d_an": avg_d_an,
            "avg_inference": avg_inference,
            "match_count": match_count,
            "total_ai_frames": total_ai,
            "total_p2p_frames": total_p2p,
            "match_rate": match_count / max(total_ai, 1)
        }
        
        self.results_df = pd.concat([
            self.results_df,
            pd.DataFrame([result_row])
        ], ignore_index=True)
    
    # ========================================================
    # 主流程
    # ========================================================
    async def run_all(self):
        """运行所有实验"""
        await self.setup_signaling()
        await self.connect_sockets()
        
        total_experiments = len(EXPERIMENTS)
        
        for i, exp in enumerate(EXPERIMENTS, 1):
            logger.info(f"\n🔬 实验进度: {i}/{total_experiments}")
            
            try:
                await self.run_single_experiment(exp, duration=EXPERIMENT_DURATION)
                
                # 实验间隔（让系统冷却）
                if i < total_experiments:
                    logger.info("⏸️  实验间隔 5 秒...")
                    await asyncio.sleep(5)
                    
            except Exception as e:
                logger.error(f"❌ 实验失败: {e}")
                import traceback
                traceback.print_exc()
        
        # 保存最终结果
        output_file = f"x3d_experiment_results_grid_{int(time.time())}.csv"
        self.results_df.to_csv(output_file, index=False)
        logger.info(f"\n✅ 所有实验完成！结果已保存到: {output_file}")
        
        # 断开连接
        await self.sio_a.disconnect()
        await self.sio_b.disconnect()


# ============================================================
# 主入口
# ============================================================
if __name__ == "__main__":
    logger.info("="*60)
    logger.info("🚀 X3D-S Full System Benchmark")
    logger.info("="*60)
    logger.info(f"服务器: {SERVER_URL}")
    logger.info(f"视频文件: {VIDEO_FILE}")
    logger.info(f"实验配置数量: {len(EXPERIMENTS)}")
    logger.info(f"丢包率: {PACKET_LOSS_RATE:.1%}")
    logger.info(f"每个实验时长: {EXPERIMENT_DURATION}s")
    logger.info("="*60)
    
    bench = DualClientBenchmark()
    
    try:
        asyncio.run(bench.run_all())
    except KeyboardInterrupt:
        logger.info("\n⏹️  用户中断")
    except Exception as e:
        logger.error(f"\n❌ 程序异常: {e}")
        import traceback
        traceback.print_exc()
