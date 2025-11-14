# main_simple.py (FINAL VERSION with Camera Management)
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import asyncio
import json
import cv2
import numpy as np
import uvicorn
import logging
import time
from av import VideoFrame
from aiortc import (
    RTCPeerConnection,
    RTCSessionDescription,
    VideoStreamTrack,
    RTCIceCandidate,
)
from aioice import Candidate
from aiortc.mediastreams import MediaStreamError
from aiortc.contrib.media import MediaRelay, MediaPlayer
from pydantic import BaseModel
from typing import Optional, Dict, Any
import socketio
import numpy as np

import threading
import queue

# 配置日志
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logging.getLogger("aiortc").setLevel(logging.WARNING)
logging.getLogger("uvicorn").setLevel(logging.INFO)
logging.getLogger("socketio").setLevel(logging.INFO)
logger = logging.getLogger("WebRTCApp")
logger.setLevel(logging.DEBUG)

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
fastapi_app = FastAPI()
app = socketio.ASGIApp(socketio_server=sio, other_asgi_app=fastapi_app)

# 配置CORS
fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

try:
    from streaming.streamer import RTSPStreamer
    from streaming.config import DEFAULT_CONFIG

    VLC_AVAILABLE = True
    STREAMER_NAMESPACE = "/streamer"
    vlc_streamer = RTSPStreamer(sio_server=sio, namespace=STREAMER_NAMESPACE)
    logging.info("🎥 VLC/FFmpeg Streamer 实例创建成功")
except ImportError as e:
    VLC_AVAILABLE = False
    vlc_streamer = None
    logging.warning(f"⚠️ VLC/FFmpeg Streamer 加载失败: {e}")


# 启用Socket.IO
async def enable_streamer_socketio():
    if vlc_streamer:
        vlc_streamer.enable_socketio()
        logging.info("🔌 VLC/FFmpeg Streamer Socket.IO 已启用")


# Pydantic 模型定义
class RTSPControlRequest(BaseModel):
    action: str
    resolution: Optional[str] = None
    fps: Optional[int] = None
    crf: Optional[int] = None
    preset: Optional[str] = None


# --- [新修复 2]: 创建摄像头管理器和锁 ---
camera_lock = threading.Lock()  # 一个线程锁来保护下面的变量
camera_in_use_by = None  # "streamer" 或 "server_push_consuming_streamer"
relay = MediaRelay()  # WebRTC 媒体中继 (保持不变)
rtsp_player = None

# P2P Socket.IO 逻辑 (保持不变, 它用的是前端摄像头, 不冲突)
client_peer_map: Dict[str, str] = {}
peer_client_map: Dict[str, str] = {}
client_room_map: Dict[str, str] = {}
P2P_NAMESPACE = "/p2p"


# P2P Connect
@sio.event(namespace=P2P_NAMESPACE)
async def connect(sid, environ):
    logger.info(f"[P2P] Client connected: {sid}")


@sio.event(namespace=P2P_NAMESPACE)
async def disconnect(sid):
    logger.info(f"[P2P] Client disconnected: {sid}")
    await leave(sid, {})


@sio.event(namespace=P2P_NAMESPACE)
async def join(sid, data: Dict[str, Any]):
    room_id = data.get("roomId")
    peer_id = data.get("peerId")
    if not room_id or not peer_id:
        await sio.emit(
            "join_error",
            {"message": "roomId and peerId are required"},
            room=sid,
            namespace=P2P_NAMESPACE,
        )
        return
    client_peer_map[sid] = peer_id
    peer_client_map[peer_id] = sid
    client_room_map[sid] = room_id
    await sio.enter_room(sid, room_id, namespace=P2P_NAMESPACE)
    logger.info(f"[P2P] Client {sid} (Peer: {peer_id}) joined room: {room_id}")
    await sio.emit(
        "joined",
        {"roomId": room_id, "peerId": peer_id},
        room=sid,
        namespace=P2P_NAMESPACE,
    )
    participants_set = sio.manager.rooms.get(room_id, {}).get(
        P2P_NAMESPACE, set()
    )  # 修正: 从命名空间获取
    other_sids = [p_sid for p_sid in participants_set if p_sid != sid]
    if len(other_sids) >= 1:
        other_target_sid = other_sids[0]
        other_peer_id = client_peer_map.get(other_target_sid, "unknown")
        await sio.emit(
            "peer_joined", {"peerId": other_peer_id}, room=sid, namespace=P2P_NAMESPACE
        )
        await sio.emit(
            "peer_joined",
            {"peerId": peer_id},
            room=other_target_sid,
            namespace=P2P_NAMESPACE,
        )


