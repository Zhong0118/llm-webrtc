import { ref, reactive, onUnmounted } from 'vue';
import { defineStore } from 'pinia';
import { ElMessage } from 'element-plus';
import { useSocketStore } from './useSocketStore';

const P2P_NAMESPACE = '/p2p';

export const useP2PStore = defineStore('p2p', () => {
    const socketStore = useSocketStore();
    const p2pSocket = ref(null);

    // --- State ---
    const roomId = ref('');
    const myPeerId = ref(Math.random().toString(36).slice(2, 10));
    const targetPeerId = ref('');
    const otherPeerId = ref('');
    const joined = ref(false);
    const calling = ref(false); 
    const connectionState = ref('disconnected');
    const pc = ref(null);
    const localStream = ref(null);
    const remoteStream = ref(null);
    const iceCandidateBuffer = ref([]); 
    
    const stats = reactive({ /* ... (保持 V23 不变) ... */ 
        inbound: { bitrateKbps: 0, framesPerSecond: 0, bytesReceived: 0, packetsReceived: 0, packetsLost: 0, jitter: 0 },
        outbound: { bitrateKbps: 0, framesPerSecond: 0, bytesSent: 0, packetsSent: 0 },
        ice: { localCandidateType: '', remoteCandidateType: '', roundTripTimeMs: 0 }
    });
    let statsTimer = null;
    const prevStats = { inboundBytes: 0, inboundTimestamp: 0, inboundFrames: 0, outboundBytes: 0, outboundTimestamp: 0, outboundFrames: 0 };

    // --- (统计函数 ... 保持 V23 不变) ---
    const updateStats = async () => {
        if (!pc.value || pc.value.connectionState !== 'connected') {
            stopStats(); return;
        }
        try {
            const reports = await pc.value.getStats();
            let activePair = null;
            reports.forEach(report => {
                if (report.type === 'candidate-pair' && report.state === 'succeeded') { activePair = report; }
            });
            if (activePair) {
                stats.ice.roundTripTimeMs = activePair.currentRoundTripTime ? (activePair.currentRoundTripTime * 1000).toFixed(0) : 0;
                if (reports.has(activePair.localCandidateId)) { stats.ice.localCandidateType = reports.get(activePair.localCandidateId).candidateType; }
                if (reports.has(activePair.remoteCandidateId)) { stats.ice.remoteCandidateType = reports.get(activePair.remoteCandidateId).candidateType; }
            }
            reports.forEach(report => {
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
        } catch (err) { console.error("Error getting stats:", err); stopStats(); }
    };
    const startStats = () => {
        if (statsTimer) return;
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
        if (statsTimer) { clearInterval(statsTimer); statsTimer = null; console.log("P2P Stats collection stopped."); }
    };
    // --- (统计函数结束) ---

    // --- Private Helpers (保持 V23 不变) ---
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
                // 这个 .toJSON() 是正确的，因为 event.candidate 是一个 RTCIceCandidate 对象
                const candidate = event.candidate ? event.candidate.toJSON() : null;
                if (joined.value && targetPeerId.value && p2pSocket.value && p2pSocket.value.connected) {
                    p2pSocket.value.emit('signal', { 
                        type: 'ice-candidate',
                        roomId: roomId.value,
                        to: targetPeerId.value,
                        candidate // candidate 此时是 { candidate: "...", sdpMid: ... }
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
    const startLocalPreview = async () => {
        if (localStream.value) { return; } 
        try {
            console.log("Requesting local media for P2P Preview...");
            const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
            localStream.value = stream;
            console.log("Local media acquired for P2P Preview.");
        } catch (err) {
            console.error("P2P GetUserMedia for Preview failed:", err);
            ElMessage.error(`无法获取摄像头/麦克风 (可能已被FFmpeg占用): ${err.message}`);
        }
    };
    const getMediaAndAddTracks = async () => {
        if (!pc.value) { throw new Error("PC not initialized"); }
        if (!localStream.value) {
            console.warn("No local preview stream found, attempting to get new media...");
            try {
                await startLocalPreview(); 
                if (!localStream.value) { throw new Error("Media not available"); }
            } catch (err) {
                console.error("P2P GetUserMedia failed during call:", err);
                throw err; 
            }
        }
        console.log("Adding local tracks to PeerConnection...");
        localStream.value.getTracks().forEach(track => {
            pc.value.addTrack(track, localStream.value);
        });
    };
    const processIceCandidateBuffer = async () => {
        if (!pc.value || iceCandidateBuffer.value.length === 0) {
            return;
        }
        console.log(`Processing ${iceCandidateBuffer.value.length} buffered ICE candidates...`);
        for (const candidate of iceCandidateBuffer.value) {
            try {
                // 这里的 candidate 是 { candidate: "...", sdpMid: ... }
                await pc.value.addIceCandidate(new RTCIceCandidate(candidate));
            } catch (iceError) {
                 if (!iceError.message.includes("Cannot add ICE") && !iceError.message.includes("closed")) {
                     console.error("Error adding buffered ICE candidate:", iceError);
                 }
            }
        }
        iceCandidateBuffer.value = [];
    };
    // --- (Signal Handler 缓冲区逻辑保持 V23 不变) ---
    const handleSignal = async (data) => {
        console.log("P2P received signal:", data);
        const signalType = data.type;
        const fromPeer = data.from;
        try {
            if (!pc.value && (signalType === 'offer' || signalType === 'ice-candidate')) {
                initPeerConnection(); 
            }
            if (!pc.value && !['joined', 'join_error', 'peer_joined', 'peer_left', 'signal_error'].includes(signalType)) {
                return;
            }

            if (signalType === 'offer') {
                if (!fromPeer) { return; }
                targetPeerId.value = fromPeer;
                ElMessage.info(`Call incoming from ${fromPeer}...`);
                
                await getMediaAndAddTracks(); 
                
                // data.offer 就是 { type: "offer", sdp: "..." }
                await pc.value.setRemoteDescription(new RTCSessionDescription(data.offer));
                
                await processIceCandidateBuffer(); 

                const answer = await pc.value.createAnswer();
                await pc.value.setLocalDescription(answer);
                
                p2pSocket.value.emit('signal', { 
                    type: 'answer', 
                    roomId: roomId.value, 
                    to: fromPeer, 
                    // [ 关键修复 1 ]：移除 .toJSON()
                    answer: answer 
                });
                calling.value = true; 

            } else if (signalType === 'answer') {
                // data.answer 就是 { type: "answer", sdp: "..." }
                await pc.value.setRemoteDescription(new RTCSessionDescription(data.answer));
                
                await processIceCandidateBuffer(); 
                
                calling.value = true; 
            } else if (signalType === 'ice-candidate') {
                
                if (!pc.value || !pc.value.remoteDescription) {
                    console.log("Buffering ICE candidate (remote description not set)");
                    if (data.candidate) {
                        iceCandidateBuffer.value.push(data.candidate);
                    }
                } else {
                    try {
                        if (data.candidate) { 
                            // data.candidate 是 { candidate: "...", sdpMid: ... }
                            await pc.value.addIceCandidate(new RTCIceCandidate(data.candidate)); 
                        } 
                        else { await pc.value.addIceCandidate(null); }
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
                    cleanup();
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
                initPeerConnection();      
                startLocalPreview();   
            } else if (signalType === 'join_error') {
                ElMessage.error(`Failed to join room: ${data.message}`);
                cleanup();
            }
        } catch (error) { 
            console.error("Error in handleSignal:", error);
            ElMessage.error(`Error handling signal: ${error.message}`);
        }
    };

    // --- Actions (已修改) ---
    const joinRoom = async (pRoomId, pMyPeerId) => {
        // (此函数保持 V23 不变)
        if (joined.value) return;
        if (!pRoomId || !pMyPeerId) { ElMessage.warning('Room ID and My ID required.'); return; }
        roomId.value = pRoomId; myPeerId.value = pMyPeerId;
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
                p2pSocket.value = null; return;
            }
        }
        console.log("/p2p socket connected.");
        p2pSocket.value.on('signal', handleSignal);
        p2pSocket.value.on('joined', (data) => handleSignal({ type: 'joined', ...data }));
        p2pSocket.value.on('join_error', (data) => handleSignal({ type: 'join_error', ...data }));
        p2pSocket.value.on('peer_joined', (data) => handleSignal({ type: 'peer_joined', ...data }));
        p2pSocket.value.on('peer_left', (data) => handleSignal({ type: 'peer_left', ...data }));
        p2pSocket.value.emit('join', { roomId: roomId.value, peerId: myPeerId.value });
    };

    const startCall = async (pTargetPeerId) => {
        if (!pc.value || !joined.value || !pTargetPeerId) { ElMessage.warning('Must join room, have PC, and set target ID.'); return; }
        if (!p2pSocket.value || !p2pSocket.value.connected) { ElMessage.error('Socket not connected.'); return; }
        
        targetPeerId.value = pTargetPeerId;
        try {
            await getMediaAndAddTracks(); 
            const offer = await pc.value.createOffer();
            await pc.value.setLocalDescription(offer);
            
            p2pSocket.value.emit('signal', { 
                type: 'offer', 
                roomId: roomId.value, 
                to: targetPeerId.value, 
                // [ 关键修复 2 ]：移除 .toJSON()
                offer: offer 
            });
            ElMessage.info(`Calling ${targetPeerId.value}...`);
            calling.value = true;
        } catch (error) { ElMessage.error(`Call failed: ${error.message}`); }
    };

    const cleanup = () => {
        // (此函数保持 V23 不变)
        console.log("Cleaning up P2P Store resources...");
        stopStats(); 
        if (pc.value) {
            pc.value.close();
            pc.value = null;
        }
        if (localStream.value) { 
            localStream.value.getTracks().forEach(t => t.stop()); 
            localStream.value = null; 
        }
        remoteStream.value = null;

        if (p2pSocket.value) {
            p2pSocket.value.off('signal', handleSignal);
            p2pSocket.value.off('joined');
            p2pSocket.value.off('join_error');
            p2pSocket.value.off('peer_joined');
            p2pSocket.value.off('peer_left');
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
        startLocalPreview 
    };
});