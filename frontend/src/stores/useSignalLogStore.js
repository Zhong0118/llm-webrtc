import { defineStore } from 'pinia';

export const useSignalLogStore = defineStore('signalLog', () => {
  const events = ref([]);
  const pushLog = (payload) => {
    events.value.unshift({
      id: crypto.randomUUID(),
      direction: payload.direction,          // 'out' / 'in'
      namespace: payload.namespace,
      type: payload.type,
      to: payload.to,
      from: payload.from,
      ts: performance.now(),
      meta: payload.meta ?? {}
    });
    events.value = events.value.slice(0, 200);
  };
  return { events, pushLog };
});