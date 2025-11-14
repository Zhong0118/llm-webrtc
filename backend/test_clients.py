import asyncio
import socketio
import logging
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from aiortc.mediastreams import MediaStreamError
import time

# --- 配置 ---
SERVER_URL = "https://localhost:33335" # 你的服务器地址
NAMESPACE = "/server_push"
NUM_CLIENTS = 3 # 你想模拟的客户端数量

# 配置日志
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
log = logging.getLogger("TestClient")

# 一个虚拟的视频轨道，用于“接收”视频
class SimpleFrameReceiver(VideoStreamTrack):
    def __init__(self, client_id):
        super().__init__()
        self.kind = "video"
        self.client_id = client_id
        self.frame_count = 0
        self.start_time = None

    async def recv(self):
        # 这个方法被 aiortc 调用时，意味着我们收到了一个帧
        pts, time_base = await self.next_timestamp()
        
        if self.start_time is None:
            self.start_time = time.time()

        self.frame_count += 1
        
        if self.frame_count % 30 == 0: # 每 30 帧打印一次
            elapsed = time.time() - self.start_time
            fps = self.frame_count / elapsed if elapsed > 0 else 0
            log.info(f"[Client {self.client_id}] Recv Frame: {self.frame_count} | FPS: {fps:.2f}")

        # 在实际的 aiortc 接收器中，我们不需要返回帧，
        # 我们只是在这里处理事件。但我们必须等待下一帧。
        # 为防止此函数立即返回并被再次调用，我们等待一个非常短的时间。
        # 在一个真正的接收器中，我们依赖于底层的 RTP 包
        
        # 补救：为了让 recv() 真正“等待”下一帧，我们模拟等待
        # (在 aiortc 的 addTrack(recvonly) 中，我们实际上不需要实现 recv)
        # 
        # 修正：我们不需要实现 recv() 来接收
        # 真正的魔法发生在 on("track") 事件
        pass

async def run_client(client_id):
    """模拟一个单独的客户端连接、offer 并接收流"""
    
    sio = socketio.AsyncClient(ssl_verify=False, logger=False, engineio_logger=False)
    pc = RTCPeerConnection()
    
    client_log = logging.getLogger(f"Client {client_id}")
    client_log.setLevel(logging.INFO)
    
    received_track_event = asyncio.Event()

    @pc.on("track")
    def on_track(track):
        client_log.info(f"成功接收到视频轨道 (Kind: {track.kind})")
        # 在这里我们可以附加到一个虚拟播放器，但对于测试，我们只设置一个事件
        received_track_event.set()

    @pc.on("connectionstatechange")
    def on_connectionstatechange():
        client_log.info(f"PC State: {pc.connectionState}")
        if pc.connectionState == "failed" or pc.connectionState == "closed":
            client_log.warning("PC 连接已关闭或失败。")
            
    async def send_offer():
        try:
            # 客户端设置为只接收
            pc.addTransceiver("video", direction="recvonly")
            
            offer = await pc.createOffer()
            await pc.setLocalDescription(offer)
            
            client_log.info("已创建 Offer, 正在发送...")
            await sio.emit("offer", {
                "offer": {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}
            }, namespace=NAMESPACE)
            
        except Exception as e:
            client_log.error(f"发送 Offer 失败: {e}", exc_info=True)

    # --- Socket.IO 事件处理器 ---
    @sio.event(namespace=NAMESPACE)
    async def connect():
        client_log.info("Socket.IO 已连接。")
        # 连接后立即发送 Offer
        asyncio.create_task(send_offer())

    @sio.event(namespace=NAMESPACE)
    async def disconnect():
        client_log.info("Socket.IO 已断开。")

    @sio.event(namespace=NAMESPACE)
    async def error(data):
        client_log.error(f"服务器错误: {data.get('message')}")
        await sio.disconnect() # 收到错误就断开

    @sio.event(namespace=NAMESPACE)
    async def answer(data):
        client_log.info("收到 Answer。")
        try:
            answer_desc = RTCSessionDescription(sdp=data["answer"]["sdp"], type=data["answer"]["type"])
            await pc.setRemoteDescription(answer_desc)
        except Exception as e:
            client_log.error(f"设置 RemoteDescription (Answer) 失败: {e}", exc_info=True)

    @sio.event(namespace=NAMESPACE)
    async def candidate(data):
        client_log.debug(f"收到 Candidate: {data.get('candidate')}")
        try:
            if data.get("candidate"):
                cand_data = data
                ice = Candidate.from_sdp(cand_data['candidate'])
                ice.sdpMid = cand_data.get('sdpMid')
                ice.sdpMLineIndex = cand_data.get('sdpMLineIndex')
                await pc.addIceCandidate(ice)
            else:
                await pc.addIceCandidate(None)
        except Exception as e:
            client_log.error(f"添加 ICE Candidate 失败: {e}", exc_info=True)

    # --- 启动客户端 ---
    try:
        await sio.connect(SERVER_URL, namespaces=[NAMESPACE], transports=['websocket'])
        
        # 等待，直到我们收到轨道或超时
        await asyncio.wait_for(received_track_event.wait(), timeout=15.0)
        
        client_log.info("轨道已接收！测试成功。将保持连接 30 秒...")
        await asyncio.sleep(30)
        
    except asyncio.TimeoutError:
        client_log.error("测试失败：超时未接收到视频轨道。")
    except Exception as e:
        client_log.error(f"客户端运行时出错: {e}", exc_info=True)
    finally:
        client_log.warning("正在关闭连接...")
        await pc.close()
        await sio.disconnect()
        client_log.info("已关闭。")

async def main():
    log.info(f"--- 启动 {NUM_CLIENTS} 个并发客户端测试 ---")
    tasks = [run_client(i+1) for i in range(NUM_CLIENTS)]
    await asyncio.gather(*tasks)
    log.info("--- 所有客户端测试完毕 ---")

if __name__ == "__main__":
    asyncio.run(main())