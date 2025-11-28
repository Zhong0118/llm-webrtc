# benchmark_runner.py
import asyncio
import time
import uuid
import logging
import os
import av
import pandas as pd
import socketio
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack

# ================= 配置区域 =================
VIDEO_FILE = "part1.mp4" 
SERVER_URL = "https://localhost:33335" # 

# [核心] 定义四组聚合窗口大小
BATCH_SIZES = [1, 5, 10, 20]

# 测试配置矩阵 (每个BatchSize都会跑一遍这组配置)
CONFIGS = [
    {"res": (640, 480), "fps": 10, "duration": 20},
    {"res": (640, 480), "fps": 15, "duration": 20},
    {"res": (640, 480), "fps": 20, "duration": 20},
    {"res": (640, 480), "fps": 30, "duration": 20},
    {"res": (1280, 720), "fps": 10, "duration": 20},
    {"res": (1280, 720), "fps": 15, "duration": 20},
    {"res": (1280, 720), "fps": 20, "duration": 20},
    {"res": (1280, 720), "fps": 30, "duration": 20},
]

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("Benchmark")
logging.getLogger("aioice.ice").setLevel(logging.ERROR)

class FileVideoTrack(VideoStreamTrack):
    def __init__(self, file_path, target_fps):
        super().__init__()
        self.container = av.open(file_path)
        self.stream = self.container.streams.video[0]
        self.target_fps = target_fps
        self.interval = 1 / target_fps
        self.iter = self.container.decode(self.stream)
        self.last_time = 0

    # 限速读取本地视频，循环播放
    async def recv(self):  
        now = time.time()
        wait = self.last_time + self.interval - now
        if wait > 0:
            await asyncio.sleep(wait)
        self.last_time = time.time()
        try:
            frame = next(self.iter)
        except StopIteration:
            self.container.seek(0)
            self.iter = self.container.decode(self.stream)
            frame = next(self.iter)
        pts, time_base = await self.next_timestamp()
        frame.pts = pts
        frame.time_base = time_base
        return frame

class BenchmarkClient:
    def __init__(self, config, batch_size):
        self.config = config
        self.batch_size = batch_size # [新增] 接收当前批次大小
        self.sio = socketio.AsyncClient(ssl_verify=False) # 忽略SSL验证方便本地测试
        self.pc = RTCPeerConnection()
        self.room_id = f"bench_{uuid.uuid4().hex[:4]}"
        self.peer_id = f"client_{uuid.uuid4().hex[:4]}"
        self.results = []
        self.running = False
        self.batch_buffer = [] 

# 连接 Socket.IO，发 WebRTC offer，运行指定秒数，期间由事件回调持续攒数据。
    async def run(self):
        logger.info(f"   -> Testing: {self.config['res']} @ {self.config['fps']} FPS")
        self._bind_socket_events()
        try:
            await self.sio.connect(SERVER_URL, namespaces=['/p2p', '/ai_analysis'])
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return []

        self.running = True
        await self.sio.emit('join', {'roomId': self.room_id, 'peerId': self.peer_id}, namespace='/ai_analysis')
        
        track = FileVideoTrack(VIDEO_FILE, self.config['fps'])
        self.pc.addTrack(track)
        
        offer = await self.pc.createOffer()
        await self.pc.setLocalDescription(offer)
        
        await self.sio.emit('offer', {
            'offer': {'sdp': offer.sdp, 'type': offer.type},
            'roomId': self.room_id,
            'peerId': self.peer_id
        }, namespace='/ai_analysis')

        start_time = time.time()
        while time.time() - start_time < self.config['duration']:
            if not self.running: break
            await asyncio.sleep(1)
            
        await self.cleanup()
        return self.results


    def _bind_socket_events(self):
        # 这是收到服务器 AI 结果的回调。
        @self.sio.on('ai_result', namespace='/ai_analysis')
        async def on_ai_result(data):
            if not self.running: return
            
            recv_time = time.time()
            send_time_ms = data.get('send_time')
            if send_time_ms is None:
                # 兼容旧字段（RTP 时间戳）
                send_time_ms = data.get('timestamp', recv_time * 1000)
            # 计算端到端延迟（毫秒）
            e2e_delay = (recv_time * 1000) - send_time_ms
            
            raw_record = {
                "server_fps": data.get('fps', 0),
                "inference_time": data.get('inference_time', 0),
                "process_time": data.get('process_time', 0),
                "e2e_delay": max(0, e2e_delay),
                "object_count": len(data.get('objects', [])),
                "frame_id": data['frame_id']
            }
            
            self.batch_buffer.append(raw_record)
            # 缓冲：它不直接写入结果，而是把数据塞进 batch_buffer。
            # [核心] 根据传入的 batch_size 进行聚合
            if len(self.batch_buffer) >= self.batch_size:
                self._flush_buffer()

        @self.sio.on('answer', namespace='/ai_analysis')
        async def on_answer(data):
            desc = RTCSessionDescription(sdp=data['answer']['sdp'], type=data['answer']['type'])
            await self.pc.setRemoteDescription(desc)

