# config.py
INPUT_SOURCE = "Integrated Camera"        # 摄像头名称（不含 video=）
RTSP_URL = "rtsp://localhost:8554/mystream"

# 可动态修改的参数
STREAM_RESOLUTION = "640x480"
STREAM_FPS = 30
STREAM_CRF = 28
STREAM_PRESET = "ultrafast"

FFMPEG_PATH = "ffmpeg"  # 或类似路径

# 延迟统计开关（用于调试）
ENABLE_DELAY_LOGGING = True

# 默认配置字典
DEFAULT_CONFIG = {
    "input_source": INPUT_SOURCE,
    "rtsp_url": RTSP_URL,
    "resolution": STREAM_RESOLUTION,
    "fps": STREAM_FPS,
    "crf": STREAM_CRF,
    "preset": STREAM_PRESET,
    "ffmpeg_path": FFMPEG_PATH,
    "enable_delay_logging": ENABLE_DELAY_LOGGING
}