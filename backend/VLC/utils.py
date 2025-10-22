# utils.py
import subprocess
import os

def is_camera_source(source):
    """
    判断输入源是否为本地摄像头
    :param source: 输入源名称，如 "Integrated Camera"
    :return: bool
    """
    if not source:
        return False
    source_lower = source.lower()
    camera_indicators = [
        'camera',
        'cam',
        'video',
        '集成',
        'usb',
        'webcam',
        'hp camera',
        'hd camera'
    ]
    return any(indicator in source_lower for indicator in camera_indicators)

def check_ffmpeg():
    """检查 ffmpeg 是否可用"""
    try:
        result = subprocess.run(
            ['ffmpeg', '-version'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        if result.returncode == 0:
            print("✅ ffmpeg 可用")
            return True
        else:
            print("❌ ffmpeg 不可用，请安装并加入 PATH")
            return False
    except FileNotFoundError:
        print("❌ 未找到 ffmpeg，请安装并加入 PATH")
        return False


# utils.py
def is_camera_source(source):
    """
    判断输入源是否为本地摄像头设备（Windows dshow）
    """
    if not source:
        return False
    source_lower = source.lower()

    # 常见摄像头关键词
    camera_keywords = [
        'camera',
        'cam',
        'video',
        '集成',
        'usb',
        'webcam',
        'hp camera',
        'hd camera',
        'integrated camera',  # 明确包含你的设备名
        'front camera',
        'back camera'
    ]

    return any(keyword in source_lower for keyword in camera_keywords)
