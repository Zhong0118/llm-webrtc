# handlers/ai.py
import logging
import asyncio
from typing import Dict, Any, List
import socketio
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCIceCandidate
from aiortc.mediastreams import MediaStreamError
import time
import json

# 配置更详细的日志
logger = logging.getLogger("AIHandler")
logger.setLevel(logging.DEBUG)  # 开启调试日志

AI_NAMESPACE = "/ai_analysis"

# AI State
ai_pcs: Dict[str, RTCPeerConnection] = {}
sid_room_map = {}
# ICE Candidate 缓冲池
ice_candidate_buffers: Dict[str, List[RTCIceCandidate]] = {}

# backend/handlers/ai.py

async def process_ai_track(track, sid, sio, ai_processor, room_id, peer_id):
    logger.info(f"[AI-Worker] Started processing track for SID:{sid}")
    
    # [核心修改 1] 计时起点：函数被调用意味着 WebRTC 链路已打通，数据开始流入
    # 这时候相当于用户已经完成了 ICE 握手，开始等待 AI 响应
    pipeline_start_time = time.time()
    
    # 1. 预热 (Warmup)
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, ai_processor.warmup)
    
    # 2. 物理消除积压 (Flush)
    dropped_frames = 0
    if hasattr(track, "_queue"):
        while track._queue.qsize() > 0:
            try:
                _ = track._queue.get_nowait()
                dropped_frames += 1
            except: break
            
    # [核心修改 2] 计算总耗时
    # 这个时间涵盖了：模型加载 + CUDA初始化 + 冲掉积压数据的耗时
    # 这就是"这7秒"里后端真正干活的时间
    actual_startup_duration = (time.time() - pipeline_start_time) * 1000
    
    logger.info(f"[AI-Worker] Ready! Total Startup: {actual_startup_duration:.0f}ms | Flushed: {dropped_frames}")

    # 3. 发送 Ready 信号 (直接把算好的时间发给前端)
    target = room_id if room_id else sid
    await sio.emit('ai_status', {
        'status': 'ready',
        'peerId': peer_id,
        'startup_time': actual_startup_duration, # <--- 前端直接显示这个
        'dropped_frames': dropped_frames         # (可选) 告诉前端丢了多少帧
    }, room=target, namespace=AI_NAMESPACE)

    # [Step 4] 进入主循环
    last_process_time = 0
    min_interval = 0.05 
    debug_last_print_time = 0

    while True:
        try:
            frame = await track.recv()
        except MediaStreamError:
            logger.info(f"[AI-Worker] Track ended for {sid}")
            break
        
        # 获取时间戳
        pts = frame.pts 
        time_base = frame.time_base
        now = time.time()
        
        # 限流逻辑
        if now - last_process_time < min_interval:
            continue
        last_process_time = now
        
        # 运行推理
        try:
            result = await loop.run_in_executor(
                None, 
                ai_processor.process, 
                frame, 
                pts,       
                time_base 
            )
            
            if result is None: continue

            result['peerId'] = peer_id 
            
            # 定期打印 Debug 信息 (每5秒)
            now_ts = time.time()
            if now_ts - debug_last_print_time > 5:
                # 简单打印关键信息
                print(f"\n[AI Debug] Peer:{peer_id} FPS:{result.get('fps')} Delay:{result.get('d_an')}ms Obj:{len(result.get('objects',[]))}")
                debug_last_print_time = now_ts
            
            # 广播结果
            if room_id:
                await sio.emit('ai_result', result, room=room_id, namespace=AI_NAMESPACE)
            else:
                await sio.emit('ai_result', result, room=sid, namespace=AI_NAMESPACE)
                
        except Exception as e:
            logger.error(f"[AI-Worker] Inference Error: {e}")

