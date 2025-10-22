# main.py
import asyncio
import logging
import random
import socketio
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import sys
import os

# 添加VLC模块路径
sys.path.append(os.path.join(os.path.dirname(__file__), 'VLC'))

# 导入VLC推流模块
try:
    from streamer import RTSPStreamer
    from config import DEFAULT_CONFIG
    VLC_AVAILABLE = True
    logging.info("✅ VLC推流模块加载成功")
except ImportError as e:
    VLC_AVAILABLE = False
    logging.warning(f"⚠️ VLC推流模块加载失败: {e}")

# 配置日志记录
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logging.info("--- V4 后端代码已成功加载，WebRTC + VLC推流整合系统 ---")

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

# VLC推流器实例（全局单例）
vlc_streamer = None
if VLC_AVAILABLE:
    vlc_streamer = RTSPStreamer()
    logging.info("🎥 VLC推流器实例创建成功")


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

async def mock_ai_analysis_task():
    """
    模拟AI分析任务的后台任务
    定期发送模拟的AI分析结果
    """
    try:
        while True:
            await asyncio.sleep(5)  # 每5秒执行一次
            
            # 模拟AI分析结果
            mock_result = {
                'type': 'ai_analysis',
                'timestamp': asyncio.get_event_loop().time(),
                'data': {
                    'face_detection': {
                        'detected': random.choice([True, False]),
                        'confidence': round(random.uniform(0.7, 0.95), 2)
                    },
                    'emotion': {
                        'emotion': random.choice(['happy', 'neutral', 'surprised', 'focused']),
                        'confidence': round(random.uniform(0.6, 0.9), 2)
                    }
                }
            }
            
            # 向所有连接的客户端发送模拟结果
            if rooms:
                await sio.emit('ai_analysis_result', mock_result)
                logging.info(f"发送模拟AI分析结果: {mock_result['data']}")
                
    except asyncio.CancelledError:
        logging.info("AI分析任务已停止")
    except Exception as e:
        logging.error(f"AI分析任务错误: {e}")

# 轻量方案：接收前端关键点并返回占位翻译结果
@sio.on('analysis_keypoints')
async def handle_analysis_keypoints(sid, payload):
    """
    接收前端发送的手部关键点数据并返回占位的手语翻译结果。
    期望payload格式示例：
    {
      "source": "local" | "remote",
      "fps": 5,
      "hands": [
        {"landmarks": [[x,y,z,score], ...], "handedness": "Left|Right"},
        ...
      ],
      "timestamp": 1234567890
    }
    """
    try:
        hands = (payload or {}).get('hands', [])
        source = (payload or {}).get('source', 'local')

        # 非常简化的占位逻辑：根据是否检测到手以及关键点数量，给出伪翻译
        detected = len(hands) > 0
        keypoint_count = sum(len(h.get('landmarks', [])) for h in hands)

        if detected and keypoint_count >= 21:
            text = '检测到手势，正在翻译…'
            confidence = 0.75
        elif detected:
            text = '检测到手部，但关键点不足'
            confidence = 0.55
        else:
            text = '未检测到明显手势'
            confidence = 0.2

        result = {
            'source': source,
            'text': text,
            'confidence': confidence,
            'timestamp': payload.get('timestamp') if isinstance(payload, dict) else None
        }

        # 仅回发给发送方（同一sid），避免跨房混淆
        await sio.emit('sign_language_translation', result, room=sid)
        logging.info(f"返回手语占位翻译给 {sid}: {result}")
    except Exception as e:
        logging.error(f"处理关键点分析失败: {e}")
        await sio.emit('sign_language_translation', {
            'source': 'unknown',
            'text': '后端处理错误',
            'confidence': 0.0
        }, room=sid)

