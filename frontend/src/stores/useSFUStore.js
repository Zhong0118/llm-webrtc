// frontend/src/stores/useSFUStore.js
import { Device } from 'mediasoup-client';
import { defineStore } from 'pinia';
import { useSocketStore } from './useSocketStore';

export const useSFUStore = defineStore('sfu', () => {
  const socket = useSocketStore().getSocket('/sfu');
  const device = new Device();
  const producers = new Map();
  const consumers = new Map();

  const joinRoom = async (roomId, peerId) => {
    await new Promise((resolve) => socket.emit('join-room', { roomId, peerId }, resolve));
    const rtpCapabilities = await once(socket, 'router-rtp-capabilities');
    await device.load({ routerRtpCapabilities: rtpCapabilities });
  };

  const publish = async (stream) => {
    const sendTransportInfo = await requestTransport('send');
    const sendTransport = device.createSendTransport(sendTransportInfo);
    bindTransportEvents(sendTransport);
    const track = stream.getVideoTracks()[0];
    const producer = await sendTransport.produce({ track });
    producers.set(producer.id, producer);
  };

  const subscribe = async (producerInfo, onTrack) => {
    const recvTransportInfo = await requestTransport('recv');
    const recvTransport = device.createRecvTransport(recvTransportInfo);
    bindTransportEvents(recvTransport);
    const consumerParams = await requestConsume(recvTransport.id, producerInfo.producerId);
    const consumer = await recvTransport.consume(consumerParams);
    consumer.track.onmute = () => consumer.close();
    onTrack(consumer.track, producerInfo.peerId);
  };

  return { joinRoom, publish, subscribe };
});
