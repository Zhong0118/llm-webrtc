# benchmark_research.py
import asyncio
import time
import uuid
import logging
import pandas as pd
import socketio
import av
from aiortc import RTCPeerConnection, VideoStreamTrack, RTCSessionDescription, RTCIceCandidate

# 实验配置矩阵：探究 Chunk Size 对延迟和置信度的影响
# 始终保持最新的 20 帧作为视野，但是每隔 5 帧才‘睁眼’看一次。”
EXPERIMENTS = [
    {"chunk_size": 1,  "stride": 1, "desc": "1 Real-time (Baseline) 1"},
    {"chunk_size": 5,  "stride": 2, "desc": "5 Short Window 2"},
    {"chunk_size": 10, "stride": 1, "desc": "10 Medium Window 1"},
    {"chunk_size": 10, "stride": 2, "desc": "10 Medium Window 2"},
    {"chunk_size": 10, "stride": 5, "desc": "10 Medium Window 5"},
    {"chunk_size": 20, "stride": 1, "desc": "20 Long Window (Sign Language) 1"},
    {"chunk_size": 20, "stride": 2, "desc": "20 Long Window (Sign Language) 2"},
    {"chunk_size": 20, "stride": 5, "desc": "20 Long Window (Sign Language) 5"},
]

VIDEO_FILE = "part1.mp4"
SERVER_URL = "https://localhost:33335"

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("ResearchBench")
logging.getLogger("aioice.ice").setLevel(logging.ERROR)

class FileVideoTrack(VideoStreamTrack):
    def __init__(self, file_path):
        super().__init__()
        self.container = av.open(file_path)
        self.stream = self.container.streams.video[0]
        self.iter = self.container.decode(self.stream)
        self.last_time = 0
        self.interval = 1/20 

    async def recv(self):
        now = time.time()
        # 强制控制发送速率，模拟真实的摄像头 FPS。
        wait = self.last_time + self.interval - now
        if wait > 0: await asyncio.sleep(wait)
        self.last_time = time.time()
        
        try: frame = next(self.iter)
        except StopIteration: 
            self.container.seek(0)
            self.iter = self.container.decode(self.stream)
            frame = next(self.iter)
            
        pts, time_base = await self.next_timestamp()
        # 写入播放时间戳，保证视频流的时间基准正确。
        frame.pts = pts
        frame.time_base = time_base
        return frame

class ResearchExperiment:
    def __init__(self):
        self.sio = socketio.AsyncClient()
        self.pc = RTCPeerConnection()
        self.data_log = []
        self.running = False

    async def run_suite(self):
        logger.info("🚀 开始科研自动化测试...")
        
        # 1. 连接服务器
        await self.sio.connect(SERVER_URL, namespaces=['/ai_analysis'])
        
        # 2. 建立 WebRTC 通道 (只建一次，中间动态改参)
        room_id = f"exp_{uuid.uuid4().hex[:4]}"
        peer_id = "researcher_bot"
        
        await self.sio.emit('join', {'roomId': room_id, 'peerId': peer_id}, namespace='/ai_analysis')
        self.pc.addTrack(FileVideoTrack(VIDEO_FILE))
        offer = await self.pc.createOffer()
        await self.pc.setLocalDescription(offer)
        await self.sio.emit('offer', {'offer': {'sdp': offer.sdp, 'type': offer.type}, 'roomId': room_id, 'peerId': peer_id}, namespace='/ai_analysis')
        
        self._bind_events()
        self.running = True

        # 3. 循环执行实验矩阵
        for exp in EXPERIMENTS:
            logger.info(f"\n🧪 正在执行实验: {exp['desc']} (Chunk={exp['chunk_size']})...")
            
            # A. 下发配置给服务器 (动态调整)
            await self.sio.emit('update_config', exp, namespace='/ai_analysis')
            
            # B. 采集数据 10秒
            self.current_exp_config = exp
            start_time = time.time()
            while time.time() - start_time < 10:
                await asyncio.sleep(0.1)
            
            logger.info(f"✅ 实验完成。")

        # 4. 保存与清理
        await self.cleanup()
        self.save_report()

    def _bind_events(self):
        @self.sio.on('ai_result', namespace='/ai_analysis')
        async def on_result(data):
            if not self.running or not hasattr(self, 'current_exp_config'): return
            
            recv_time = time.time()
            send_time_ms = data.get('send_time')
            if send_time_ms is None:
                send_time_ms = data.get('timestamp', recv_time * 1000)
            # 计算 E2E 延迟（毫秒）
            e2e_delay = (recv_time * 1000) - send_time_ms
            
            # 记录一条完整的科研数据
            record = {
                "experiment": self.current_exp_config['desc'],
                "chunk_size": self.current_exp_config['chunk_size'],
                "stride": self.current_exp_config['stride'],
                "frame_id": data['frame_id'],
                "d_an": data['d_an'],                 # 核心：服务端处理+堆积延迟
                "inference_time": data['inference_time'], # 核心：纯算力耗时
                "e2e_delay": e2e_delay,               # 核心：用户感知延迟
                "mean_confidence": data['mean_confidence'] # 核心：准确度指标
            }
            self.data_log.append(record)
        @self.sio.on('answer', namespace='/ai_analysis')
        async def on_answer(data):
            answer = data['answer']
            desc = RTCSessionDescription(sdp=answer['sdp'], type=answer['type'])
            await self.pc.setRemoteDescription(desc)

        @self.sio.on('candidate', namespace='/ai_analysis')
        async def on_candidate(data):
            cand = data.get('candidate')
            if not cand: 
                return
            await self.pc.addIceCandidate(RTCIceCandidate(
                sdpMid=cand.get('sdpMid'),
                sdpMLineIndex=cand.get('sdpMLineIndex'),
                candidate=cand['candidate'],
            ))

    async def cleanup(self):
        self.running = False
        await self.pc.close()
        await self.sio.disconnect()

    def save_report(self):
        df = pd.DataFrame(self.data_log)
        df.to_csv('research_results.csv', index=False)
        print(f"\n📊 数据已保存至 research_results.csv (共 {len(df)} 条)")

if __name__ == "__main__":
    exp = ResearchExperiment()
    asyncio.run(exp.run_suite())