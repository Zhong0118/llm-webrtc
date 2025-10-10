// 动态加载 TFJS 与 Handpose 模型（通过CDN），避免安装依赖
// 轻量方案用于在浏览器侧进行手部关键点提取

const TFJS_URL = 'https://cdn.jsdelivr.net/npm/@tensorflow/tfjs@3.20.0/dist/tf.min.js'
const HANDPOSE_URL = 'https://cdn.jsdelivr.net/npm/@tensorflow-models/handpose@0.0.7/dist/handpose.min.js'

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = src
    script.async = true
    script.onload = () => resolve()
    script.onerror = (e) => reject(e)
    document.head.appendChild(script)
  })
}

export async function loadHandposeModel() {
  if (window.handpose && window.tf) {
    return await window.handpose.load()
  }
  await loadScript(TFJS_URL)
  await loadScript(HANDPOSE_URL)
  if (!window.handpose) throw new Error('handpose 未成功加载')
  return await window.handpose.load()
}

export function toPlainHandData(predictions) {
  // handpose 返回的结构过于复杂，这里提取关键点和左右手信息
  // predictions: [{landmarks: [[x,y,z],...], annotations: {...}}]
  return (predictions || []).map((p) => ({
    landmarks: (p.landmarks || []).map((lm) => [lm[0], lm[1], lm[2]]),
    handedness: 'unknown'
  }))
}