import asyncio
import socketio
import time
import logging
import pandas as pd
import uuid
import random
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCIceCandidate, VideoStreamTrack
from aiortc.contrib.media import MediaPlayer, MediaBlackhole

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("FullSystemDiff")
# 屏蔽 aiortc 繁琐的 debug 日志
logging.getLogger("aioice").setLevel(logging.WARNING)
logging.getLogger("aiortc").setLevel(logging.WARNING)

SERVER_URL = "https://localhost:33335"  
VIDEO_FILE = "part1.mp4"         
EXPERIMENTS = [
    {"chunk_size": 1,  "stride": 1, "desc": "1.Baseline (Realtime)1-1"},
    {"chunk_size": 5,  "stride": 2, "desc": "2.Short Window5-2"},
    {"chunk_size": 10, "stride": 1, "desc": "3.Medium Window (High Load)10-1"},
    {"chunk_size": 10, "stride": 2, "desc": "4.Medium Window (Balanced)10-2"},
    {"chunk_size": 10, "stride": 5, "desc": "5.Medium Window (Low Load)10-5"},
    {"chunk_size": 20, "stride": 1, "desc": "6.Long Window (High Load)20-1"},
    {"chunk_size": 20, "stride": 2, "desc": "7.Long Window (Standard)20-2"},
    {"chunk_size": 20, "stride": 5, "desc": "8.Long Window (Efficient)20-5"},
]

# 容差设置 (用于 merge_asof) 90 ticks = 1ms
tolerance_space = [90 * x for x in [1, 10, 20, 50, 100, 200, 500, 1000, 2000]]
# ----------------------------------------

class MetricsVideoSink(VideoStreamTrack):
    """
    Client B (接收端) 的自定义 Video Track。
    它不显示画面，而是记录每一帧到达的时间和 PTS。
    """
    def __init__(self, track):
        super().__init__()
        self.track = track
        self.received_data = [] # [{pts, p2p_arrival_time}, ...]

    async def recv(self):
        frame = await self.track.recv()
        # 记录 P2P 视频帧到达的时间 (作为基准时间)
        now = time.time()

        LOSS_RATE = 0.10 
        
        # ?模拟丢包
        if random.random() > LOSS_RATE:
            self.received_data.append({
                "pts": frame.pts,
                "p2p_arrival_time": now
            })
        # self.received_data.append({
        #     "pts": frame.pts,
        #     "p2p_arrival_time": now
        # })
        return frame

