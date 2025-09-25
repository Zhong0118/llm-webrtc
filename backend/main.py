# main.py
import asyncio
import logging
import random
import socketio
from fastapi import FastAPI

# 配置日志记录
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logging.info("--- V3 后端代码已成功加载，信令转发逻辑已更新 ---")

# 创建 Socket.IO 服务器实例
# async_mode='asgi' 指定使用ASGI模式，与FastAPI兼容
# cors_allowed_origins='*' 允许所有来源的跨域请求
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')

fastapi_app = FastAPI()

# 将 FastAPI 应用和 Socket.IO 服务器组合成一个单一的ASGI应用
# WebSocket请求将被路由到sio，而HTTP请求将被路由到fastapi_app
app = socketio.ASGIApp(socketio_server=sio, other_asgi_app=fastapi_app)

# 存储房间信息：房间ID -> 客户端SID列表
rooms = {}
# 存储客户端信息：客户端SID -> 房间ID
client_rooms = {}

async def mock_ai_analysis_task():
    """
    一个独立的后台任务，在第一个用户连接后启动。
    它会每隔2秒向所有已连接的客户端广播一条伪造的AI分析结果。
    """
    logging.info("模拟AI分析任务已启动...")
    # 使用一个简单的标志来确保这个无限循环的任务只被启动一次
    if hasattr(sio, 'task_started') and sio.task_started:
        return
    sio.task_started = True
    while True:
        await asyncio.sleep(2)
        # 模拟数据
        mock_result = {
            "faces": [{"id": i, "confidence": round(random.uniform(0.7, 0.99), 2)} for i in range(random.randint(0, 3))],
            "objects": [{"label": random.choice(["杯子", "键盘", "鼠标"]), "confidence": round(random.uniform(0.6, 0.95), 2)} for i in range(random.randint(0, 2))],
            "confidence": round(random.uniform(0.8, 0.98), 2),
            "processingTime": random.randint(50, 150)
        }
        await sio.emit('analysis_result', mock_result)
        logging.info(f"已广播模拟AI结果")

def get_or_create_room():
    # 寻找有空位的房间（少于2个客户端）
    for room_id, clients in rooms.items():
        if len(clients) < 2:
            return room_id
    # 如果没有可用房间，创建新房间
    room_id = f"room_{len(rooms) + 1}"
    rooms[room_id] = []
    logging.info(f"创建新房间: {room_id}")
    return room_id

def add_client_to_room(sid, room_id):
    if room_id not in rooms:
        rooms[room_id] = []
    if sid not in rooms[room_id]:
        rooms[room_id].append(sid)
        client_rooms[sid] = room_id
        logging.info(f"客户端 {sid} 加入房间 {room_id}")
    return len(rooms[room_id])

def remove_client_from_room(sid):
    if sid in client_rooms:
        room_id = client_rooms[sid]
        if room_id in rooms and sid in rooms[room_id]:
            rooms[room_id].remove(sid)
            logging.info(f"客户端 {sid} 离开房间 {room_id}")
            if len(rooms[room_id]) == 0:
                del rooms[room_id]
                logging.info(f"删除空房间 {room_id}")
        
        del client_rooms[sid]

def get_room_peer(sid):
    if sid not in client_rooms:
        return None
    room_id = client_rooms[sid]
    if room_id not in rooms:
        return None
    room_clients = rooms[room_id]
    peers = [client for client in room_clients if client != sid]
    return peers[0] if peers else None

@sio.on('connect')
async def connect(sid, environ):
    """
    当一个新的客户端通过WebSocket连接成功时，这个函数会被调用。
    """
    logging.info(f"客户端连接成功: sid='{sid}'")
    room_id = get_or_create_room()
    client_count = add_client_to_room(sid, room_id)
    await sio.emit('room_joined', {
        'room_id': room_id,
        'client_count': client_count
    }, room=sid)
    if client_count == 2:
        await sio.emit('room_ready', {
            'room_id': room_id,
            'message': '房间已满，可以开始通话'
        }, room=room_id)
        logging.info(f"房间 {room_id} 已满，可以开始通话")
    sio.start_background_task(mock_ai_analysis_task)

@sio.on('disconnect')
def disconnect(sid):
    """
    当一个客户端断开连接时，这个函数会被调用。
    """
    logging.info(f"客户端断开连接: sid='{sid}'")
    remove_client_from_room(sid)

@sio.on('webrtc_offer')
async def handle_offer(sid, offer):
    """
    接收到'webrtc_offer'事件后，将其转发给房间中的对等端。
    """
    logging.info(f"从 sid='{sid}' 收到 Offer，准备转发...")
    
    # 获取房间中的对等端
    peer_sid = get_room_peer(sid)
    if peer_sid:
        await sio.emit('webrtc_offer', offer, room=peer_sid)
        logging.info(f"Offer 已转发给对等端 {peer_sid}")
    else:
        logging.warning(f"未找到 sid='{sid}' 的对等端，无法转发 Offer")

@sio.on('webrtc_answer')
async def handle_answer(sid, answer):
    """
    接收到'webrtc_answer'事件后，将其转发给房间中的对等端。
    """
    logging.info(f"从 sid='{sid}' 收到 Answer，准备转发...")
    
    # 获取房间中的对等端
    peer_sid = get_room_peer(sid)
    if peer_sid:
        await sio.emit('webrtc_answer', answer, room=peer_sid)
        logging.info(f"Answer 已转发给对等端 {peer_sid}")
    else:
        logging.warning(f"未找到 sid='{sid}' 的对等端，无法转发 Answer")

@sio.on('ice_candidate')
async def handle_ice_candidate(sid, candidate):
    """
    接收到'ice_candidate'事件后，将其转发给房间中的对等端。
    """
    logging.info(f"从 sid='{sid}' 收到 ICE Candidate，准备转发...")
    
    # 获取房间中的对等端
    peer_sid = get_room_peer(sid)
    if peer_sid:
        await sio.emit('ice_candidate', candidate, room=peer_sid)
        logging.info(f"ICE Candidate 已转发给对等端 {peer_sid}")
    else:
        logging.warning(f"未找到 sid='{sid}' 的对等端，无法转发 ICE Candidate")

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8000)