# 目的：消除网络瞬间抖动对整体趋势的影响，输出一条代表性的数据。它把缓冲区里的 10 帧数据拿出来，求平均值 (mean)。
    def _flush_buffer(self):
        if not self.batch_buffer: return
        count = len(self.batch_buffer)
        
        # server_fps: 服务器实际处理能力（看是否跑满）。
        # inference_time: YOLO 纯推理耗时（显卡能力）。
        # process_time: 解码+推理+编码总耗时（后端效率）。
        # e2e_delay: 端到端延迟（用户体验）。
        avg_record = {
            "resolution": f"{self.config['res'][0]}x{self.config['res'][1]}",
            "fps": self.config['fps'],
            "batch_size_group": self.batch_size, # 标记属于哪一组
            "end_frame_id": self.batch_buffer[-1]['frame_id'],
            "server_fps": round(sum(d['server_fps'] for d in self.batch_buffer) / count, 2),
            "inference_time": round(sum(d['inference_time'] for d in self.batch_buffer) / count, 2),
            "process_time": round(sum(d['process_time'] for d in self.batch_buffer) / count, 2),
            "e2e_delay": round(sum(d['e2e_delay'] for d in self.batch_buffer) / count, 2),
            "object_count": round(sum(d['object_count'] for d in self.batch_buffer) / count, 2)
        }
        self.results.append(avg_record)
        self.batch_buffer = []

    async def cleanup(self):
        self.running = False
        if self.batch_buffer: self._flush_buffer()
        if self.pc: await self.pc.close()
        if self.sio.connected: await self.sio.disconnect()

async def main():
    if not os.path.exists(VIDEO_FILE):
        logger.error(f"Video file not found: {VIDEO_FILE}")
        return

    # [核心循环] 遍历 4 组 batch_size
    for batch_size in BATCH_SIZES:
        logger.info(f"\n\n========== 开始测试 Batch Size: {batch_size} ==========")
        current_batch_data = []
        
        for conf in CONFIGS:
            # 将 batch_size 传入 Client
            client = BenchmarkClient(conf, batch_size)
            data = await client.run()
            current_batch_data.extend(data)
            await asyncio.sleep(1) # 休息一下，避免端口冲突
        
        # 每跑完一组，存一个 CSV
        filename = f"benchmark_log_batch_{batch_size}.csv"
        if current_batch_data:
            df = pd.DataFrame(current_batch_data)
            df.to_csv(filename, index=False)
            logger.info(f"✅ Saved: {filename} (Rows: {len(df)})")
        else:
            logger.warning(f"❌ No data collected for batch {batch_size}")

    logger.info("\n🎉 所有测试组运行完毕！")

if __name__ == "__main__":
    asyncio.run(main())