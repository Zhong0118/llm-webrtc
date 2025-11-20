import logging
import asyncio
import os
import shutil
import threading
from typing import Dict, Any, Optional
import socketio
from fastapi import FastAPI, HTTPException, UploadFile, File
from pydantic import BaseModel
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCIceCandidate, VideoStreamTrack
from aiortc.contrib.media import MediaRelay, MediaPlayer

logger = logging.getLogger("StreamerHandler")
STREAMER_NAMESPACE = "/streamer"
SERVER_PUSH_NAMESPACE = "/server_push"

# Shared State (Passed from main)
class StreamerContext:
    def __init__(self, vlc_streamer):
        self.vlc_streamer = vlc_streamer
        self.camera_lock = threading.Lock()
        self.camera_in_use_by = None # "streamer" or "server_push_consuming_streamer"
        self.rtsp_player = None
        self.relay = MediaRelay()

# Local State
server_push_pcs: Dict[str, RTCPeerConnection] = {}
server_push_tracks: Dict[str, Any] = {}

# Models
class RTSPControlRequest(BaseModel):
    action: str
    resolution: Optional[str] = None
    fps: Optional[int] = None
    crf: Optional[int] = None
    preset: Optional[str] = None

async def cleanup_server_push_client(sid, context: StreamerContext, skip_lock=False):
    logger.info(f"[ServerPush] Cleaning up client: {sid}")
    client_data = server_push_pcs.pop(sid, None)
    track = server_push_tracks.pop(sid, None)

    if track:
        track.stop()

    if client_data:
        pc = client_data.get("pc")
        if pc and pc.connectionState != "closed":
            try:
                pc.close()
            except Exception as e:
                logger.error(f"Error closing PC for {sid}: {e}")

    if not server_push_pcs:
        logger.info(f"[ServerPush] Last client disconnected.")
        player_to_close = None
        
        if not skip_lock:
            with context.camera_lock:
                if context.rtsp_player and not server_push_pcs:
                    player_to_close = context.rtsp_player
                    context.rtsp_player = None
                    if context.camera_in_use_by == "server_push_consuming_streamer":
                        context.camera_in_use_by = "streamer"
        else:
             if context.rtsp_player and not server_push_pcs:
                player_to_close = context.rtsp_player
                context.rtsp_player = None

        if player_to_close:
            logger.info(f"[ServerPush] Closing MediaPlayer...")
            await asyncio.to_thread(player_to_close.close)

