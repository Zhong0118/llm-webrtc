import { reactive, ref } from 'vue';
import { defineStore } from 'pinia';
import { io } from 'socket.io-client';

export const useSocketStore = defineStore('socket', () => {
    // 管理一个连接池 e.g., { '/p2p': Socket, '/streamer': Socket }
    const connections = reactive({});
    const serverUrl = ref('');

    /**
     * 初始化，计算基础 URL
     * 这应该在您的主组件 (App.vue 或 SimpleWebRTC.vue) onMounted 时被调用一次。
     */
    function initialize() {
        if (serverUrl.value) return; // 已经初始化
        serverUrl.value = window.location.origin;
        console.log(`Socket.IO Base URL (via Vite Proxy): ${serverUrl.value}`);
    }

    /**
     * 按需获取或创建命名空间连接
     * @param {string} namespace - 例如 '/p2p' 或 '/streamer'
     * @returns {Socket} Socket.IO 客户端实例
     */
    function getSocket(namespace = '/') {
        // 确保 initialize 已被调用
        if (!serverUrl.value) {
            initialize();
        }

        // 如果已存在并且已连接，直接返回
        if (connections[namespace] && (connections[namespace].connected || connections[namespace].connecting)) {
            return connections[namespace];
        }

        // 如果已存在但已断开，先移除
        if (connections[namespace]) {
             connections[namespace].disconnect();
             delete connections[namespace];
        }
        
        // --- 修正：Socket.IO 客户端连接到命名空间的方式 ---
        // 正确的方式是在URL中包含命名空间路径
        
        const fullUrl = namespace === '/' ? serverUrl.value : `${serverUrl.value}${namespace}`;
        console.log(`Connecting Socket.IO to namespace: '${namespace}' at ${fullUrl}`);

        const socket = io(fullUrl, { // 连接到包含命名空间的完整URL
            reconnectionAttempts: 5,
            transports: ['websocket'],
            path: '/socket.io', // 必须匹配 vite.config.js 的 proxy 规则
            namespace: namespace, 
        });

        socket.on('connect', () => {
            console.log(`Socket.IO connected to namespace: ${namespace}`);
        });
        socket.on('disconnect', (reason) => {
            console.warn(`Socket.IO disconnected from ${namespace}: ${reason}`);
            if (connections[namespace]) {
                delete connections[namespace];
            }
        });
        socket.on('connect_error', (error) => {
            console.error(`Socket.IO ${namespace} connection error:`, error.message);
        });

        connections[namespace] = socket; // 存储这个命名空间的连接
        return socket;
    }

    /**
     * 断开所有连接
     */
    function disconnectAll() {
        console.log('Disconnecting all Socket.IO namespaces...');
        for (const ns in connections) {
            connections[ns].disconnect();
        }
        Object.keys(connections).forEach(key => delete connections[key]); // 清空连接池
    }

    return {
        getSocket,
        disconnectAll,
        initialize
    };
});