# 新增：接收序列关键点并返回占位的序列翻译结果
@sio.on('analysis_keypoints_sequence')
async def handle_analysis_keypoints_sequence(sid, payload):
    """
    接收前端打包的关键点序列 frames 并进行占位翻译。
    期望payload格式示例：
    {
      "source": "local",
      "fps": 5,
      "frames": [
        {"hands": [...], "timestamp": 123},
        ...
      ],
      "started_at": 123456,
      "ended_at": 123789
    }
    """
    try:
      frames = (payload or {}).get('frames', [])
      source = (payload or {}).get('source', 'local')
      fps = (payload or {}).get('fps', 5)
      started_at = (payload or {}).get('started_at')
      ended_at = (payload or {}).get('ended_at')

      length = len(frames)
      duration_ms = (ended_at - started_at) if (started_at and ended_at) else 0
      # 简单度量：总关键点数量与帧数
      total_keypoints = 0
      hand_frames = 0
      for f in frames:
        hands = (f or {}).get('hands', [])
        if hands:
          hand_frames += 1
          total_keypoints += sum(len(h.get('landmarks', [])) for h in hands)

      # 占位翻译策略：帧数≥10且有连续手帧，提升置信度
      if hand_frames >= max(2, int(0.4 * length)) and length >= max(5, int(1.5 * fps)):
        text = '检测到连续手势序列，正在翻译…'
        confidence = 0.82
      elif hand_frames > 0:
        text = '检测到零散手势序列'
        confidence = 0.6
      else:
        text = '序列中未检测到有效手势'
        confidence = 0.25

      result = {
        'source': source,
        'text': text,
        'confidence': confidence,
        'timestamp': ended_at or started_at or None,
        'meta': {
          'frames': length,
          'duration_ms': duration_ms,
          'fps': fps,
          'hand_frames': hand_frames,
          'total_keypoints': total_keypoints
        }
      }

      await sio.emit('sign_language_translation', result, room=sid)
      logging.info(f"返回序列占位翻译给 {sid}: {result}")
    except Exception as e:
      logging.error(f"处理关键点序列失败: {e}")
      await sio.emit('sign_language_translation', {
        'source': 'unknown',
        'text': '后端序列处理错误',
        'confidence': 0.0
      }, room=sid)

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

# ==================== VLC推流控制API ====================

@fastapi_app.get("/api/vlc/status")
async def get_vlc_status():
    """获取VLC推流状态"""
    if not VLC_AVAILABLE or not vlc_streamer:
        raise HTTPException(status_code=503, detail="VLC推流模块不可用")
    
    try:
        status = vlc_streamer.get_status()
        return JSONResponse(content={
            "success": True,
            "data": status
        })
    except Exception as e:
        logging.error(f"获取VLC状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取状态失败: {str(e)}")

@fastapi_app.post("/api/vlc/start")
async def start_vlc_stream(config: dict = None):
    """启动VLC推流"""
    if not VLC_AVAILABLE or not vlc_streamer:
        raise HTTPException(status_code=503, detail="VLC推流模块不可用")
    
    try:
        # 使用传入的配置或默认配置
        stream_config = config or DEFAULT_CONFIG
        success = vlc_streamer.start_stream(stream_config)
        
        if success:
            # 通知所有连接的客户端推流已启动
            await sio.emit('vlc_stream_started', {
                'status': 'started',
                'config': stream_config,
                'timestamp': asyncio.get_event_loop().time()
            })
            
            return JSONResponse(content={
                "success": True,
                "message": "推流启动成功",
                "config": stream_config
            })
        else:
            raise HTTPException(status_code=500, detail="推流启动失败")
            
    except Exception as e:
        logging.error(f"启动VLC推流失败: {e}")
        raise HTTPException(status_code=500, detail=f"启动失败: {str(e)}")

@fastapi_app.post("/api/vlc/stop")
async def stop_vlc_stream():
    """停止VLC推流"""
    if not VLC_AVAILABLE or not vlc_streamer:
        raise HTTPException(status_code=503, detail="VLC推流模块不可用")
    
    try:
        success = vlc_streamer.stop_stream()
        
        if success:
            # 通知所有连接的客户端推流已停止
            await sio.emit('vlc_stream_stopped', {
                'status': 'stopped',
                'timestamp': asyncio.get_event_loop().time()
            })
            
            return JSONResponse(content={
                "success": True,
                "message": "推流停止成功"
            })
        else:
            return JSONResponse(content={
                "success": False,
                "message": "推流停止失败或未在运行"
            })
            
    except Exception as e:
        logging.error(f"停止VLC推流失败: {e}")
        raise HTTPException(status_code=500, detail=f"停止失败: {str(e)}")

