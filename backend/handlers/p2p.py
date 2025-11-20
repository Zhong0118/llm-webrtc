import logging
from typing import Dict, Any, Set
import socketio

logger = logging.getLogger("P2PHandler")
P2P_NAMESPACE = "/p2p"

# P2P State
client_peer_map: Dict[str, str] = {}
peer_client_map: Dict[str, str] = {}
client_room_map: Dict[str, str] = {}

room_participants: Dict[str, Set[str]] = {} # roomId -> Set[sid]
def register_p2p_handlers(sio: socketio.AsyncServer):
    
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

        if room_id not in room_participants:
            room_participants[room_id] = set()
        room_participants[room_id].add(sid)
    
        await sio.enter_room(sid, room_id, namespace=P2P_NAMESPACE)
        logger.info(f"[P2P] Client {sid} (Peer: {peer_id}) joined room: {room_id}")
        await sio.emit(
            "joined",
            {"roomId": room_id, "peerId": peer_id},
            room=sid,
            namespace=P2P_NAMESPACE,
        )
        current_room_sids = room_participants.get(room_id, set())
        other_sids = [p_sid for p_sid in current_room_sids if p_sid != sid]
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

            if room_id in room_participants:
                room_participants[room_id].discard(sid)
                # 如果房间空了，删除 key
                if not room_participants[room_id]:
                    del room_participants[room_id]
            remaining_sids = room_participants.get(room_id, set())
            for other_sid in remaining_sids:
                 await sio.emit("peer_left", {"peerId": peer_id}, room=other_sid, namespace=P2P_NAMESPACE)
            await sio.leave_room(sid, room_id, namespace=P2P_NAMESPACE)
            if sid in client_peer_map:
                del client_peer_map[sid]
            if peer_id in peer_client_map:
                del peer_client_map[peer_id]
            if sid in client_room_map:
                del client_room_map[sid]
