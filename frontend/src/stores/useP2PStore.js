import { ref, reactive, onUnmounted } from 'vue';
import { defineStore } from 'pinia';
import { ElMessage } from 'element-plus';
import { useSocketStore } from './useSocketStore';
import { useAIStore } from './useAIStore';

const P2P_NAMESPACE = '/p2p';

export const useP2PStore = defineStore('p2p', () => {
    const socketStore = useSocketStore();
    const p2pSocket = ref(null);

    // --- 状态 (State) ---
    const roomId = ref('');
    const myPeerId = ref(Math.random().toString(36).slice(2, 10));
    const targetPeerId = ref('');
    const otherPeerId = ref('');
    
    // 连接状态
    const joined = ref(false);
    const calling = ref(false); 
    const connectionState = ref('disconnected');
    
    // WebRTC 对象
    const pc = ref(null);
    const localStream = ref(null);
    const remoteStream = ref(null);
    const iceCandidateBuffer = ref([]); // ICE 候选缓冲区
    
    // 统计数据
    const stats = reactive({
        inbound: { bitrateKbps: 0, framesPerSecond: 0, bytesReceived: 0, packetsReceived: 0, packetsLost: 0, jitter: 0 },
        outbound: { bitrateKbps: 0, framesPerSecond: 0, bytesSent: 0, packetsSent: 0 },
        ice: { localCandidateType: '', remoteCandidateType: '', roundTripTimeMs: 0 }
    });
    let statsTimer = null;
    const prevStats = { 
        inboundBytes: 0, inboundTimestamp: 0, inboundFrames: 0, 
        outboundBytes: 0, outboundTimestamp: 0, outboundFrames: 0 
    };

    // --- [新功能] 切换视频轨道 (摄像头 <-> 视频文件) ---
    const switchVideoStream = async (newStream) => {
        console.log("=== 开始切换视频源 ===");
        
        // 1. 检查新流的合法性
        const newVideoTrack = newStream.getVideoTracks()[0];
        if (!newVideoTrack) {
            // 这一步应该已经被 Vue 层的重试机制拦截了，但这里做最后一道防线
            console.error("Error: switchVideoStream received stream with NO video tracks");
            ElMessage.error("切换失败：流中没有视频数据");
            return;
        }
        
        console.log("新视频轨道 ID:", newVideoTrack.id, "状态:", newVideoTrack.readyState);
        newVideoTrack.enabled = true;

        // 2. 混合流：保留麦克风声音，替换视频
        // 这样你在播放视频文件时，对方还能听到你说话
        let combinedStream;
        if (localStream.value) {
            const audioTracks = localStream.value.getAudioTracks();
            if (audioTracks.length > 0) {
                console.log(`保留 ${audioTracks.length} 个音频轨道`);
                combinedStream = new MediaStream([newVideoTrack, ...audioTracks]);
            } else {
                combinedStream = newStream;
            }
        } else {
            combinedStream = newStream;
        }
        
        // 3. 更新本地预览
        localStream.value = combinedStream;
        console.log("本地预览已更新");

        // 4. 如果正在 P2P 通话中，热切换 Sender
        if (pc.value && connectionState.value === 'connected') {
            const senders = pc.value.getSenders();
            const videoSender = senders.find(s => s.track && s.track.kind === 'video');

            if (videoSender) {
                try {
                    console.log("正在替换 WebRTC 发送轨道...");
                    await videoSender.replaceTrack(newVideoTrack);
                    ElMessage.success("P2P 推流已切换为视频文件");
                } catch (e) {
                    console.error("replaceTrack 失败:", e);
                    ElMessage.error("推流切换失败，请挂断重试");
                }
            } else {
                console.warn("未找到视频 Sender，可能是纯音频通话");
                ElMessage.warning("仅本地可见 (未找到发送通道)");
            }
        } else {
            ElMessage.success("视频源已就绪 (下次通话生效)");
        }
    };

    // --- 统计相关函数 ---
    const updateStats = async () => {
        if (!pc.value || pc.value.connectionState !== 'connected') {
            stopStats();
            return;
        }
        try {
            const reports = await pc.value.getStats();
            let activePair = null;

            // 查找当前活跃的 ICE 候选对
            reports.forEach(report => {
                if (report.type === 'candidate-pair' && report.state === 'succeeded') {
                    activePair = report;
                }
            });

            if (activePair) {
                stats.ice.roundTripTimeMs = activePair.currentRoundTripTime ? (activePair.currentRoundTripTime * 1000).toFixed(0) : 0;
                if (reports.has(activePair.localCandidateId)) {
                    stats.ice.localCandidateType = reports.get(activePair.localCandidateId).candidateType;
                }
                if (reports.has(activePair.remoteCandidateId)) {
                    stats.ice.remoteCandidateType = reports.get(activePair.remoteCandidateId).candidateType;
                }
            }

            reports.forEach(report => {
                // 入站视频流统计
                if (report.type === 'inbound-rtp' && (report.kind === 'video' || !report.kind)) {
                    stats.inbound.bytesReceived = report.bytesReceived;
                    stats.inbound.packetsReceived = report.packetsReceived;
                    stats.inbound.packetsLost = report.packetsLost;
                    stats.inbound.jitter = report.jitter;

                    const timeDiff = report.timestamp - prevStats.inboundTimestamp;
                    const bytesDiff = report.bytesReceived - prevStats.inboundBytes;
                    const framesDiff = (report.framesDecoded || 0) - prevStats.inboundFrames;

                    if (timeDiff > 0) {
                        stats.inbound.bitrateKbps = Math.round((bytesDiff * 8) / timeDiff);
                        stats.inbound.framesPerSecond = Math.round((framesDiff * 1000) / timeDiff);
                    }
                    prevStats.inboundBytes = report.bytesReceived;
                    prevStats.inboundTimestamp = report.timestamp;
                    prevStats.inboundFrames = report.framesDecoded || 0;
                }

                // 出站视频流统计
                if (report.type === 'outbound-rtp' && (report.kind === 'video' || !report.kind)) {
                    stats.outbound.bytesSent = report.bytesSent;
                    stats.outbound.packetsSent = report.packetsSent;

                    const timeDiff = report.timestamp - prevStats.outboundTimestamp;
                    const bytesDiff = report.bytesSent - prevStats.outboundBytes;
                    const framesDiff = report.framesSent - prevStats.outboundFrames;

                    if (timeDiff > 0) {
                        stats.outbound.bitrateKbps = Math.round((bytesDiff * 8) / timeDiff);
                        stats.outbound.framesPerSecond = Math.round((framesDiff * 1000) / timeDiff);
                    }
                    prevStats.outboundBytes = report.bytesSent;
                    prevStats.outboundTimestamp = report.timestamp;
                    prevStats.outboundFrames = report.framesSent;
                }
            });
        } catch (err) {
            console.error("Error getting stats:", err);
            stopStats();
        }
    };

    const startStats = () => {
        if (statsTimer) return;
        // 重置之前的数据
        Object.assign(prevStats, { inboundBytes: 0, inboundTimestamp: 0, inboundFrames: 0, outboundBytes: 0, outboundTimestamp: 0, outboundFrames: 0 });
        Object.assign(stats, {
            inbound: { bitrateKbps: 0, framesPerSecond: 0, bytesReceived: 0, packetsReceived: 0, packetsLost: 0, jitter: 0 },
            outbound: { bitrateKbps: 0, framesPerSecond: 0, bytesSent: 0, packetsSent: 0 },
            ice: { localCandidateType: '', remoteCandidateType: '', roundTripTimeMs: 0 }
        });
        statsTimer = setInterval(updateStats, 1000);
        console.log("P2P Stats collection started.");
    };

    const stopStats = () => {
        if (statsTimer) {
            clearInterval(statsTimer);
            statsTimer = null;
            console.log("P2P Stats collection stopped.");
        }
    };

    // --- 核心辅助函数 ---

    // 初始化 PeerConnection
    const initPeerConnection = () => {
        if (pc.value) { return; }
        console.log("Initializing RTCPeerConnection (P2P)...");
        try {
            pc.value = new RTCPeerConnection({
                iceServers: [{ urls: 'stun:stun.l.google.com:19302' }],
            });

            pc.value.onconnectionstatechange = () => {
                const newState = pc.value?.connectionState ?? 'closed';
                console.log("P2P Connection State Changed:", newState);
                connectionState.value = newState;
                if (newState === 'connected') {
                    calling.value = true;
                    startStats();
                    ElMessage.success('WebRTC P2P Connection Established');
                } else if (['disconnected', 'failed', 'closed'].includes(newState)) {
                    stopStats();
                    if (newState === 'failed' || newState === 'closed') {
                        calling.value = false;
                        ElMessage.warning(`WebRTC P2P Connection ${newState}`);
                    }
                }
            };

            pc.value.ontrack = (event) => {
                console.log("Received remote track:", event.streams[0]);
                if (event.streams && event.streams[0]) {
                    remoteStream.value = event.streams[0];
                }
            };

            pc.value.onicecandidate = (event) => {
                const candidate = event.candidate ? event.candidate.toJSON() : null;
                if (joined.value && targetPeerId.value && p2pSocket.value && p2pSocket.value.connected) {
                    // 注意：这里发送 signal 消息，后端会转发给 to
                    p2pSocket.value.emit('signal', { 
                        type: 'ice-candidate',
                        roomId: roomId.value,
                        to: targetPeerId.value,
                        candidate
                    });
                }
            };
        } catch (err) {
            console.error("PeerConnection initialization failed:", err);
            ElMessage.error(`Failed to initialize WebRTC: ${err.message}`);
            cleanup();
            throw err;
        }
    };

    // 启动本地预览 (不添加轨道)
    const startLocalPreview = async () => {
        if (localStream.value) { return; }
        try {
            console.log("Requesting local media for P2P Preview...");
            // 这里可能会失败，如果 FFmpeg 正在运行。这是预期的。
            const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
            localStream.value = stream;
            console.log("Local media acquired for P2P Preview.");
        } catch (err) {
            console.error("P2P GetUserMedia for Preview failed:", err);
            ElMessage.error(`无法获取摄像头/麦克风 (可能已被其他程序占用): ${err.message}`);
        }
    };

    // 获取媒体并添加到 PC (幂等操作)
    const getMediaAndAddTracks = async () => {
        if (!pc.value) throw new Error("PC not initialized");
        
        // 如果还没有预览流，尝试获取
        if (!localStream.value) {
            console.warn("No local preview stream found, attempting to get new media...");
            try {
                await startLocalPreview();
                if (!localStream.value) throw new Error("Media not available");
            } catch (err) {
                console.error("P2P GetUserMedia failed during call:", err);
                throw err;
            }
        }
        
        console.log("Adding local tracks to PeerConnection...");
        const senders = pc.value.getSenders();
        
        localStream.value.getTracks().forEach(track => {
            // [ 修复 ] 检查轨道是否已经添加，防止 "A sender already exists" 错误
            const senderExists = senders.some(sender => sender.track && sender.track.id === track.id);
            
            if (!senderExists) {
                console.log(`Adding ${track.kind} track...`);
                pc.value.addTrack(track, localStream.value);
            } else {
                console.log(`A ${track.kind} sender already exists. Skipping addTrack.`);
            }
        });
    };

    // 处理缓冲的 ICE 候选
    const processIceCandidateBuffer = async () => {
        if (!pc.value || iceCandidateBuffer.value.length === 0) {
            return;
        }
        console.log(`Processing ${iceCandidateBuffer.value.length} buffered ICE candidates...`);
        for (const candidate of iceCandidateBuffer.value) {
            try {
                await pc.value.addIceCandidate(new RTCIceCandidate(candidate));
            } catch (iceError) {
                 if (!iceError.message.includes("Cannot add ICE") && !iceError.message.includes("closed")) {
                     console.error("Error adding buffered ICE candidate:", iceError);
                 }
            }
        }
        iceCandidateBuffer.value = [];
    };

    // --- 信号处理 (Handle Signals) ---
    const handleSignal = async (data) => {
        console.log("P2P received signal:", data);
        const signalType = data.type;
        const fromPeer = data.from;

        try {
            // 确保 PC 已初始化
            if (!pc.value && (signalType === 'offer' || signalType === 'ice-candidate')) {
                initPeerConnection();
            }
            if (!pc.value && !['joined', 'join_error', 'peer_joined', 'peer_left', 'signal_error'].includes(signalType)) {
                return;
            }

            if (signalType === 'control') {
                const aiStore = useAIStore();
                
                if (data.action === 'start-ai') {
                    ElMessage.info(`Peer ${fromPeer} 请求开启 AI 分析`);
                    // 收到请求 -> 启动我的本地推流
                    // 注意：这里使用 store 里的状态
                    if (localStream.value && roomId.value && myPeerId.value) {
                        await aiStore.connectAI(localStream.value, roomId.value, myPeerId.value);
                    } else {
                        ElMessage.warning("无法响应 AI 请求：本地流未就绪");
                    }
                }
                else if (data.action === 'stop-ai') {
                    ElMessage.info(`Peer ${fromPeer} 请求停止 AI 分析`);
                    aiStore.stopStreaming();
                    if (aiStore.resultsMap[myPeerId.value]) {
                        delete aiStore.resultsMap[myPeerId.value];
                    }
                }
                return; // Control 消息处理完毕
            }
            if (signalType === 'offer') {
                if (!fromPeer) return;
                targetPeerId.value = fromPeer;
                ElMessage.info(`Call incoming from ${fromPeer}...`);
                
                // 1. 准备媒体
                await getMediaAndAddTracks();
                
                // 2. 设置远端描述 (Offer)
                await pc.value.setRemoteDescription(new RTCSessionDescription(data.offer));
                
                // 3. 处理可能先到的 ICE 候选
                await processIceCandidateBuffer();

                // 4. 创建应答 (Answer)
                const answer = await pc.value.createAnswer();
                await pc.value.setLocalDescription(answer);
                
                // 5. 发送应答 (直接发送对象，Socket.IO 会处理序列化)
                p2pSocket.value.emit('signal', { 
                    type: 'answer', 
                    roomId: roomId.value, 
                    to: fromPeer, 
                    answer: answer 
                });
                calling.value = true;

            } else if (signalType === 'answer') {
                // 设置远端描述 (Answer)
                await pc.value.setRemoteDescription(new RTCSessionDescription(data.answer));
                // 处理缓冲的候选
                await processIceCandidateBuffer();
                calling.value = true;

            } else if (signalType === 'ice-candidate') {
                // 缓冲逻辑：如果 RemoteDescription 还没设置，就先存起来
                if (!pc.value || !pc.value.remoteDescription) {
                    console.log("Buffering ICE candidate (remote description not set)");
                    if (data.candidate) {
                        iceCandidateBuffer.value.push(data.candidate);
                    }
                } else {
                    // 否则直接添加
                    try {
                        if (data.candidate) { 
                            await pc.value.addIceCandidate(new RTCIceCandidate(data.candidate)); 
                        } else { 
                            await pc.value.addIceCandidate(null); 
                        }
                    } catch (iceError) {
                        if (!iceError.message.includes("Cannot add ICE") && !iceError.message.includes("closed")) {
                             console.error("Error adding ICE candidate:", iceError);
                        }
                    }
                }

            } else if (signalType === 'signal_error') {
                ElMessage.error(`Signaling Error from server: ${data.message}`);
            } else if (signalType === 'peer_left') {
                if (data.peerId === targetPeerId.value || data.peerId === otherPeerId.value) {
                    ElMessage.warning(`Peer ${data.peerId} left.`);
                    otherPeerId.value = '';
                    cleanup(); // 对方离开，清理资源
                }
            } else if (signalType === 'peer_joined') {
                if (data.peerId !== myPeerId.value && !otherPeerId.value) {
                    otherPeerId.value = data.peerId;
                    ElMessage.info(`Peer ${data.peerId} joined. You can call them.`);
                    if (!targetPeerId.value) targetPeerId.value = data.peerId;
                }
            } else if (signalType === 'joined') {
                joined.value = true;
                ElMessage.success(`Successfully joined room: ${data.roomId}`);
                initPeerConnection(); // 初始化 WebRTC 栈
                startLocalPreview();  // 立即开启预览
            } else if (signalType === 'join_error') {
                ElMessage.error(`Failed to join room: ${data.message}`);
                cleanup();
            }
        } catch (error) { 
            console.error("Error in handleSignal:", error);
            ElMessage.error(`Error handling signal: ${error.message}`);
        }
    };

    // --- Actions (业务动作) ---

    const joinRoom = async (pRoomId, pMyPeerId) => {
        if (joined.value) return;
        if (!pRoomId || !pMyPeerId) { ElMessage.warning('Room ID and My ID required.'); return; }
        
        roomId.value = pRoomId; 
        myPeerId.value = pMyPeerId;
        
        // 使用 useSocketStore 获取连接
        p2pSocket.value = socketStore.getSocket(P2P_NAMESPACE);
        
        if (!p2pSocket.value.connected) {
            try {
                await new Promise((resolve, reject) => {
                    const timeout = setTimeout(() => reject(new Error("Socket connection timeout")), 5000);
                    p2pSocket.value.once('connect', () => { clearTimeout(timeout); resolve(); });
                    p2pSocket.value.once('connect_error', (err) => { clearTimeout(timeout); reject(err); });
                });
            } catch (err) {
                ElMessage.error(`Socket.IO to /p2p failed: ${err.message}`);
                p2pSocket.value = null; 
                return;
            }
        }
        console.log("/p2p socket connected.");

        // [ 健壮性 ] 断线重连逻辑：如果 socket 重新连接，自动重新加入房间
        p2pSocket.value.on('connect', () => {
            if (joined.value && roomId.value && myPeerId.value) {
                console.log("Socket reconnected, re-joining room...");
                p2pSocket.value.emit('join', { roomId: roomId.value, peerId: myPeerId.value });
            }
        });

        // 绑定事件
        p2pSocket.value.on('signal', handleSignal);
        p2pSocket.value.on('joined', (data) => handleSignal({ type: 'joined', ...data }));
        p2pSocket.value.on('join_error', (data) => handleSignal({ type: 'join_error', ...data }));
        p2pSocket.value.on('peer_joined', (data) => handleSignal({ type: 'peer_joined', ...data }));
        p2pSocket.value.on('peer_left', (data) => handleSignal({ type: 'peer_left', ...data }));
        
        // 发送加入请求
        p2pSocket.value.emit('join', { roomId: roomId.value, peerId: myPeerId.value });
    };

    const startCall = async (pTargetPeerId) => {
        if (!pc.value || !joined.value || !pTargetPeerId) { ElMessage.warning('Must join room, have PC, and set target ID.'); return; }
        if (!p2pSocket.value || !p2pSocket.value.connected) { ElMessage.error('Socket not connected.'); return; }
        
        targetPeerId.value = pTargetPeerId;
        try {
            await getMediaAndAddTracks(); // 确保媒体已添加

            const offer = await pc.value.createOffer();
            await pc.value.setLocalDescription(offer);
            
            p2pSocket.value.emit('signal', { 
                type: 'offer', 
                roomId: roomId.value, 
                to: targetPeerId.value, 
                offer: offer // 直接发送对象
            });
            ElMessage.info(`Calling ${targetPeerId.value}...`);
            calling.value = true;
        } catch (error) { ElMessage.error(`Call failed: ${error.message}`); }
    };

    const cleanup = () => {
        console.log("Cleaning up P2P Store resources...");
        stopStats(); 
        
        if (pc.value) {
            pc.value.close();
            pc.value = null;
        }
        
        // 清理本地流
        if (localStream.value) { 
            localStream.value.getTracks().forEach(t => t.stop()); 
            localStream.value = null; 
        }
        remoteStream.value = null;

        // 清理 socket 监听器
        if (p2pSocket.value) {
            p2pSocket.value.off('signal');
            p2pSocket.value.off('joined');
            p2pSocket.value.off('join_error');
            p2pSocket.value.off('peer_joined');
            p2pSocket.value.off('peer_left');
            p2pSocket.value.off('connect'); // 清理重连监听器

            if (joined.value && roomId.value) {
                p2pSocket.value.emit('leave', { roomId: roomId.value });
            }
            p2pSocket.value = null;
        }
        
        joined.value = false;
        calling.value = false;
        connectionState.value = 'disconnected';
        targetPeerId.value = '';
        otherPeerId.value = '';
        iceCandidateBuffer.value = []; 
        console.log("P2P Store cleanup finished.");
    };
    
    const hangup = () => { cleanup(); ElMessage.info('Call ended.'); };
    const leaveRoom = () => { cleanup(); roomId.value = ''; ElMessage.info('Left room.'); };

    onUnmounted(() => { cleanup(); });

    return {
        // State
        roomId, myPeerId, targetPeerId, otherPeerId,
        joined, calling, connectionState,
        localStream, remoteStream, stats,
        // Actions
        joinRoom, startCall, hangup, leaveRoom, cleanup,
        startLocalPreview, switchVideoStream
    };
});