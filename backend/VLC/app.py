# app.py
from flask import Flask, render_template, jsonify, request

# 从 config 导入的是默认值，不是运行时变量
from config import INPUT_SOURCE, RTSP_URL, STREAM_RESOLUTION, STREAM_FPS, STREAM_CRF, STREAM_PRESET, FFMPEG_PATH
import threading
import time

# 导入推流器
from streamer import RTSPStreamer

app = Flask(__name__)

# 全局推流器实例
streamer = RTSPStreamer()

# 当前运行参数（可动态修改）
current_config = {
    'resolution': STREAM_RESOLUTION,
    'fps': STREAM_FPS,
    'crf': STREAM_CRF,
    'preset': STREAM_PRESET
}

# 状态记录
status_log = ["系统启动，等待指令..."]

def log_status(msg):
    global status_log
    timestamp = time.strftime("%H:%M:%S")
    status_log.append(f"[{timestamp}] {msg}")
    status_log = status_log[-100:]  # 保留最近100条


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/status')
def api_status():
    return jsonify({
        'running': streamer.is_running(),
        'rtsp_url': RTSP_URL,
        'log': status_log,
        'resolution': current_config['resolution'],
        'fps': current_config['fps'],
        'crf': current_config['crf'],
        'preset': current_config['preset'],
        'delay_info': streamer.get_delay_info()
    })


@app.route('/api/control', methods=['POST'])
def api_control():
    action = request.json.get('action')
    result = "未知指令"

    if action == 'start':
        # 使用 current_config 配置 streamer
        streamer.configure(
            resolution=current_config['resolution'],
            fps=current_config['fps'],
            crf=current_config['crf'],
            preset=current_config['preset'],
            input_source=INPUT_SOURCE,
            rtsp_url=RTSP_URL,
            ffmpeg_path=FFMPEG_PATH
        )
        result = streamer.start()
        log_status("启动推流: " + result)

    elif action == 'stop':
        result = streamer.stop()
        log_status("停止推流: " + result)

    elif action == 'set_params':
        # 获取新参数
        resolution = request.json.get('resolution')
        fps = request.json.get('fps')
        crf = request.json.get('crf')
        preset = request.json.get('preset')

        updated = False
        if resolution:
            current_config['resolution'] = resolution
            log_status(f"✅ 分辨率已设置为: {resolution}")
            updated = True
        if fps is not None:
            current_config['fps'] = int(fps)
            log_status(f"✅ 帧率已设置为: {fps} fps")
            updated = True
        if crf is not None:
            current_config['crf'] = int(crf)
            log_status(f"✅ CRF 已设置为: {crf}")
            updated = True
        if preset:
            current_config['preset'] = preset
            log_status(f"✅ 编码预设已设置为: {preset}")
            updated = True

        # 如果正在运行，重启推流
        if streamer.is_running() and updated:
            streamer.stop()
            time.sleep(1)
            streamer.configure(
                resolution=current_config['resolution'],
                fps=current_config['fps'],
                crf=current_config['crf'],
                preset=current_config['preset'],
                input_source=INPUT_SOURCE,
                rtsp_url=RTSP_URL,
                ffmpeg_path=FFMPEG_PATH
            )
            streamer.start()
            result = "参数已更新并重启推流"
        else:
            result = "参数已保存，待启动时生效"

    return jsonify({'result': result})


if __name__ == '__main__':
    print("🌍 启动 Web 管理界面: http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, threaded=True)