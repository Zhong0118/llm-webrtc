// backend/sfu/server.js
import http from 'http';
import express from 'express';
import { Server } from 'socket.io';
import * as mediasoup from 'mediasoup';

const app = express();
const httpServer = http.createServer(app);
const io = new Server(httpServer, { cors: { origin: '*' } });

const worker = await mediasoup.createWorker({ rtcMinPort: 40000, rtcMaxPort: 49999 });
const router = await worker.createRouter({ mediaCodecs: [
  { kind: 'audio', mimeType: 'audio/opus', clockRate: 48000, channels: 2 },
  { kind: 'video', mimeType: 'video/H264', clockRate: 90000, parameters: { 'packetization-mode': 1, 'profile-level-id': '42e01f' } },
]});

const rooms = new Map(); // roomId -> { peers: Map<socketId, PeerContext> }

io.on('connection', socket => {
  socket.on('join-room', async ({ roomId, peerId }) => {
    if (!rooms.has(roomId)) rooms.set(roomId, { peers: new Map() });
    rooms.get(roomId).peers.set(socket.id, { peerId, transports: [], producers: [], consumers: [] });
    socket.join(roomId);
    socket.emit('router-rtp-capabilities', router.rtpCapabilities);
  });

  socket.on('create-transport', async ({ direction }, cb) => {
    const transport = await router.createWebRtcTransport({
      listenIps: [{ ip: '0.0.0.0', announcedIp: process.env.PUBLIC_IP }],
      enableUdp: true, enableTcp: true, preferUdp: true,
    });
    const peer = findPeer(socket.id);
    peer.transports.push(transport);
    transport.observer.on('dtlsstatechange', state => state === 'closed' && transport.close());
    cb({
      id: transport.id,
      iceParameters: transport.iceParameters,
      iceCandidates: transport.iceCandidates,
      dtlsParameters: transport.dtlsParameters,
    });
  });

  socket.on('connect-transport', async ({ transportId, dtlsParameters }) => {
    const transport = findTransport(socket.id, transportId);
    await transport.connect({ dtlsParameters });
  });

  socket.on('produce', async ({ transportId, kind, rtpParameters }, cb) => {
    const transport = findTransport(socket.id, transportId);
    const producer = await transport.produce({ kind, rtpParameters });
    const peer = findPeer(socket.id);
    peer.producers.push(producer);
    producer.observer.on('close', () => producer.close());
    cb({ id: producer.id });
    socket.to(getRoom(socket.id)).emit('new-producer', { producerId: producer.id, peerId: peer.peerId });
  });

  socket.on('consume', async ({ transportId, producerId, rtpCapabilities }, cb) => {
    if (!router.canConsume({ producerId, rtpCapabilities })) return cb({ error: 'cannot consume' });
    const transport = findTransport(socket.id, transportId);
    const consumer = await transport.consume({ producerId, rtpCapabilities, paused: false });
    findPeer(socket.id).consumers.push(consumer);
    cb({ id: consumer.id, kind: consumer.kind, rtpParameters: consumer.rtpParameters, producerId });
  });

  socket.on('disconnect', () => cleanupPeer(socket.id));
});

httpServer.listen(8888, () => console.log('SFU listening on :8888'));

function getRoom(socketId) {
  for (const [roomId, room] of rooms.entries()) {
    if (room.peers.has(socketId)) return roomId;
  }
  return null;
}

function findPeer(socketId) {
  const roomId = getRoom(socketId);
  if (!roomId) throw new Error(`Peer ${socketId} not in any room`);
  return rooms.get(roomId).peers.get(socketId);
}

function findTransport(socketId, transportId) {
  const peer = findPeer(socketId);
  const transport = peer.transports.find(t => t.id === transportId);
  if (!transport) throw new Error(`Transport ${transportId} not found`);
  return transport;
}

function cleanupPeer(socketId) {
  const roomId = getRoom(socketId);
  if (!roomId) return;
  const room = rooms.get(roomId);
  const peer = room.peers.get(socketId);
  if (!peer) return;
  peer.consumers.forEach(c => c.close());
  peer.producers.forEach(p => p.close());
  peer.transports.forEach(t => t.close());
  room.peers.delete(socketId);
  if (room.peers.size === 0) rooms.delete(roomId);
}