# streamer.py
import subprocess
import threading
import time
import sys
import os
import asyncio # Import asyncio
from collections import deque
import signal

# --- [MODIFICATION 1]: Import socketio for type hinting ---
import socketio

try:
    from .utils import is_camera_source
except ImportError:
    from utils import is_camera_source

class RTSPStreamer:
    # --- [MODIFICATION 2]: Accept sio_server and namespace in __init__ ---
    def __init__(self, sio_server: socketio.AsyncServer = None, namespace: str = None, log_limit=100):
        """
        Initialize RTSP Streamer.
        :param sio_server: Optional Socket.IO AsyncServer instance for real-time updates.
        :param namespace: Optional Socket.IO namespace for emissions.
        :param log_limit: Max log entries to keep.
        """
        self.process = None
        self.thread = None
        self._running = False
        self._lock = threading.Lock()
        self.log = deque(maxlen=log_limit)
        self.start_timestamps = {}

        # Store sio and namespace (but don't use them during init)
        self.sio = None  # Will be set later
        self.namespace = namespace
        self._pending_sio = sio_server  # Store for later
        
        # --- [FIX 1]: Add placeholder for the main event loop ---
        self.main_loop = None # Will store the main asyncio loop

        # Default config (can be updated via configure)
        self.resolution = "640x480"
        self.fps = 30
        self.crf = 28
        self.preset = "ultrafast"
        self.input_source = "Integrated Camera"
        self.rtsp_url = "rtsp://127.0.0.1:8554/mystream"
        self.ffmpeg_path = "ffmpeg"

        # Log without Socket.IO emission during init
        timestamp = time.strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] 系统初始化，等待指令..."
        self.log.append(log_entry)
        print(log_entry)

    # --- [FIX 2]: Capture the main event loop when socketio is enabled ---
    def enable_socketio(self):
        """Enable Socket.IO after event loop is running and store the loop."""
        if self._pending_sio:
            self.sio = self._pending_sio
            self._pending_sio = None
            try:
                # Capture the main event loop (this runs in the main thread)
                self.main_loop = asyncio.get_running_loop() 
            except RuntimeError as e:
                print(f"❌ streamer.py: Could not get running event loop in enable_socketio: {e}")
                self.main_loop = None

    async def _emit_status_update(self):
        """Safely emits the current status via Socket.IO if available."""
        if self.sio:
            try:
                status_data = self.get_status()
                await self.sio.emit('rtsp_status_update', status_data, namespace=self.namespace)
            except Exception as e:
                print(f"Error emitting status update via Socket.IO: {e}")

    async def _emit_log_update(self, log_entry):
        """Safely emits a new log entry via Socket.IO if available."""
        if self.sio:
            try:
                await self.sio.emit('rtsp_log_update', {'log_entry': log_entry}, namespace=self.namespace)
            except Exception as e:
                print(f"Error emitting log update via Socket.IO: {e}")

    # --- [FIX 3]: Use self.main_loop (no longer call get_running_loop) ---
    def _log(self, msg):
        """Internal method to add log entry and trigger Socket.IO emission."""
        timestamp = time.strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {msg}"
        self.log.append(log_entry)
        print(log_entry) # Keep console logging

        # Schedule the async emit function to run in the main event loop
        if self.sio and self.main_loop: # Check if loop was captured
            try:
                # Use run_coroutine_threadsafe for thread safety
                asyncio.run_coroutine_threadsafe(self._emit_log_update(log_entry), self.main_loop)
            except Exception as e:
                print(f"Error scheduling log emission: {e}")


    def configure(self, **kwargs):
        """Dynamically configure streaming parameters."""
        updated = False
        with self._lock:
            # ... (validation logic remains the same) ...
            valid_keys = {
                'resolution', 'fps', 'crf', 'preset',
                'input_source', 'rtsp_url', 'ffmpeg_path'
            }
            updated_params = []
            for key, value in kwargs.items():
                if key in valid_keys and value is not None:
                    old_value = getattr(self, key)
                    if key in ['fps', 'crf']:
                        try: value = int(value)
                        except (ValueError, TypeError): continue
                    if old_value != value:
                        setattr(self, key, value)
                        updated_params.append(f"{key}='{old_value}'->'{value}'")

            if updated_params:
                self._log("⚙️ 参数已更新: " + ", ".join(updated_params))
                updated = True # Set flag if updated
            else:
                self._log("⚙️ 未提供有效参数更新或参数值未改变。")

        # --- [FIX 4]: Use self.main_loop ---
        if updated and self.sio and self.main_loop:
             asyncio.run_coroutine_threadsafe(self._emit_status_update(), self.main_loop)
        return updated

    def build_ffmpeg_cmd(self):
        # ... (remains the same) ...
        cmd = [self.ffmpeg_path]
        is_cam = is_camera_source(self.input_source)
        if is_cam:
            cmd += ['-f', 'dshow', '-framerate', str(self.fps), '-video_size', self.resolution, '-i', f'video={self.input_source}']
        else:
            cmd += ['-re', '-i', self.input_source]
        cmd += ['-c:v', 'libx264', '-preset', self.preset, '-tune', 'zerolatency', '-crf', str(self.crf), '-g', '50', '-s', self.resolution, '-r', str(self.fps), '-f', 'rtsp', '-rtsp_transport', 'tcp', self.rtsp_url]
        return cmd


    def _run(self):
        """Background thread for running FFmpeg."""
        while self._running:
            process = None
            should_emit_stopped = False # Flag to emit stopped status *after* loop breaks
            try:
                cmd = self.build_ffmpeg_cmd()
                self._log("🚀 执行推流命令...") # Simplified log
                self.start_timestamps = { 'start': time.time(), 'first_frame': None }

                process = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, encoding='utf-8', errors='ignore',
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
                )
                self.process = process

                stream_stable_logged = False # Flag to log stability only once per run
                for line in iter(process.stderr.readline, ''):
                    if not self._running: break
                    line = line.strip()
                    if line:
                        print(f"[FFMPEG] {line}")
                        is_error = any(err in line.lower() for err in ['error', 'failed', 'cannot open', 'invalid', 'connection refused'])
                        if is_error:
                            self._log(f"❌ FFmpeg 错误: {line}")
                            # --- [FIX 5]: Use self.main_loop ---
                            if self.sio and self.main_loop:
                                asyncio.run_coroutine_threadsafe(
                                    self.sio.emit('rtsp_error', {'message': line}, namespace=self.namespace),
                                    self.main_loop
                                )
                        elif ('frame=' in line or 'fps=' in line) and not stream_stable_logged:
                            if self.start_timestamps.get('first_frame') is None:
                                self.start_timestamps['first_frame'] = time.time()
                                delay_ms = (self.start_timestamps['first_frame'] - self.start_timestamps['start']) * 1000
                                self._log(f"✅ 推流稳定，首帧延迟 ≈ {delay_ms:.1f} ms")
                                stream_stable_logged = True
                                # --- [FIX 6]: Use self.main_loop (This is where it crashed) ---
                                if self.sio and self.main_loop:
                                    asyncio.run_coroutine_threadsafe(self._emit_status_update(), self.main_loop)

                process.wait()
                return_code = process.poll()
                self._log(f"🔚 FFmpeg 进程退出，返回码: {return_code}")
                should_emit_stopped = True # Process exited normally or with error

            except FileNotFoundError:
                 self._log(f"❌ 错误: 未找到 ffmpeg 命令 ('{self.ffmpeg_path}')。")
                 self._running = False
                 should_emit_stopped = True
                 break # Exit while loop
            except Exception as e:
                self._log(f"❌ 推流线程异常: {e}")
                should_emit_stopped = True
            finally:
                if process and process.poll() is None:
                    try: process.terminate(); process.wait(timeout=1); process.kill()
                    except: pass
                self.process = None
                # --- [FIX 7]: Use self.main_loop ---
                if should_emit_stopped and self.sio and self.main_loop:
                     # Ensure the internal state is updated before emitting
                     self._running = False # Explicitly set running to false here
                     asyncio.run_coroutine_threadsafe(self._emit_status_update(), self.main_loop)


            if self._running: # Only retry if _running is still True (i.e., not stopped externally)
                self._log("⚠️ 推流意外中断，将在 5 秒后尝试重启...")
                time.sleep(5)

        self._log("⏹️ 推流线程已停止。")
        # --- [FIX 8]: Use self.main_loop ---
        if self.sio and self.main_loop:
             # Ensure internal state reflects stopped status
             self._running = False
             asyncio.run_coroutine_threadsafe(self._emit_status_update(), self.main_loop)


    def start(self):
        """Starts the streaming thread (thread-safe)."""
        with self._lock:
            if self._running:
                self._log("ℹ️ 推流已在运行中。")
                return "推流已在运行"
            if not all([self.resolution, self.fps, self.crf, self.preset, self.input_source, self.rtsp_url]):
                 self._log("⚠️ 启动失败：推流参数不完整。")
                 return "启动失败：推流参数不完整"

            self._running = True
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()
            self._log("🚀 推流启动指令已发送...")
            
            # --- [FIX 9]: Use self.main_loop ---
            if self.sio and self.main_loop:
                asyncio.run_coroutine_threadsafe(self._emit_status_update(), self.main_loop) # is_running() will return True now
            return "推流启动中..."

    def stop(self):
        """Stops the streaming thread (thread-safe)."""
        with self._lock:
            if not self._running and not self.process:
                self._log("ℹ️ 推流当前未运行。")
                return "推流未在运行"

            self._log("🛑 正在发送停止指令...")
            self._running = False # Signal the thread to stop

            process_to_stop = self.process
            stop_successful = True # Assume success initially
            if process_to_stop:
                try:
                    # --- 【新修复 3】: 修正这里的逻辑 ---
                    if sys.platform == "win32":
                        # 使用 signal.CTRL_BREAK_EVENT
                        process_to_stop.send_signal(signal.CTRL_BREAK_EVENT)
                    else:
                        # Linux/Mac 使用 terminate (SIGTERM)
                        process_to_stop.terminate()
                    # --- 修复结束 ---
                        
                    process_to_stop.wait(timeout=5)
                    self._log("✅ FFmpeg 进程已优雅退出。")
                except subprocess.TimeoutExpired:
                    self._log("⚠️ FFmpeg 进程未在5秒内响应，强制结束...")
                    process_to_stop.kill(); process_to_stop.wait()
                    self._log("强制结束完成。")
                except Exception as e:
                    self._log(f"❌ 终止 FFmpeg 进程时发生错误: {e}")
                    stop_successful = False # Mark as potentially failed
                finally:
                    self.process = None

            if self.thread and self.thread.is_alive():
                self.thread.join(timeout=2)

            self._log("⏹️ 推流已确认停止。")
             
            if self.sio and self.main_loop:
                 asyncio.run_coroutine_threadsafe(self._emit_status_update(), self.main_loop)
            return "推流已停止" if stop_successful else "推流停止时遇到问题"


    def restart(self):
        """Safely restarts the stream."""
        with self._lock:
            if self._running:
                self._log("🔄 正在重启推流...")
                stop_result = self.stop()
                # Give a slight pause ONLY IF stop was successful, otherwise start might fail
                if "已停止" in stop_result: time.sleep(1)
                start_result = self.start()
                self._log("🔄 重启指令完成。")
                return f"推流已重启 ({start_result})" # Return only start result for simplicity
            else:
                self._log("ℹ️ 推流未在运行，直接启动...")
                start_result = self.start()
                return f"推流已启动 ({start_result})"

    def is_running(self):
        """Checks if streaming is active."""
        with self._lock:
            thread_alive = self.thread is not None and self.thread.is_alive()
            process_alive = self.process is not None and self.process.poll() is None
            if self._running and not (thread_alive or process_alive):
                 self._log("⚠️ 检测到运行状态不一致，自动修正为停止。")
                 self._running = False
                 # --- [FIX 11]: Use self.main_loop ---
                 if self.sio and self.main_loop:
                     asyncio.run_coroutine_threadsafe(self._emit_status_update(), self.main_loop)
            return self._running

    # --- [FIX 12]: Re-order get_status to avoid deadlock (from previous step) ---
    def get_status(self):
        """Gets the complete current status dictionary."""
        
        # 1. 先调用 is_running()。这个函数会自己获取和释放锁
        current_running_state = self.is_running()

        # 2. 现在，我们 *再次* 获取锁（这是安全的）
        with self._lock:
            config_data = {
                "resolution": self.resolution, "fps": self.fps, "crf": self.crf,
                "preset": self.preset, "input_source": self.input_source,
                "rtsp_url": self.rtsp_url, "ffmpeg_path": self.ffmpeg_path
            }
            log_data = self.get_log() # get_log() 不需要锁
            delay_data = self.get_delay_info() # get_delay_info() 不需要锁

        return {
            "running": current_running_state,
            "config": config_data,
            "log": log_data,
            "delay_info": delay_data
        }

    def get_log(self, count=20):
        """Gets recent log entries."""
        return list(self.log)[-count:]

    def get_delay_info(self):
        """Gets startup delay info."""
        # ... (remains the same) ...
        start = self.start_timestamps.get('start')
        first = self.start_timestamps.get('first_frame')
        if start and first:
            total_delay_ms = (first - start) * 1000
            return {"total_startup_ms": round(total_delay_ms, 1)}
        else:
            return {"total_startup_ms": None}