@fastapi_app.post("/api/vlc/config")
async def update_vlc_config(new_config: dict):
    """更新VLC推流配置"""
    if not VLC_AVAILABLE or not vlc_streamer:
        raise HTTPException(status_code=503, detail="VLC推流模块不可用")
    
    try:
        # 验证配置参数
        required_fields = ['input_source', 'rtsp_url']
        for field in required_fields:
            if field not in new_config:
                raise HTTPException(status_code=400, detail=f"缺少必需字段: {field}")
        
        # 更新配置
        vlc_streamer.update_config(new_config)
        
        return JSONResponse(content={
            "success": True,
            "message": "配置更新成功",
            "config": new_config
        })
        
    except Exception as e:
        logging.error(f"更新VLC配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"配置更新失败: {str(e)}")

@fastapi_app.get("/api/vlc/logs")
async def get_vlc_logs(lines: int = 50):
    """获取VLC推流日志"""
    if not VLC_AVAILABLE or not vlc_streamer:
        raise HTTPException(status_code=503, detail="VLC推流模块不可用")
    
    try:
        logs = vlc_streamer.get_logs(lines)
        return JSONResponse(content={
            "success": True,
            "data": {
                "logs": logs,
                "lines": len(logs)
            }
        })
    except Exception as e:
        logging.error(f"获取VLC日志失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取日志失败: {str(e)}")

# ==================== Socket.IO VLC事件 ====================

@sio.on('vlc_get_status')
async def handle_vlc_get_status(sid):
    """Socket.IO: 获取VLC状态"""
    if not VLC_AVAILABLE or not vlc_streamer:
        await sio.emit('vlc_status_error', {
            'error': 'VLC推流模块不可用'
        }, room=sid)
        return
    
    try:
        status = vlc_streamer.get_status()
        await sio.emit('vlc_status_update', status, room=sid)
    except Exception as e:
        await sio.emit('vlc_status_error', {
            'error': f'获取状态失败: {str(e)}'
        }, room=sid)

@sio.on('vlc_start_stream')
async def handle_vlc_start_stream(sid, config=None):
    """Socket.IO: 启动VLC推流"""
    if not VLC_AVAILABLE or not vlc_streamer:
        await sio.emit('vlc_stream_error', {
            'error': 'VLC推流模块不可用'
        }, room=sid)
        return
    
    try:
        stream_config = config or DEFAULT_CONFIG
        success = vlc_streamer.start_stream(stream_config)
        
        if success:
            # 广播给所有客户端
            await sio.emit('vlc_stream_started', {
                'status': 'started',
                'config': stream_config,
                'timestamp': asyncio.get_event_loop().time()
            })
        else:
            await sio.emit('vlc_stream_error', {
                'error': '推流启动失败'
            }, room=sid)
            
    except Exception as e:
        await sio.emit('vlc_stream_error', {
            'error': f'启动失败: {str(e)}'
        }, room=sid)

@sio.on('vlc_stop_stream')
async def handle_vlc_stop_stream(sid):
    """Socket.IO: 停止VLC推流"""
    if not VLC_AVAILABLE or not vlc_streamer:
        await sio.emit('vlc_stream_error', {
            'error': 'VLC推流模块不可用'
        }, room=sid)
        return
    
    try:
        success = vlc_streamer.stop_stream()
        
        if success:
            # 广播给所有客户端
            await sio.emit('vlc_stream_stopped', {
                'status': 'stopped',
                'timestamp': asyncio.get_event_loop().time()
            })
        else:
            await sio.emit('vlc_stream_error', {
                'error': '推流停止失败或未在运行'
            }, room=sid)
            
    except Exception as e:
        await sio.emit('vlc_stream_error', {
            'error': f'停止失败: {str(e)}'
        }, room=sid)

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8000)