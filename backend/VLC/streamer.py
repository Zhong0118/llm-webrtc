# streamer.py
import subprocess
import threading
import time
import sys


class RTSPStreamer:
    def __init__(self):
        self.process = None
        self.thread = None
        self.running = False
        self.log = ["系统启动，等待指令..."]
        self.start_timestamps = {}

        # 推流参数（可动态更新）
        self.resolution = "640x480"
        self.fps = 30
        self.crf = 28
        self.preset = "ultrafast"
        self.input_source = "Integrated Camera"  # 默认摄像头名称
        self.rtsp_url = "rtsp://127.0.0.1:8554/mystream"
        self.ffmpeg_path = "ffmpeg"  # 默认在 PATH 中

        # 锁，防止并发操作
        self._lock = threading.Lock()

    def configure(self, **kwargs):
        """
        动态配置推流参数，支持部分更新
        示例：configure(resolution="1280x720", fps=25)
        """
        valid_keys = {
            'resolution', 'fps', 'crf', 'preset',
            'input_source', 'rtsp_url', 'ffmpeg_path'
        }
        updated = []
        for k, v in kwargs.items():
            if k in valid_keys and v is not None:
                old_val = getattr(self, k)
                setattr(self, k, v)
                if old_val != v:
                    updated.append(f"{k}='{old_val}' → '{v}'")
        if updated:
            self.log.append("参数更新: " + ", ".join(updated))
            print("⚙️ 参数已更新:", ", ".join(updated))
        else:
            print("⚙️ 无有效参数更新")

    def build_ffmpeg_cmd(self):
        """构建 ffmpeg 推流命令"""
        cmd = [self.ffmpeg_path]

        if self._is_camera_source(self.input_source):
            # 使用 dshow 采集摄像头（Windows）
            cmd += [
                '-f', 'dshow',
                '-framerate', str(self.fps),
                '-video_size', self.resolution,
                '-i', f'video={self.input_source}'
            ]
            print(f"📹 正在使用摄像头设备: {self.input_source}")
        else:
            # 文件或网络流输入
            cmd += ['-re', '-i', self.input_source]
            print(f"📁 正在使用输入源: {self.input_source}")

        # 视频编码参数
        cmd += [
            '-c:v', 'libx264',
            '-preset', self.preset,
            '-tune', 'zerolatency',
            '-crf', str(self.crf),
            '-g', '50'  # GOP 大小，影响关键帧间隔
        ]

        # 强制输出分辨率和帧率
        if self.resolution:
            cmd += ['-s', self.resolution]
        if self.fps:
            cmd += ['-r', str(self.fps)]

        # RTSP 输出设置
        cmd += [
            '-f', 'rtsp',
            '-rtsp_transport', 'tcp',
            self.rtsp_url
        ]

        return cmd

    def _run(self):
        """子线程运行推流逻辑"""
        while self.running:
            try:
                cmd = self.build_ffmpeg_cmd()
                print("🚀 执行推流命令:", " ".join(cmd))
                self.log.append("启动推流: " + " ".join(cmd[:5]) + " ...")  # 避免日志过长

                # 重置时间戳
                self.start_timestamps = {
                    'start': time.time(),
                    'first_frame': None
                }

                self.process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
                )

                # 读取 FFmpeg 输出
                while self.running and self.process.poll() is None:
                    line = self.process.stderr.readline().decode('utf-8', errors='ignore').strip()
                    if line:
                        print(f"[FFMPEG] {line}")
                        if any(err in line.lower() for err in ['error', 'failed', 'cannot']):
                            self.log.append(f"❌ FFmpeg 错误: {line}")

                        # 检测首帧输出（更精确的关键词）
                        if (self.start_timestamps['first_frame'] is None and
                            any(kw in line for kw in ['frame=0', 'Output', 'Starting', 'rtsp'])):
                            self.start_timestamps['first_frame'] = time.time()
                            delay_ms = (self.start_timestamps['first_frame'] - self.start_timestamps['start']) * 1000
                            print(f"✅ 首帧检测成功，启动延迟 ≈ {delay_ms:.1f} ms")
                            self.log.append(f"✅ 推流稳定，首帧延迟: {delay_ms:.1f} ms")

                try:
                    ret = self.process.wait(timeout=3)
                    print(f"🔚 FFmpeg 退出，返回码: {ret}")
                except subprocess.TimeoutExpired:
                    print("⚠️ FFmpeg 未响应，强制终止...")
                    self.process.kill()
                    self.process.wait()

                if self.running:
                    print("⚠️ 推流中断，5秒后重试...")
                    self.log.append("⚠️ 推流中断，5秒后重试...")
                    time.sleep(5)
                else:
                    print("⏹️ 推流已停止")
                    self.log.append("⏹️ 推流已停止")

            except Exception as e:
                error_msg = f"❌ 推流异常: {e}"
                print(error_msg)
                self.log.append(error_msg)
                if self.running:
                    time.sleep(5)

    def start(self):
        """启动推流（线程安全）"""
        with self._lock:
            if self.running:
                return "推流已在运行"
            if not all([self.resolution, self.fps, self.crf, self.preset, self.input_source, self.rtsp_url]):
                return "推流参数未配置，请先设置"

            self.running = True
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()
            return "推流启动中..."

    def stop(self):
        """停止推流（线程安全）"""
        with self._lock:
            if not self.running:
                return "推流未在运行"
            self.running = False
            if self.process:
                try:
                    print("🛑 正在终止 FFmpeg 进程...")
                    self.process.terminate()
                    self.process.wait(timeout=3)
                    if self.process.poll() is None:
                        print("⚠️ 进程未响应，强制杀死...")
                        self.process.kill()
                        self.process.wait()
                except Exception as e:
                    print(f"❌ 终止失败: {e}")
                finally:
                    self.process = None
            return "推流已停止"

    def restart(self):
        """安全重启推流（用于参数更新后）"""
        with self._lock:
            was_running = self.running
            if was_running:
                print("🔄 正在重启推流以应用新参数...")
                self.stop()
                time.sleep(1)  # 确保旧进程完全退出
            result = self.start()
            return "推流已重启" if was_running else result

    def is_running(self):
        return self.running

    def get_log(self):
        return self.log[-20:]

    def get_status(self):
        """供前端 API 调用的状态信息"""
        return {
            "running": self.is_running(),
            "resolution": self.resolution,
            "fps": self.fps,
            "crf": self.crf,
            "preset": self.preset,
            "input_source": self.input_source,
            "rtsp_url": self.rtsp_url,
            "log": self.get_log(),
            "delay_info": self.get_delay_info()
        }

    def get_delay_info(self):
        """返回延迟信息"""
        if not self.start_timestamps or 'start' not in self.start_timestamps:
            return {"total": 0}
        if self.start_timestamps.get('first_frame') is None:
            return {"total": 0}
        total_delay_ms = (self.start_timestamps['first_frame'] - self.start_timestamps['start']) * 1000
        return {"total": round(total_delay_ms, 2)}

    def _is_camera_source(self, source):
        """判断是否为摄像头源"""
        if not source:
            return False
        source_lower = source.lower()
        camera_keywords = [
            'camera', 'cam', 'video', '集成', 'usb', 'webcam',
            'hp camera', 'hd camera', 'integrated camera', 'front', 'back'
        ]
        return any(kw in source_lower for kw in camera_keywords)