@sio.event(namespace=P2P_NAMESPACE)
async def signal(sid, data: Dict[str, Any]):
    room_id = data.get("roomId")
    to_peer_id = data.get("to")
    signal_type = data.get("type")
    if not room_id or not to_peer_id or not signal_type:
        await sio.emit(
            "signal_error",
            {"message": "Signal message requires roomId, to, and type"},
            room=sid,
            namespace=P2P_NAMESPACE,
        )
        return
    target_sid = peer_client_map.get(to_peer_id)
    if target_sid and target_sid != sid:
        data["from"] = client_peer_map.get(sid, "unknown")
        await sio.emit("signal", data, room=target_sid, namespace=P2P_NAMESPACE)
    elif not target_sid:
        await sio.emit(
            "signal_error",
            {"message": f"Target peer '{to_peer_id}' not found"},
            room=sid,
            namespace=P2P_NAMESPACE,
        )


@sio.event(namespace=P2P_NAMESPACE)
async def leave(sid, data: Dict[str, Any]):
    room_id = client_room_map.get(sid)
    peer_id = client_peer_map.get(sid)
    if room_id:
        logger.info(f"[P2P] Client {sid} (Peer: {peer_id}) leaving room {room_id}")
        participants = sio.manager.rooms.get(room_id, {}).get(P2P_NAMESPACE, set())
        other_sids = [p_sid for p_sid in participants if p_sid != sid]
        for other_sid in other_sids:
            await sio.emit(
                "peer_left",
                {"peerId": peer_id},
                room=other_sid,
                namespace=P2P_NAMESPACE,
            )
        await sio.leave_room(
            sid, room_id, namespace=P2P_NAMESPACE
        )  # 修正: await leave_room
        if sid in client_peer_map:
            del client_peer_map[sid]
        if peer_id in peer_client_map:
            del peer_client_map[peer_id]
        if sid in client_room_map:
            del client_room_map[sid]


# Streamer Socket.IO 逻辑 (保持不变)
@sio.event(namespace=STREAMER_NAMESPACE)
async def connect(sid, environ):
    logging.info(f"Streamer client connected: {sid}")
    await enable_streamer_socketio()
    if VLC_AVAILABLE and vlc_streamer:
        try:
            status_data = vlc_streamer.get_status()
            await sio.emit(
                "rtsp_status_update",
                status_data,
                room=sid,
                namespace=STREAMER_NAMESPACE,
            )
        except Exception as e:
            logging.error(f"Error sending initial status to {sid}: {e}")


@sio.event(namespace=STREAMER_NAMESPACE)
async def disconnect(sid):
    logging.info(f"Streamer client disconnected: {sid}")


# --- [新修复 5]: 修改 RTSP 推流 API 以使用锁 ---
@fastapi_app.get("/api/rtsp/status")
async def get_rtsp_status():
    if not VLC_AVAILABLE or not vlc_streamer:
        raise HTTPException(status_code=503, detail="VLC/FFmpeg Streamer 不可用")
    try:
        status_data = vlc_streamer.get_status()
        return status_data
    except Exception as e:
        logging.error(f"获取RTSP状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取状态失败: {str(e)}")


