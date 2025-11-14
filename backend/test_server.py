import requests
import socketio
import time
import urllib3
import threading

# 禁用因自签名证书而产生的 InsecureRequestWarning
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 您的后端地址
BASE_URL = 'https://localhost:33335'

# --- 测试 1：测试根 API ---
def test_api_root():
    print("--- [测试 1: 正在测试 API (GET /)] ---")
    try:
        response = requests.get(BASE_URL + '/', verify=False, timeout=5)
        if response.status_code == 200 and response.json().get('status') == 'ok':
            print("✅ API (/) 测试成功！")
            print(f"    内容: {response.json()}")
        else:
            print(f"❌ API (/) 测试失败。状态码: {response.status_code}")
    except Exception as e:
        print(f"❌ API (/) 测试连接失败: {e}")
    print("-" * 40 + "\n")

# --- 测试 2：测试 RTSP 状态 API ---
def test_api_rtsp_status():
    print("--- [测试 2: 正在测试 API (GET /api/rtsp/status)] ---")
    try:
        # 这个 API 路径在您的 main_simple.py 中定义
        response = requests.get(BASE_URL + '/api/rtsp/status', verify=False, timeout=5)
        if response.status_code == 200 and 'running' in response.json():
            print("✅ API (/api/rtsp/status) 测试成功！")
            print(f"    推流器状态: {'运行中' if response.json()['running'] else '已停止'}")
        else:
            print(f"❌ API (/api/rtsp/status) 测试失败。状态码: {response.status_code}")
            print(f"    内容: {response.text}")
    except Exception as e:
        print(f"❌ API (/api/rtsp/status) 测试连接失败: {e}")
    print("-" * 40 + "\n")

# --- 辅助函数：创建和管理 Socket.IO 客户端 ---
def run_socket_test(namespace, test_name):
    """
    通用的 Socket.IO 连接测试函数
    """
    print(f"--- [测试 {test_name}: 正在测试 Socket.IO ({namespace})] ---")
    
    # 使用 threading.Event 来等待连接成功
    connect_event = threading.Event()
    connect_error_data = None
    
    sio = socketio.Client(ssl_verify=False, logger=False, engineio_logger=False)
    
    # --- 关键修复：为 *特定命名空间* 注册事件 ---
    @sio.on('connect', namespace=namespace)
    def on_connect():
        print(f"✅ Socket.IO ({namespace}) 测试成功：已连接！")
        connect_event.set() # 发送“已连接”信号

    @sio.on('connect_error', namespace=namespace)
    def on_connect_error(data):
        nonlocal connect_error_data
        connect_error_data = data
        print(f"❌ Socket.IO ({namespace}) 测试失败：连接错误。")
        print(f"    错误详情: {data}")
        connect_event.set() # 同样发送信号，以便主线程退出

    @sio.on('rtsp_status_update', namespace='/streamer')
    def on_rtsp_status(data):
        # streamer 命名空间会在连接时自动发送状态
        print(f"    ℹ️  ({namespace}) 收到状态更新: {'运行中' if data.get('running') else '已停止'}")

    try:
        print(f"    正在尝试连接到 {BASE_URL} (命名空间: {namespace})...")
        sio.connect(BASE_URL, namespaces=[namespace], transports=['websocket'])
        
        # 等待最多 5 秒钟，看 on_connect 或 on_connect_error 是否被触发
        connected = connect_event.wait(timeout=5)
        
        if not connected and not connect_error_data:
            print(f"❌ Socket.IO ({namespace}) 测试失败：连接超时（5秒）。")
            
    except socketio.exceptions.ConnectionError as e:
        print(f"❌ Socket.IO ({namespace}) 测试失败：连接被拒绝或超时。")
        print(f"    错误详情: {e}")
    except Exception as e:
        print(f"❌ Socket.IO ({namespace}) 测试期间发生未知错误: {e}")
    finally:
        if sio.connected:
            sio.disconnect()
            print(f"    ℹ️  ({namespace}) 已断开连接。")
    print("-" * 40 + "\n")


if __name__ == "__main__":
    print(f"*** 开始全面测试后端服务器: {BASE_URL} ***\n")
    
    # 1. 测试 API
    test_api_root()
    time.sleep(1)
    test_api_rtsp_status()
    time.sleep(1)
    
    # 2. 测试 P2P 命名空间
    run_socket_test(namespace='/p2p', test_name="3 (P2P)")
    time.sleep(1)
    
    # 3. 测试 Streamer 命名空间
    run_socket_test(namespace='/streamer', test_name="4 (Streamer)")
    time.sleep(1)
    
    # 4. 测试 Server Push 命名空间
    run_socket_test(namespace='/server_push', test_name="5 (Server Push)")
    time.sleep(1)

    print("*** 所有测试完成 ***")