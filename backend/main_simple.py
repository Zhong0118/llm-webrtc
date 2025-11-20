# main_simple.py (Refactored)
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import socketio
import uvicorn
import logging
import os

# Import Handlers
from handlers.p2p import register_p2p_handlers
from handlers.ai import register_ai_handlers
from handlers.streamer import register_streamer_handlers, StreamerContext

# Import Core Components
from ai_processor import AIProcessor
try:
    from streaming.streamer import RTSPStreamer
    VLC_AVAILABLE = True
except ImportError:
    VLC_AVAILABLE = False
    RTSPStreamer = None

# Configure Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("WebRTCApp")

# Setup App and Socket.IO
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
fastapi_app = FastAPI()
app = socketio.ASGIApp(socketio_server=sio, other_asgi_app=fastapi_app)

fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Components
ai_processor = AIProcessor()

if VLC_AVAILABLE:
    vlc_streamer = RTSPStreamer(sio_server=sio, namespace="/streamer")
    streamer_context = StreamerContext(vlc_streamer)
else:
    vlc_streamer = None
    streamer_context = StreamerContext(None)

# Register Handlers
register_p2p_handlers(sio)
register_ai_handlers(sio, ai_processor)
register_streamer_handlers(fastapi_app, sio, streamer_context)

# Basic Routes
@fastapi_app.get("/")
async def root():
    return {"message": "WebRTC Server is running (Refactored)", "status": "ok"}

@fastapi_app.get("/health")
async def health_check():
    return {"status": "healthy"}

@fastapi_app.get("/api/info")
async def server_info():
    return {
        "server": "WebRTC Server",
        "version": "2.0.0",
        "socketio_namespaces": ["/p2p", "/streamer", "/server_push", "/ai_analysis"],
        "vlc_available": VLC_AVAILABLE,
    }

if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    cert_dir = os.path.abspath(os.path.join(base_dir, "..", "frontend", "certs"))
    ssl_keyfile = os.path.join(cert_dir, "localhost+3-key.pem")
    ssl_certfile = os.path.join(cert_dir, "localhost+3.pem")
    
    if os.path.exists(ssl_keyfile) and os.path.exists(ssl_certfile):
        print(f"Starting HTTPS Server on port 33335")
        uvicorn.run(app, host="0.0.0.0", port=33335, ssl_keyfile=ssl_keyfile, ssl_certfile=ssl_certfile)
    else:
        print(f"Starting HTTP Server on port 33335 (No Certs Found)")
        uvicorn.run(app, host="0.0.0.0", port=33335)