@fastapi_app.post("/api/rtsp/control")
async def control_rtsp(request: RTSPControlRequest):
    global camera_in_use_by, rtsp_player
    if not VLC_AVAILABLE or not vlc_streamer:
        raise HTTPException(status_code=503, detail="VLC/FFmpeg Streamer unavailable")
    action = request.action
    result = "Unknown action"

    with camera_lock:
        if action == "start":
            if camera_in_use_by == "server_push_consuming_streamer":
                raise HTTPException(
                    status_code=409, detail="摄像头正被“服务器直播”功能占用。"
                )
            result = vlc_streamer.start()
            if "启动中" in result or "已在运行" in result:
                camera_in_use_by = "streamer"

        elif action == "stop":
            if camera_in_use_by == "server_push_consuming_streamer":
                logger.warning("[StreamerAPI] 'server_push' 正在使用中，将强制停止...")
                # 强制清理所有 WebRTC 连接
                if rtsp_player:
                    try:
                        rtsp_player.close()  # 同步关闭
                    except Exception as e:
                        logger.error(f"清理 rtsp_player 时出错: {e}")
                    rtsp_player = None
                for sid in list(server_push_pcs.keys()):
                    await cleanup_server_push_client(
                        sid, skip_lock=True
                    )  # 跳过锁，因为我们已经持有它

            result = vlc_streamer.stop()
            camera_in_use_by = None  # 彻底释放

        elif action == "set_params":
            # (set_params 逻辑保持不变)
            new_params = request.model_dump(exclude={"action"}, exclude_unset=True)
            result = "No valid parameters provided"
            if new_params:
                updated = vlc_streamer.configure(**new_params)
                result = "Parameters updated" if updated else "Parameters unchanged"
                if updated and vlc_streamer.is_running():
                    result += f", streamer restarted ({vlc_streamer.restart()})"
    return {"result": result}


# ( ... /api/rtsp/logs, /api/upload/video, /api/videos, /api/videos/{filename} ... )
# ( ... 这些 API 保持不变 ... )
@fastapi_app.get("/api/rtsp/logs")
async def get_rtsp_logs(lines: int = 50):
    if not VLC_AVAILABLE or not vlc_streamer:
        raise HTTPException(status_code=503, detail="VLC/FFmpeg Streamer unavailable")
    try:
        logs = vlc_streamer.get_log(count=lines)
        return {"logs": logs}
    except Exception as e:
        logging.error(f"Failed to get RTSP logs via API: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get logs: {str(e)}")


from fastapi import UploadFile, File
import os
import shutil

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


@fastapi_app.post("/api/upload/video")
async def upload_video(file: UploadFile = File(...)):
    try:
        allowed_types = [
            "video/mp4",
            "video/avi",
            "video/mov",
            "video/mkv",
            "video/webm",
        ]
        if file.content_type not in allowed_types:
            raise HTTPException(status_code=400, detail="不支持的文件类型")
        file_path = os.path.join(UPLOAD_DIR, file.filename)
        file_size = 0
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            file_size = buffer.tell()
        if file_size > 100 * 1024 * 1024:
            os.remove(file_path)
            raise HTTPException(status_code=413, detail="文件大小超过100MB限制")
        duration = -99
        try:
            import cv2

            cap = cv2.VideoCapture(file_path)
            if not cap.isOpened():
                logging.warning(f"无法使用cv2打开视频文件: {file.filename}")
                duration = -1
            else:
                fps = cap.get(cv2.CAP_PROP_FPS)
                frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                duration = (
                    round(frame_count / fps, 2)
                    if fps and fps > 0 and frame_count
                    else 0
                )
                cap.release()
        except ImportError:
            duration = -2
        except Exception as video_info_err:
            logging.error(f"使用cv2获取视频信息时出错: {video_info_err}")
            duration = -3
        return {
            "message": "上传成功",
            "filename": file.filename,
            "size": file_size,
            "duration": duration,
            "path": file_path,
        }
    except Exception as e:
        logging.error(f"视频上传失败: {e}")
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}")


@fastapi_app.get("/api/videos")
async def list_videos():
    try:
        videos = []
        if os.path.exists(UPLOAD_DIR):
            for filename in os.listdir(UPLOAD_DIR):
                file_path = os.path.join(UPLOAD_DIR, filename)
                if os.path.isfile(file_path):
                    file_size = os.path.getsize(file_path)
                    duration = -99
                    try:
                        import cv2

                        cap = cv2.VideoCapture(file_path)
                        if cap.isOpened():
                            fps = cap.get(cv2.CAP_PROP_FPS)
                            frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                            duration = (
                                round(frame_count / fps, 2)
                                if fps and fps > 0 and frame_count
                                else 0
                            )
                            cap.release()
                        else:
                            duration = -1
                    except ImportError:
                        duration = -2
                    except Exception:
                        duration = -3
                    videos.append(
                        {"filename": filename, "size": file_size, "duration": duration}
                    )
        return {"videos": videos}
    except Exception as e:
        logging.error(f"获取视频列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取列表失败: {str(e)}")


