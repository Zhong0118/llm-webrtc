# handlers/ai.py
import logging
import asyncio
from typing import Dict, Any, List
import socketio
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCIceCandidate
from aiortc.mediastreams import MediaStreamError
import time

# 配置更详细的日志
logger = logging.getLogger("AIHandler")
logger.setLevel(logging.DEBUG)  # 开启调试日志

AI_NAMESPACE = "/ai_analysis"

# AI State
ai_pcs: Dict[str, RTCPeerConnection] = {}
sid_room_map = {}
# ICE Candidate 缓冲池
ice_candidate_buffers: Dict[str, List[RTCIceCandidate]] = {}

async def process_ai_track(track, sid, sio, ai_processor, room_id, peer_id):
    """
    后台任务：消费视频帧并运行 AI 推理
    """
    logger.info(f"[AI-Worker] Started processing track for SID:{sid} Peer:{peer_id}")
    
    # [关键] 性能控制变量
    last_process_time = 0
    min_interval = 0.05  # 限制 AI 最大处理帧率 (约 20 FPS)，防止 CPU 爆炸
    
    try:
        while True:
            try:
                # 1. 获取帧 (这一步是实时的)
                # aiortc 的 recv() 会尝试给下一帧。
                # 如果我们处理慢了，aiortc 内部可能会积压。
                frame = await track.recv()
            except MediaStreamError:
                logger.info(f"[AI-Worker] Track ended for {sid}")
                break
            
            # 2. [核心策略] 丢帧逻辑 (Drop Frames)
            # 如果距离上次处理时间太短，直接丢弃，追赶实时画面
            now = time.time()
            if now - last_process_time < min_interval:
                # 丢弃这一帧，不送进 AI，也不广播
                continue
            
            last_process_time = now
            
            # 3. 运行 AI 处理 (耗时操作)
            # 这里的 process 是同步的，会阻塞这个协程，直到推理完成
            # 这天然形成了一种“背压”：推理没完，就不会去 recv 下一帧
            try:
                # 这里的 frame 是 aiortc 的 VideoFrame 对象
                # 我们将它转交给 ai_processor
                
                # 在线程池中运行同步的 process 方法，避免阻塞整个 asyncio 循环
                # 这是一个高级优化，防止 socket 心跳断连
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, ai_processor.process, frame)
                
                # 4. 注入身份信息
                result['peerId'] = peer_id 
                
                # 5. 广播结果
                if room_id:
                    await sio.emit('ai_result', result, room=room_id, namespace=AI_NAMESPACE)
                else:
                    await sio.emit('ai_result', result, room=sid, namespace=AI_NAMESPACE)
                    
            except Exception as e:
                logger.error(f"[AI-Worker] AI Inference Error: {e}")
            
    except asyncio.CancelledError:
        logger.info(f"[AI-Worker] Processing task cancelled for {sid}")
    except Exception as e:
        logger.error(f"[AI-Worker] Critical error: {e}")
    finally:
        logger.info(f"[AI-Worker] Stopped processing track for {sid}")

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