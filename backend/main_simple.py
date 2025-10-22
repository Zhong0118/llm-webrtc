from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import json
import cv2
import numpy as np
import uvicorn
from av import VideoFrame
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack, RTCIceCandidate
from aioice import Candidate
from aiortc.contrib.media import MediaRelay

app = FastAPI()

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 存储活跃连接
active_connections = {}
# 房间映射：roomId -> { peerId -> websocket }
rooms = {}

# 媒体中继（支持多客户端订阅同一视频源）
relay = MediaRelay()

# 视频源 - 使用摄像头
class CameraStreamTrack(VideoStreamTrack):
    kind = "video"

    def __init__(self):
        super().__init__()
        self.cap = cv2.VideoCapture(0)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        fps = self.cap.get(cv2.CAP_PROP_FPS)
        self._fps = fps if fps and fps > 0 else 30

    async def recv(self):
        # 控制帧率
        await asyncio.sleep(1 / self._fps)
        ret, frame = self.cap.read()
        if not ret:
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
        # 转换为RGB格式
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        # 创建视频帧并设置时间戳
        video_frame = VideoFrame.from_ndarray(frame, format="rgb24")
        video_frame.pts, video_frame.time_base = await self.next_timestamp()
        return video_frame

    def stop(self):
        if self.cap:
            self.cap.release()

# 创建单一摄像头源，并通过 relay 提供给各连接
camera_track = CameraStreamTrack()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connection_id = id(websocket)

    pc = RTCPeerConnection()

    # 为每个连接订阅同一视频源（支持多客户端观看）
    video_track = relay.subscribe(camera_track)
    pc.addTrack(video_track)

    active_connections[connection_id] = {
        "websocket": websocket,
        "peer_connection": pc,
        "video_track": video_track
    }

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            if message.get("type") == "offer":
                offer = RTCSessionDescription(sdp=message["offer"]["sdp"], type=message["offer"]["type"])
                await pc.setRemoteDescription(offer)

                answer = await pc.createAnswer()
                await pc.setLocalDescription(answer)

                await websocket.send_json({
                    "type": "answer",
                    "answer": {
                        "sdp": pc.localDescription.sdp,
                        "type": pc.localDescription.type
                    }
                })

            elif message.get("type") == "ice-candidate":
                candidate = message.get("candidate")
                # 处理 ICE 候选：支持 null（结束候选）与字典对象
                if candidate is None:
                    await pc.addIceCandidate(None)
                elif isinstance(candidate, dict):
                    sdp_mid = candidate.get("sdpMid")
                    sdp_mline_index = candidate.get("sdpMLineIndex")
                    cand_str = candidate.get("candidate")
                    if not cand_str:
                        print("ICE候选缺少 candidate 字段，忽略")
                    else:
                        # 去掉 'candidate:' 前缀
                        cand_sdp = cand_str[10:] if cand_str.startswith("candidate:") else cand_str
                        try:
                            aioice_cand = Candidate.from_sdp(cand_sdp)
                            ice = RTCIceCandidate(
                                component=aioice_cand.component,
                                foundation=aioice_cand.foundation,
                                ip=aioice_cand.host,
                                port=aioice_cand.port,
                                priority=aioice_cand.priority,
                                protocol=aioice_cand.transport,
                                type=aioice_cand.type,
                                relatedAddress=aioice_cand.related_address,
                                relatedPort=aioice_cand.related_port,
                                tcpType=aioice_cand.tcptype,
                                sdpMid=sdp_mid,
                                sdpMLineIndex=sdp_mline_index,
                            )
                            await pc.addIceCandidate(ice)
                        except Exception as parse_err:
                            print(f"解析 ICE 候选失败: {parse_err}")
                else:
                    # 兼容异常格式：直接忽略或打印日志
                    print(f"ICE候选格式不支持: {candidate}")


    except WebSocketDisconnect:
        print(f"WebSocket连接断开: {connection_id}")
    except Exception as e:
        print(f"错误: {e}")
    finally:
        if connection_id in active_connections:
            # 关闭订阅轨道，不影响主摄像头源
            active_connections[connection_id]["video_track"].stop()
            await active_connections[connection_id]["peer_connection"].close()
            del active_connections[connection_id]

@app.websocket("/ws-room")
async def ws_room(websocket: WebSocket):
    await websocket.accept()
    connection_id = id(websocket)
    joined_room = None
    peer_id = None
    try:
        while True:
            raw = await websocket.receive_text()
            message = json.loads(raw)
            msg_type = message.get("type")

            if msg_type == "join":
                room_id = str(message.get("roomId") or "")
                peer_id = str(message.get("peerId") or "")
                if not room_id or not peer_id:
                    await websocket.send_json({"type": "error", "message": "roomId/peerId required"})
                    continue
                rooms.setdefault(room_id, {})
                rooms[room_id][peer_id] = websocket
                joined_room = room_id
                await websocket.send_json({"type": "joined", "roomId": room_id, "peerId": peer_id})

            elif msg_type in ("offer", "answer", "ice-candidate"):
                room_id = str(message.get("roomId") or "")
                to_peer = str(message.get("to") or "")
                if not room_id or not to_peer:
                    await websocket.send_json({"type": "error", "message": "roomId/to required"})
                    continue
                target_ws = rooms.get(room_id, {}).get(to_peer)
                if target_ws:
                    # 透明转发
                    await target_ws.send_text(raw)
                else:
                    await websocket.send_json({"type": "error", "message": "target not found"})
            else:
                await websocket.send_json({"type": "error", "message": f"unknown type: {msg_type}"})

    except WebSocketDisconnect:
        print(f"Room WebSocket连接断开: {connection_id}")
    except Exception as e:
        print(f"Room错误: {e}")
    finally:
        # 清理房间内记录
        if joined_room and peer_id:
            room = rooms.get(joined_room)
            if room and room.get(peer_id) == websocket:
                del room[peer_id]
            if room and len(room) == 0:
                del rooms[joined_room]

@app.get("/")
async def root():
    return {"message": "WebRTC简化版本API"}

if __name__ == "__main__":
    import uvicorn
    import os

    # --- 确认这部分配置都在 ---
    base_dir = os.path.dirname(os.path.abspath(__file__))
    cert_dir = os.path.abspath(os.path.join(base_dir, "..", "frontend", "certs"))
    ssl_keyfile = os.path.join(cert_dir, "localhost+3-key.pem")
    ssl_certfile = os.path.join(cert_dir, "localhost+3.pem")

    # 检查文件 (省略了打印错误，但逻辑应保留)
    if not os.path.exists(ssl_keyfile) or not os.path.exists(ssl_certfile):
        print("错误: SSL 证书文件未找到!")
        exit(1)

    print(f"使用SSL证书: {ssl_certfile}")
    print(f"使用SSL密钥: {ssl_keyfile}")
    print("启动HTTPS服务器 (带重载) 在 https://0.0.0.0:8000")

    uvicorn.run(
        app,                    # 直接传递 app 对象
        host="0.0.0.0",
        port=8000,
        reload=True,            # 启用重载
        ssl_keyfile=ssl_keyfile,
        ssl_certfile=ssl_certfile
    )