@fastapi_app.delete("/api/videos/{filename}")
async def delete_video(filename: str):
    try:
        if "/" in filename or "\\" in filename:
            raise HTTPException(status_code=400, detail="无效的文件名")
        file_path = os.path.join(UPLOAD_DIR, filename)
        if not os.path.abspath(file_path).startswith(os.path.abspath(UPLOAD_DIR)):
            raise HTTPException(status_code=400, detail="无效的文件路径")
        if os.path.exists(file_path) and os.path.isfile(file_path):
            os.remove(file_path)
            return {"message": "删除成功"}
        else:
            raise HTTPException(status_code=404, detail="文件不存在")
    except Exception as e:
        logging.error(f"删除视频失败: {e}")
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")


# --- [新修复 6]: 修改 Server Push (直播) 逻辑以使用锁 ---
SERVER_PUSH_NAMESPACE = "/server_push"
server_push_pcs: Dict[str, RTCPeerConnection] = {}
server_push_tracks: Dict[str, Any] = {}


@sio.event(namespace=SERVER_PUSH_NAMESPACE)
async def connect(sid, environ):
    """
    [V19-FIX] 异步处理连接，防止阻塞。
    """
    global rtsp_player, camera_in_use_by
    logger.info(f"[ServerPush] Client connected: {sid}")

    rtsp_url_to_play = None

    # 1. (快速) 检查 Streamer 是否在运行
    with camera_lock:
        if (
            (
                camera_in_use_by == "streamer"
                or camera_in_use_by == "server_push_consuming_streamer"
            )
            and VLC_AVAILABLE
            and vlc_streamer
            and vlc_streamer.is_running()
        ):

            logger.info(
                f"[ServerPush] (Lock) Streamer 正在运行，将连接到: {vlc_streamer.rtsp_url}"
            )
            rtsp_url_to_play = vlc_streamer.rtsp_url
        else:
            logger.warning(
                f"[ServerPush] (Lock) 拒绝 {sid}：Streamer (FFmpeg) 未在运行。"
            )

    # 2. 如果 Streamer 未运行，立即断开
    if not rtsp_url_to_play:
        disconnect_reason = "服务器推流 (FFmpeg) 未启动，请在控制台启动推流后再观看。"
        logger.warning(f"[ServerPush] 断开 {sid} 连接, 原因: {disconnect_reason}")
        # 我们不能在这里 await，因为我们还在 connect 处理器中
        # 我们返回 False 来拒绝连接
        return False  # 拒绝连接

    # 3. (慢速) 异步创建或获取 Player
    try:
        if rtsp_player is None:
            logger.info(f"[ServerPush] {sid} 正在创建新的 MediaPlayer 实例 (异步)...")

            # [ 关键修复 ]：在后台线程中运行阻塞的 MediaPlayer()
            new_player = await asyncio.to_thread(
                MediaPlayer,
                rtsp_url_to_play,
                options={"rtsp_transport": "tcp", "stimeout": "5000000"},  # 增加超时
            )

            # 再次获取锁，检查在 await 期间是否已有其他客户端创建了 player
            with camera_lock:
                if rtsp_player is None:
                    rtsp_player = new_player
                    camera_in_use_by = "server_push_consuming_streamer"
                    logger.info(f"[ServerPush] (Lock) MediaPlayer 已创建并分配。")
                else:
                    logger.info(
                        f"[ServerPush] (Lock) MediaPlayer 已被创建，关闭这个多余的。"
                    )
                    await asyncio.to_thread(new_player.close)  # 在线程中关闭
        else:
            logger.info(f"[ServerPush] {sid} 将复用现有的 MediaPlayer 实例。")

    except Exception as e:
        logger.error(f"[ServerPush] 创建 MediaPlayer 失败: {e}", exc_info=True)
        return False  # 拒绝连接

    logger.info(f"[ServerPush] 客户端 {sid} 已成功连接并准备好。")
    return True  # 接受连接