def register_ai_handlers(sio: socketio.AsyncServer, ai_processor):
    
    @sio.event(namespace=AI_NAMESPACE)
    async def connect(sid, environ):
        logger.info(f"[AI] Client connected: {sid}")
        ice_candidate_buffers[sid] = [] # 初始化 buffer

    @sio.event(namespace=AI_NAMESPACE)
    async def disconnect(sid):
        logger.info(f"[AI] Client disconnected: {sid}")
        if sid in ai_pcs:
            await ai_pcs[sid].close()
            del ai_pcs[sid]
        if sid in sid_room_map:
            del sid_room_map[sid]
        if sid in ice_candidate_buffers:
            del ice_candidate_buffers[sid]

    @sio.event(namespace=AI_NAMESPACE)
    async def join(sid, data: Dict[str, Any]):
        room_id = data.get("roomId")
        if room_id:
            # [修复] 必须加 await，否则进房失败
            await sio.enter_room(sid, room_id, namespace=AI_NAMESPACE)
            sid_room_map[sid] = room_id
            logger.info(f"[AI] SID {sid} joined AI room {room_id}")

    @sio.event(namespace=AI_NAMESPACE)
    async def offer(sid, data: Dict[str, Any]):
        logger.info(f"[AI] Received offer from {sid}")
        offer_desc = data.get("offer")
        room_id = data.get("roomId")
        peer_id = data.get("peerId")

        if not offer_desc or not peer_id:
            logger.error(f"[AI] Offer missing peerId or SDP from {sid}")
            return

        if room_id:
            # [修复] 必须加 await，否则进房失败
            await sio.enter_room(sid, room_id, namespace=AI_NAMESPACE)
            sid_room_map[sid] = room_id

        pc = RTCPeerConnection()
        ai_pcs[sid] = pc

        @pc.on("icecandidate")
        async def on_icecandidate(candidate):
            # [修复] 实现 Server -> Client 的 Trickle ICE
            # 即使大部分 Candidate 都在 SDP 里，这也是更健壮的做法
            if candidate:
                # aiortc 的 candidate 对象转 JSON 可能需要手动处理，或者用 candidate.to_sdp()
                # 这里 aiortc 的 candidate 是 RTCIceCandidate 对象
                # 它的结构比较简单，我们构造一个标准的 candidate 字典发给前端
                candidate_dict = {
                    "candidate": candidate.to_sdp(),
                    "sdpMid": candidate.sdpMid,
                    "sdpMLineIndex": candidate.sdpMLineIndex
                }
                await sio.emit(
                    "candidate",
                    {"candidate": candidate_dict},
                    room=sid,
                    namespace=AI_NAMESPACE
                )

        @pc.on("track")
        def on_track(track):
            logger.info(f"[AI] Track received: {track.kind}")
            if track.kind == "video":
                asyncio.create_task(process_ai_track(track, sid, sio, ai_processor, room_id, peer_id))

        try:
            logger.info(f"[AI] Setting Remote Description for {sid}...")
            await pc.setRemoteDescription(RTCSessionDescription(sdp=offer_desc["sdp"], type=offer_desc["type"]))
            
            # 处理缓冲的 ICE Candidates
            if sid in ice_candidate_buffers and ice_candidate_buffers[sid]:
                buffered_candidates = ice_candidate_buffers[sid]
                logger.info(f"[AI] Processing {len(buffered_candidates)} buffered candidates for {sid}...")
                for candidate in buffered_candidates:
                    await pc.addIceCandidate(candidate)
                ice_candidate_buffers[sid] = [] 

            logger.info(f"[AI] Creating Answer for {sid}...")
            answer = await pc.createAnswer()
            await pc.setLocalDescription(answer)

            await sio.emit(
                "answer",
                {"answer": {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}},
                room=sid,
                namespace=AI_NAMESPACE,
            )
            logger.info(f"[AI] Answer sent to {sid}")

        except Exception as e:
            logger.error(f"[AI] Error handling offer for {sid}: {e}")
            import traceback
            logger.error(traceback.format_exc())

    @sio.event(namespace=AI_NAMESPACE)
    async def candidate(sid, data: Dict[str, Any]):
        try:
            cand_data = data.get("candidate")
            if not cand_data: return

            if isinstance(cand_data, dict) and "candidate" in cand_data:
                sdp_mid = cand_data.get("sdpMid")
                sdp_mline_index = cand_data.get("sdpMLineIndex")
                candidate_str = cand_data["candidate"]
                
                parts = candidate_str.split()
                if len(parts) < 8: return

                ice = RTCIceCandidate(
                    component=int(parts[1]),
                    foundation=parts[0].split(":")[1],
                    ip=parts[4],
                    port=int(parts[5]),
                    priority=int(parts[3]),
                    protocol=parts[2],
                    type=parts[7],
                    sdpMid=sdp_mid,
                    sdpMLineIndex=sdp_mline_index,
                )

                pc = ai_pcs.get(sid)
                if pc and pc.remoteDescription:
                    await pc.addIceCandidate(ice)
                    logger.debug(f"[AI] Added ICE candidate for {sid}")
                else:
                    logger.info(f"[AI] Buffering ICE candidate for {sid} (RemoteDesc not ready)")
                    if sid not in ice_candidate_buffers:
                        ice_candidate_buffers[sid] = []
                    ice_candidate_buffers[sid].append(ice)
            
        except Exception as e:
            logger.error(f"[AI] Error handling candidate for {sid}: {e}")

    @sio.event(namespace=AI_NAMESPACE)
    async def update_config(sid, data):
        """允许客户端动态调整 AI 参数"""
        if hasattr(ai_processor, 'update_config'):
            ai_processor.update_config(data)
            await sio.emit('config_updated', data, room=sid)