class DualClientBenchmark:
    def __init__(self):
        # 创建两个独立的 Socket.IO 客户端
        self.sio_a = socketio.AsyncClient() # Sender
        self.sio_b = socketio.AsyncClient() # Receiver
        
        self.results_df = pd.DataFrame()
        self.room_id = f"bench_room_{uuid.uuid4().hex[:8]}"
        self.peer_a_id = "client_A_sender"
        self.peer_b_id = "client_B_receiver"

        # WebRTC 连接对象
        self.pc_a_to_ai = None  # A -> AI Server
        self.pc_a_p2p = None    # A -> B (Sender Side)
        self.pc_b_p2p = None    # A -> B (Receiver Side)
        
        self.player = None
        self.metrics_sink = None # 用于 B 端记录数据
        
        self.ai_results = []     # B 端收到的 AI 结果
        self.is_running = False

    async def setup_signaling(self):
        """配置 Socket.IO 事件监听"""
        
        # --- Client A (Sender) Listeners ---
        @self.sio_a.on('answer', namespace='/ai_analysis')
        async def on_ai_answer(data):
            if self.pc_a_to_ai:
                desc = RTCSessionDescription(sdp=data['answer']['sdp'], type=data['answer']['type'])
                await self.pc_a_to_ai.setRemoteDescription(desc)

        @self.sio_a.on('candidate', namespace='/ai_analysis')
        async def on_ai_candidate(data):
            if self.pc_a_to_ai:
                c = data['candidate']
                candidate = RTCIceCandidate(
                    candidate=c['candidate'], sdpMid=c['sdpMid'], sdpMLineIndex=c['sdpMLineIndex']
                )
                await self.pc_a_to_ai.addIceCandidate(candidate)

        @self.sio_a.on('signal', namespace='/p2p')
        async def on_p2p_signal_a(data):
            # A 收到 B 的 P2P 信令 (通常是 Answer 或 Candidate)
            if data['type'] == 'answer':
                desc = RTCSessionDescription(sdp=data['answer']['sdp'], type=data['answer']['type'])
                await self.pc_a_p2p.setRemoteDescription(desc)
            elif data['type'] == 'ice-candidate':
                c = data['candidate']
                if c:
                    candidate = RTCIceCandidate(
                        candidate=c['candidate'], sdpMid=c['sdpMid'], sdpMLineIndex=c['sdpMLineIndex']
                    )
                    await self.pc_a_p2p.addIceCandidate(candidate)

        # --- Client B (Receiver) Listeners ---
        @self.sio_b.on('signal', namespace='/p2p')
        async def on_p2p_signal_b(data):
            # B 收到 A 的 P2P 信令 (通常是 Offer 或 Candidate)
            if data['type'] == 'offer':
                await self.handle_p2p_offer(data)
            elif data['type'] == 'ice-candidate':
                c = data['candidate']
                if c:
                    candidate = RTCIceCandidate(
                        candidate=c['candidate'], sdpMid=c['sdpMid'], sdpMLineIndex=c['sdpMLineIndex']
                    )
                    await self.pc_b_p2p.addIceCandidate(candidate)

        @self.sio_b.on('ai_result', namespace='/ai_analysis')
        async def on_ai_result(data):
            if not self.is_running: return
            # B 收到 AI 结果，记录到达时间
            self.ai_results.append({
                "pts": data.get('timestamp'), # 假设后端 ai_processor 传回了 PTS
                "ai_arrival_time": time.time(),
                "d_an": data.get('d_an', 0),
                "conf": data.get('mean_confidence', 0)
            })

    async def connect_sockets(self):
        await self.sio_a.connect(SERVER_URL, namespaces=['/p2p', '/ai_analysis'])
        await self.sio_b.connect(SERVER_URL, namespaces=['/p2p', '/ai_analysis'])
        
        # Join Rooms
        await self.sio_a.emit('join', {'roomId': self.room_id, 'peerId': self.peer_a_id}, namespace='/p2p')
        await self.sio_b.emit('join', {'roomId': self.room_id, 'peerId': self.peer_b_id}, namespace='/p2p')
        # A 也要加入 AI 房间
        await self.sio_a.emit('join', {'roomId': self.room_id}, namespace='/ai_analysis')
        # B 也要加入 AI 房间 (为了接收广播)
        await self.sio_b.emit('join', {'roomId': self.room_id}, namespace='/ai_analysis')
        
        await asyncio.sleep(1) # 等待加入完成

    async def start_ai_stream(self):
        """建立 A -> AI Server 的连接"""
        logger.info("📡 建立 A -> AI Server 连接...")
        self.pc_a_to_ai = RTCPeerConnection()
        
        # 添加 ICE 处理
        @self.pc_a_to_ai.on("icecandidate")
        async def on_icecandidate(candidate):
            if candidate:
                c_dict = {"candidate": candidate.to_sdp(), "sdpMid": candidate.sdpMid, "sdpMLineIndex": candidate.sdpMLineIndex}
                await self.sio_a.emit('candidate', {'candidate': c_dict}, namespace='/ai_analysis')

        # 添加视频轨道 (复用同一个 MediaPlayer 的 track)
        self.player_ai = MediaPlayer(VIDEO_FILE)
        self.pc_a_to_ai.addTrack(self.player_ai.video)

        offer = await self.pc_a_to_ai.createOffer()
        await self.pc_a_to_ai.setLocalDescription(offer)
        
        await self.sio_a.emit('offer', {
            'offer': {'sdp': self.pc_a_to_ai.localDescription.sdp, 'type': self.pc_a_to_ai.localDescription.type},
            'roomId': self.room_id,
            'peerId': self.peer_a_id
        }, namespace='/ai_analysis')

    async def start_p2p_stream(self):
        """建立 A -> B 的 P2P 连接"""
        logger.info("🔗 建立 A -> B P2P 连接...")
        self.pc_a_p2p = RTCPeerConnection()
        self.pc_b_p2p = RTCPeerConnection() # B 端的 PC 对象

        # A 端 ICE
        @self.pc_a_p2p.on("icecandidate")
        async def on_a_ice(candidate):
            if candidate:
                c_dict = {"candidate": candidate.to_sdp(), "sdpMid": candidate.sdpMid, "sdpMLineIndex": candidate.sdpMLineIndex}
                await self.sio_a.emit('signal', {'type': 'ice-candidate', 'candidate': c_dict, 'to': self.peer_b_id, 'roomId': self.room_id}, namespace='/p2p')

        # B 端 ICE
        @self.pc_b_p2p.on("icecandidate")
        async def on_b_ice(candidate):
            if candidate:
                c_dict = {"candidate": candidate.to_sdp(), "sdpMid": candidate.sdpMid, "sdpMLineIndex": candidate.sdpMLineIndex}
                await self.sio_b.emit('signal', {'type': 'ice-candidate', 'candidate': c_dict, 'to': self.peer_a_id, 'roomId': self.room_id}, namespace='/p2p')

        # B 端接收 Track
        @self.pc_b_p2p.on("track")
        def on_track(track):
            if track.kind == "video":
                # 使用自定义 Sink 记录时间
                self.metrics_sink = MetricsVideoSink(track)
                # 必须要把 track 消费掉，否则流不会动
                asyncio.create_task(self.consume_track(self.metrics_sink))

        # A 添加轨道
        self.player_p2p = MediaPlayer(VIDEO_FILE)
        self.pc_a_p2p.addTrack(self.player_p2p.video)

        # A 创建 Offer
        offer = await self.pc_a_p2p.createOffer()
        await self.pc_a_p2p.setLocalDescription(offer)
        
        # 通过 Socket 发送 Offer 给 B
        await self.sio_a.emit('signal', {
            'type': 'offer',
            'offer': {'sdp': self.pc_a_p2p.localDescription.sdp, 'type': self.pc_a_p2p.localDescription.type},
            'roomId': self.room_id,
            'to': self.peer_b_id
        }, namespace='/p2p')

    async def handle_p2p_offer(self, data):
        """B 处理 A 的 P2P Offer"""
        offer_desc = RTCSessionDescription(sdp=data['offer']['sdp'], type=data['offer']['type'])
        await self.pc_b_p2p.setRemoteDescription(offer_desc)
        
        answer = await self.pc_b_p2p.createAnswer()
        await self.pc_b_p2p.setLocalDescription(answer)
        
        await self.sio_b.emit('signal', {
            'type': 'answer',
            'answer': {'sdp': self.pc_b_p2p.localDescription.sdp, 'type': self.pc_b_p2p.localDescription.type},
            'roomId': self.room_id,
            'to': self.peer_a_id
        }, namespace='/p2p')

    async def consume_track(self, track):
        """B 端消费 P2P 视频流"""
        while True:
            try:
                await track.recv()
            except Exception:
                break

    async def run_single_experiment(self, config, duration=30):
        logger.info(f"1 开始实验: {config['desc']}")
        
        # 1. 更新 AI 配置
        await self.sio_a.emit('update_config', config, namespace='/ai_analysis')
        
        # 2. 启动流
        self.is_running = True
        self.ai_results = []
        if self.metrics_sink: self.metrics_sink.received_data = []
        
        # *同时启动，不要人为 sleep
        logger.info("2 同时启动 P2P 和 AI 推流...")
        await asyncio.gather(
            self.start_p2p_stream(),
            self.start_ai_stream()
        )

        # 3. 智能等待：等待 AI 产出第一个结果 (剔除冷启动时间)
        logger.info("3 等待 AI 引擎预热 & 首帧产出...")
        start_wait = time.time()
        while not self.ai_results:
            await asyncio.sleep(0.1)
            if time.time() - start_wait > 10:
                logger.error(" AI 启动超时 (10s)")
                break

        logger.info(f"4 AI 已出数据 (耗时 {time.time()-start_wait:.1f}s)，开始正式计时...")
        
        # 3. 运行
        logger.info(f"5 收集数据中 ({duration}s)...")
        await asyncio.sleep(duration)
        
        # 4. 停止并分析
        self.is_running = False
        await self.cleanup_connections()
        self.analyze_data(config)

    async def cleanup_connections(self):
        if self.pc_a_to_ai: await self.pc_a_to_ai.close()
        if self.pc_a_p2p: await self.pc_a_p2p.close()
        if self.pc_b_p2p: await self.pc_b_p2p.close()
        self.pc_a_to_ai = None
        self.pc_a_p2p = None
        self.pc_b_p2p = None

    def analyze_data(self, config):
        if not self.metrics_sink or not self.metrics_sink.received_data:
            logger.warning("B端未收到 P2P 数据，检查连接")
            return
        if not self.ai_results:
            logger.warning("B端未收到 AI 数据，检查 AI 服务")
            return

        df_p2p = pd.DataFrame(self.metrics_sink.received_data)
        df_ai = pd.DataFrame(self.ai_results)
        
        # 确保 PTS 类型一致
        df_p2p['pts'] = df_p2p['pts'].astype(int)
        df_ai['pts'] = df_ai['pts'].astype(int)

        # 排序
        df_p2p = df_p2p.sort_values('pts')
        df_ai = df_ai.sort_values('pts')

        df_p2p_clean = df_p2p.rename(columns={'pts': 'pts_video', 'p2p_arrival_time': 't_video'})
        df_ai_clean = df_ai.rename(columns={'pts': 'pts_ai', 'ai_arrival_time': 't_ai'})

        tol_ticks = config['tolerance_ticks']

        merged = pd.merge_asof(
            df_ai_clean,
            df_p2p_clean,
            left_on='pts_ai',
            right_on='pts_video',
            direction='nearest',
            tolerance=tol_ticks
        )

        valid_matches = merged.dropna(subset=['t_video']).copy()

        if not valid_matches.empty:
            valid_matches['visual_drift_ms'] = (valid_matches['t_ai'] - valid_matches['t_video']) * 1000
            valid_matches['pts_diff_abs'] = (valid_matches['pts_ai'] - valid_matches['pts_video']).abs()
            exact_count = (valid_matches['pts_diff_abs'] == 0).sum()
            exact_ratio = exact_count / len(valid_matches) * 100

            stats = {
                'desc': config['desc'],
                'chunk_size': config['chunk_size'],
                'stride': config['stride'],
                'tolerance_ms': round(tol_ticks / 90.0, 1),
                'match_count': len(valid_matches),
                'exact_match_ratio': round(exact_ratio, 1),
                'avg_drift_ms': round(valid_matches['visual_drift_ms'].mean(), 2),
                'std_drift_ms': round(valid_matches['visual_drift_ms'].std(), 2),
                'server_proc_ms': round(valid_matches['d_an'].mean(), 2)
            }
            self.results_df = pd.concat([self.results_df, pd.DataFrame([stats])], ignore_index=True)
            logger.info(f"6 结果: Tol={stats['tolerance_ms']}ms | Matches={stats['match_count']} | Drift={stats['avg_drift_ms']}ms")
        else:
            logger.warning(f"Tol={tol_ticks/90}ms 无匹配数据")


        # ?你现在用 pd.merge_asof(..., direction='nearest')。
        # ?这会在时间轴上给每条 AI 记录挑最近的 P2P 帧，只要距离小于 tolerance。
        # ?你的 PTS 是完全同步的（相同 frame.pts），所以距离就是 0 ticks；只要容差 ≥0，全都匹配。
        # ?改变容差不会影响结果，除非某个 AI 帧找不到任何 P2P 帧或存在两个候选距离一样近。

        
    async def run_all(self):
        await self.setup_signaling()
        await self.connect_sockets()
        
        total_runs = len(EXPERIMENTS) * len(tolerance_space)
        current_run = 0

        # [核心修改] 双层循环结构
        for exp in EXPERIMENTS:
            for tol_ticks in tolerance_space:
                current_run += 1
                
                # 1. 构造本次运行的完整配置
                # 必须 copy，否则会污染原始 EXPERIMENTS 列表
                run_config = exp.copy()
                
                # 关键点：在这里把 tolerance_ticks 注入进去！
                # 这样 run_single_experiment -> analyze_data 才能读到它
                run_config['tolerance_ticks'] = tol_ticks
                
                tol_ms = round(tol_ticks / 90.0, 1)
                logger.info(f"[Run {current_run}/{total_runs}] {run_config['desc']} (Tol: {tol_ms}ms)")
                
                # 2. 运行单次实验 (它会调用 analyze_data)
                await self.run_single_experiment(run_config, duration=15)
                
                # 3. 冷却一下，防止端口未释放
                await asyncio.sleep(2)

        # 保存最终大表
        self.results_df.to_csv("full_physical_experiment_results.csv", index=False)
        logger.info(" 72次实验全部完成。结果保存至 full_physical_experiment_results.csv")
        
        await self.sio_a.disconnect()
        await self.sio_b.disconnect()

if __name__ == "__main__":
    bench = DualClientBenchmark()
    asyncio.run(bench.run_all())