@sio.event(namespace=SERVER_PUSH_NAMESPACE)
async def offer(sid, data: Dict[str, Any]):
    global rtsp_player
    logger.info(f"[ServerPush] 收到来自 {sid} 的 Offer")

    offer_desc = data.get("offer")
    if not offer_desc:
        logger.warning(f"[ServerPush] {sid} 的 Offer 数据缺失。")
        return

    if rtsp_player is None or rtsp_player.video is None:
        logger.error(f"[ServerPush] {sid} 发送了 Offer, 但 rtsp_player 不可用!")
        await sio.emit(
            "error",
            {"message": "服务器RTSP播放器不可用"},
            room=sid,
            namespace=SERVER_PUSH_NAMESPACE,
        )
        return

    offer_sdp = RTCSessionDescription(sdp=offer_desc["sdp"], type=offer_desc["type"])
    pc = RTCPeerConnection()
    server_push_pcs[sid] = {
        "pc": pc,
        "candidates": [],
    }  # 移除缓冲逻辑，我们有 on('icecandidate')

    @pc.on("icecandidate")
    async def on_icecandidate(candidate):
        if candidate:
            logger.debug(
                f"[ServerPush] {sid} 生成了一个 ICE candidate: {candidate.type}"
            )
            await sio.emit(
                "candidate",
                {
                    "candidate": candidate.sdp,
                    "sdpMid": candidate.sdpMid,
                    "sdpMLineIndex": candidate.sdpMLineIndex,
                    "type": "ice-candidate",
                },
                room=sid,
                namespace=SERVER_PUSH_NAMESPACE,
            )
        else:
            logger.info(f"[ServerPush] {sid} ICE 收集完毕 (null candidate)。")
            await sio.emit(
                "candidate",
                {"candidate": None, "type": "ice-candidate"},
                room=sid,
                namespace=SERVER_PUSH_NAMESPACE,
            )

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        logger.info(f"[ServerPush] {sid} 的 PC 状态: {pc.connectionState}")
        if pc.connectionState == "failed" or pc.connectionState == "closed":
            await cleanup_server_push_client(sid)

    try:
        video_track = relay.subscribe(rtsp_player.video)
        server_push_tracks[sid] = video_track
        pc.addTrack(video_track)
        logger.info(f"[ServerPush] {sid} 已从 MediaRelay 订阅 RTSP 视频轨道")

        await pc.setRemoteDescription(offer_sdp)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        await sio.emit(
            "answer",
            {
                "answer": {
                    "sdp": pc.localDescription.sdp,
                    "type": pc.localDescription.type,
                },
                "type": "answer",
            },
            room=sid,
            namespace=SERVER_PUSH_NAMESPACE,
        )
        logger.info(f"[ServerPush] {sid} 的 Answer 已发送。")
    except Exception as e:
        logger.error(f"[ServerPush] {sid} 处理 offer 时出错: {e}", exc_info=True)
        await sio.emit(
            "error",
            {"message": f"Failed to process offer: {str(e)}"},
            room=sid,
            namespace=SERVER_PUSH_NAMESPACE,
        )
        await cleanup_server_push_client(sid)


@sio.event(namespace=SERVER_PUSH_NAMESPACE)
async def candidate(sid, data: Dict[str, Any]):
    logger.debug(f"[ServerPush] 收到来自 {sid} 的 Candidate: {data.get('candidate')}")
    client_data = server_push_pcs.get(sid)
    if not client_data:
        return

    pc = client_data["pc"]
    if pc.remoteDescription is None:
        logger.warning(
            f"[ServerPush] {sid} 的 Candidate 到达，但 RemoteDescription 未设置。"
        )
        return  # 理论上不应该发生，但作为保护

    try:
        cand_data = data.get("candidate")
        if cand_data:
            if isinstance(cand_data, dict) and "candidate" in cand_data:
                sdp = cand_data["candidate"]
                parts = sdp.split()
                if len(parts) < 8:
                    logger.error(f"无法解析: {sdp}")
                    return

                ice = RTCIceCandidate(
                    component=int(parts[1]),
                    foundation=parts[0].split(":")[1],
                    ip=parts[4],
                    port=int(parts[5]),
                    priority=int(parts[3]),
                    protocol=parts[2],
                    type=parts[7],
                    sdpMid=cand_data.get("sdpMid"),
                    sdpMLineIndex=cand_data.get("sdpMLineIndex"),
                )
                await pc.addIceCandidate(ice)
            else:
                logger.warning(
                    f"[ServerPush] {sid} 的 candidate 格式不支持: {cand_data}"
                )
        else:
            await pc.addIceCandidate(None)
    except Exception as e:
        if "closed" not in str(e):
            logger.error(
                f"[ServerPush] {sid} 添加 candidate 时出错: {e}", exc_info=True
            )