def register_streamer_handlers(app: FastAPI, sio: socketio.AsyncServer, context: StreamerContext):
    
    # --- Socket.IO: Streamer Namespace ---
    @sio.event(namespace=STREAMER_NAMESPACE)
    async def connect(sid, environ):
        logging.info(f"Streamer client connected: {sid}")
        if context.vlc_streamer:
            context.vlc_streamer.enable_socketio()
            try:
                status_data = context.vlc_streamer.get_status()
                await sio.emit("rtsp_status_update", status_data, room=sid, namespace=STREAMER_NAMESPACE)
            except Exception as e:
                logging.error(f"Error sending status: {e}")

    @sio.event(namespace=STREAMER_NAMESPACE)
    async def disconnect(sid):
        logging.info(f"Streamer client disconnected: {sid}")

    # --- Socket.IO: Server Push Namespace ---
    @sio.event(namespace=SERVER_PUSH_NAMESPACE)
    async def connect_push(sid, environ):
        logger.info(f"[ServerPush] Client connected: {sid}")
        rtsp_url_to_play = None

        with context.camera_lock:
            if (context.camera_in_use_by in ["streamer", "server_push_consuming_streamer"] 
                and context.vlc_streamer and context.vlc_streamer.is_running()):
                rtsp_url_to_play = context.vlc_streamer.rtsp_url
            else:
                logger.warning(f"[ServerPush] Streamer not running. Rejecting {sid}")
        
        if not rtsp_url_to_play:
            return False

        try:
            if context.rtsp_player is None:
                new_player = await asyncio.to_thread(
                    MediaPlayer, rtsp_url_to_play, options={"rtsp_transport": "tcp", "stimeout": "5000000"}
                )
                with context.camera_lock:
                    if context.rtsp_player is None:
                        context.rtsp_player = new_player
                        context.camera_in_use_by = "server_push_consuming_streamer"
                    else:
                        await asyncio.to_thread(new_player.close)
        except Exception as e:
            logger.error(f"Failed to create player: {e}")
            return False
        return True

    @sio.event(namespace=SERVER_PUSH_NAMESPACE)
    async def disconnect_push(sid):
        logger.info(f"[ServerPush] Client disconnected: {sid}")
        await cleanup_server_push_client(sid, context)

    @sio.event(namespace=SERVER_PUSH_NAMESPACE)
    async def offer(sid, data: Dict[str, Any]):
        offer_desc = data.get("offer")
        if not offer_desc or not context.rtsp_player or not context.rtsp_player.video:
            return

        pc = RTCPeerConnection()
        server_push_pcs[sid] = {"pc": pc, "candidates": []}

        @pc.on("icecandidate")
        async def on_icecandidate(candidate):
            if candidate:
                await sio.emit("candidate", {
                    "candidate": candidate.sdp, "sdpMid": candidate.sdpMid, 
                    "sdpMLineIndex": candidate.sdpMLineIndex, "type": "ice-candidate"
                }, room=sid, namespace=SERVER_PUSH_NAMESPACE)
            else:
                await sio.emit("candidate", {"candidate": None}, room=sid, namespace=SERVER_PUSH_NAMESPACE)

        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            if pc.connectionState in ["failed", "closed"]:
                await cleanup_server_push_client(sid, context)

        try:
            video_track = context.relay.subscribe(context.rtsp_player.video)
            server_push_tracks[sid] = video_track
            pc.addTrack(video_track)
            await pc.setRemoteDescription(RTCSessionDescription(sdp=offer_desc["sdp"], type=offer_desc["type"]))
            answer = await pc.createAnswer()
            await pc.setLocalDescription(answer)
            await sio.emit("answer", {"answer": {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}}, room=sid, namespace=SERVER_PUSH_NAMESPACE)
        except Exception as e:
            logger.error(f"Error handling offer: {e}")
            await cleanup_server_push_client(sid, context)

    @sio.event(namespace=SERVER_PUSH_NAMESPACE)
    async def candidate(sid, data: Dict[str, Any]):
        client_data = server_push_pcs.get(sid)
        if client_data:
            pc = client_data["pc"]
            cand_data = data.get("candidate")
            if cand_data and isinstance(cand_data, dict):
                ice = RTCIceCandidate(
                    component=int(cand_data.get("candidate").split()[1]),
                    foundation=cand_data.get("candidate").split()[0].split(":")[1],
                    ip=cand_data.get("candidate").split()[4],
                    port=int(cand_data.get("candidate").split()[5]),
                    priority=int(cand_data.get("candidate").split()[3]),
                    protocol=cand_data.get("candidate").split()[2],
                    type=cand_data.get("candidate").split()[7],
                    sdpMid=cand_data.get("sdpMid"),
                    sdpMLineIndex=cand_data.get("sdpMLineIndex")
                )
                await pc.addIceCandidate(ice)
            else:
                await pc.addIceCandidate(None)

    # --- HTTP APIs ---
    @app.get("/api/rtsp/status")
    async def get_rtsp_status():
        if not context.vlc_streamer:
            raise HTTPException(status_code=503, detail="Streamer unavailable")
        return context.vlc_streamer.get_status()

    @app.post("/api/rtsp/control")
    async def control_rtsp(request: RTSPControlRequest):
        if not context.vlc_streamer:
            raise HTTPException(status_code=503, detail="Streamer unavailable")
        
        action = request.action
        result = "Unknown"
        
        with context.camera_lock:
            if action == "start":
                if context.camera_in_use_by == "server_push_consuming_streamer":
                    raise HTTPException(status_code=409, detail="Camera in use by Server Push")
                result = context.vlc_streamer.start()
                if "启动中" in result or "已在运行" in result:
                    context.camera_in_use_by = "streamer"
            
            elif action == "stop":
                if context.camera_in_use_by == "server_push_consuming_streamer":
                    # Force cleanup
                    if context.rtsp_player:
                        context.rtsp_player.close()
                        context.rtsp_player = None
                    for sid in list(server_push_pcs.keys()):
                        await cleanup_server_push_client(sid, context, skip_lock=True)
                
                result = context.vlc_streamer.stop()
                context.camera_in_use_by = None

            elif action == "set_params":
                new_params = request.model_dump(exclude={"action"}, exclude_unset=True)
                if new_params:
                    updated = context.vlc_streamer.configure(**new_params)
                    result = "Updated"
                    if updated and context.vlc_streamer.is_running():
                        context.vlc_streamer.restart()

        return {"result": result}

    @app.get("/api/rtsp/logs")
    async def get_rtsp_logs(lines: int = 50):
        if context.vlc_streamer:
            return {"logs": context.vlc_streamer.get_log(count=lines)}
        return {"logs": []}

    # File Uploads
    UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    @app.post("/api/upload/video")
    async def upload_video(file: UploadFile = File(...)):
        # (Simplified upload logic)
        file_path = os.path.join(UPLOAD_DIR, file.filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        return {"message": "Success", "filename": file.filename}

    @app.get("/api/videos")
    async def list_videos():
        videos = []
        if os.path.exists(UPLOAD_DIR):
            for f in os.listdir(UPLOAD_DIR):
                videos.append({"filename": f})
        return {"videos": videos}

    @app.delete("/api/videos/{filename}")
    async def delete_video(filename: str):
        p = os.path.join(UPLOAD_DIR, filename)
        if os.path.exists(p):
            os.remove(p)
            return {"message": "Deleted"}
        raise HTTPException(status_code=404)