async def cleanup_server_push_client(sid, skip_lock=False):
    """
    [V19-FIX] 清理客户端，并在后台线程中关闭 I/O。
    """
    global rtsp_player, camera_in_use_by
    logger.info(f"[ServerPush] 正在清理客户端: {sid}")

    client_data = server_push_pcs.pop(sid, None)
    track = server_push_tracks.pop(sid, None)

    if track:
        track.stop()
        logger.debug(f"[ServerPush] {sid} 的订阅轨道已停止。")

    if client_data:
        pc = client_data.get("pc")
        if pc and pc.connectionState != "closed":
            try:
                pc.close()  # [ 关键修复 ]：close() 是同步的，不是 await
                logger.debug(f"[ServerPush] {sid} 的 PC 已关闭。")
            except Exception as e:
                logger.error(f"[ServerPush] {sid} 关闭 PC 时出错: {e}", exc_info=True)

    # 检查是否是最后一个客户端
    if not server_push_pcs:
        logger.info(f"[ServerPush] {sid} 是最后一个客户端。")

        player_to_close = None
        if not skip_lock:
            with camera_lock:
                if rtsp_player and not server_push_pcs:  # 双重检查
                    logger.info(
                        "[ServerPush] (Lock) 最后一个客户端已断开，正在释放 MediaPlayer..."
                    )
                    player_to_close = rtsp_player
                    rtsp_player = None
                    if camera_in_use_by == "server_push_consuming_streamer":
                        camera_in_use_by = "streamer"
        else:  # skip_lock 为 True (来自 control_rtsp)
            if rtsp_player and not server_push_pcs:
                logger.info("[ServerPush] (Lock-Skipped) 正在释放 MediaPlayer...")
                player_to_close = rtsp_player
                rtsp_player = None
                # camera_in_use_by 状态由 control_rtsp 自己管理

        if player_to_close:
            logger.info(f"[ServerPush] 正在后台线程中关闭 MediaPlayer...")
            # [ 关键修复 ]：在线程中关闭阻塞的 I/O
            await asyncio.to_thread(player_to_close.close)
            logger.info(f"[ServerPush] MediaPlayer 已关闭。")

    else:
        logger.info(
            f"[ServerPush] {sid} 断开, 但仍有 {len(server_push_pcs)} 个其他客户端在连接。"
        )


@sio.event(namespace=SERVER_PUSH_NAMESPACE)
async def disconnect(sid):
    logger.info(f"[ServerPush] Client disconnected: {sid}")
    await cleanup_server_push_client(sid)


# 根路由和健康检查 (保持不变)
@fastapi_app.get("/")
async def root():
    return {"message": "WebRTC Server is running", "status": "ok"}


@fastapi_app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": time.time()}


@fastapi_app.get("/api/info")
async def server_info():
    return {
        "server": "WebRTC Server",
        "version": "1.0.0",
        "socketio_namespaces": ["/p2p", "/streamer", "/server_push"],
        "vlc_available": VLC_AVAILABLE,
    }


# main 入口 (保持不变)
if __name__ == "__main__":
    import uvicorn
    import os

    base_dir = os.path.dirname(os.path.abspath(__file__))
    cert_dir = os.path.abspath(os.path.join(base_dir, "..", "frontend", "certs"))
    ssl_keyfile = os.path.join(cert_dir, "localhost+3-key.pem")
    ssl_certfile = os.path.join(cert_dir, "localhost+3.pem")
    if not os.path.exists(ssl_keyfile) or not os.path.exists(ssl_certfile):
        print("错误: SSL 证书文件未找到!")
        exit(1)
    print(f"使用SSL证书: {ssl_certfile}")
    print(f"使用SSL密钥: {ssl_keyfile}")
    print("启动HTTPS服务器 (带重载) 在 https://0.0.0.0:33335")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=33335,
        reload=True,
        ssl_keyfile=ssl_keyfile,
        ssl_certfile=ssl_certfile,
    )
