"""
X3D Integration Helper
======================

这个脚本帮助您将 X3D Processor 集成到现有的 WebRTC 系统中。

使用方法：
    python integrate_x3d.py

功能：
1. 检查环境依赖
2. 测试 X3D 模型是否能正常加载
3. 生成集成代码示例

作者: AI Toolkit Assistant
日期: 2025-12-16
"""

import sys
import subprocess
from pathlib import Path

def check_dependencies():
    """检查必要的依赖是否已安装"""
    print("="*60)
    print("🔍 检查依赖...")
    print("="*60)
    
    required_packages = {
        'torch': 'PyTorch',
        'torchvision': 'TorchVision',
        'pytorchvideo': 'PyTorchVideo',
        'cv2': 'OpenCV (opencv-python)',
        'pandas': 'Pandas',
        'matplotlib': 'Matplotlib',
        'seaborn': 'Seaborn',
    }
    
    missing = []
    
    for package, name in required_packages.items():
        try:
            __import__(package)
            print(f"✅ {name}")
        except ImportError:
            print(f"❌ {name} - 未安装")
            missing.append(package if package != 'cv2' else 'opencv-python')
    
    if missing:
        print("\n⚠️ 缺少以下依赖:")
        for pkg in missing:
            print(f"   - {pkg}")
        
        print("\n📦 安装命令:")
        print(f"   pip install {' '.join(missing)}")
        return False
    
    print("\n✅ 所有依赖已安装")
    return True


def test_x3d_model():
    """测试 X3D 模型是否能正常加载"""
    print("\n" + "="*60)
    print("🧪 测试 X3D 模型...")
    print("="*60)
    
    try:
        import torch
        from pytorchvideo.models.hub import x3d_s
        
        print("📥 加载 X3D-S 模型...")
        model = x3d_s(pretrained=True)
        
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        print(f"🎯 使用设备: {device}")
        
        if device == 'cuda':
            gpu_name = torch.cuda.get_device_name(0)
            gpu_memory = torch.cuda.get_device_properties(0).total_memory / 1e9
            print(f"   GPU: {gpu_name}")
            print(f"   显存: {gpu_memory:.1f} GB")
        
        model = model.to(device)
        model.eval()
        
        # 测试推理
        print("\n🔥 测试推理性能...")
        import time
        
        dummy_input = torch.randn(1, 3, 13, 182, 182).to(device)
        
        # Warmup
        with torch.no_grad():
            _ = model(dummy_input)
        
        if device == 'cuda':
            torch.cuda.synchronize()
        
        # Benchmark
        times = []
        for _ in range(10):
            start = time.time()
            with torch.no_grad():
                _ = model(dummy_input)
            if device == 'cuda':
                torch.cuda.synchronize()
            times.append(time.time() - start)
        
        avg_time = sum(times) / len(times) * 1000  # 转为毫秒
        
        print(f"\n✅ X3D-S 模型测试成功!")
        print(f"   平均推理时间: {avg_time:.1f} ms")
        print(f"   预计 FPS: {1000/avg_time:.1f}")
        
        # 性能评估
        if avg_time < 50:
            print("   性能评级: ⭐⭐⭐⭐⭐ 优秀（适合实时）")
        elif avg_time < 100:
            print("   性能评级: ⭐⭐⭐⭐ 良好")
        elif avg_time < 200:
            print("   性能评级: ⭐⭐⭐ 一般（需要优化）")
        else:
            print("   性能评级: ⭐⭐ 较慢（建议减小 chunk_size）")
        
        return True
        
    except Exception as e:
        print(f"\n❌ X3D 模型测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def generate_integration_example():
    """生成集成代码示例"""
    print("\n" + "="*60)
    print("📝 集成代码示例")
    print("="*60)
    
    example_code = """
# ============================================================
# 方式 1: 修改现有的 main.py
# ============================================================

# 在 backend/main.py 中：

# 1. 导入 X3D Processor（替代原 AIProcessor）
from ai_processor_x3d import AIProcessorX3D

# 2. 在 app 初始化时创建实例
app = web.Application()
ai_processor = AIProcessorX3D()  # 替代原来的 AIProcessor()

# 3. 注册处理器（与原代码相同）
from handlers.ai import register_ai_handlers
register_ai_handlers(sio, ai_processor)

# ============================================================
# 方式 2: 仅用于测试（不影响现有系统）
# ============================================================

# 运行测试脚本（独立测试，不影响现有系统）
cd backend/test/multi2
python full_system_x3d_test.py

# ============================================================
# 配置调整（可选）
# ============================================================

# 在 handlers/ai.py 的 process_ai_track 函数中：
# 可以动态调整配置

@sio.event(namespace='/ai_analysis')
async def update_config(sid, data):
    '''允许前端动态调整 chunk_size 和 stride'''
    ai_processor.update_config(data)
    await sio.emit('config_updated', data, room=sid)

# 前端可以发送：
socket.emit('update_config', {
    chunk_size: 16,
    stride: 8,
    enable_fp16: true
}, namespace='/ai_analysis');

# ============================================================
# 性能优化（针对 RTX 4060）
# ============================================================

# 1. 启用混合精度（已默认启用）
config = {
    "enable_fp16": True,  # RTX 4060 支持
    "chunk_size": 13,     # X3D-S 标准值
    "stride": 6           # 平衡精度和速度
}

# 2. 如果显存不足，可以减小 chunk_size
config = {
    "chunk_size": 8,      # 减小到 8 帧
    "enable_fp16": True
}

# 3. 如果追求极致速度（牺牲精度）
config = {
    "chunk_size": 8,
    "stride": 8,          # 每 8 帧推理一次
    "enable_fp16": True
}
"""
    
    print(example_code)
    
    # 保存到文件
    output_file = Path("integration_example.py")
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(example_code)
    
    print(f"\n✅ 集成示例已保存到: {output_file}")


def main():
    """主函数"""
    print("\n" + "🚀 X3D Integration Helper")
    print("="*60)
    
    # Step 1: 检查依赖
    if not check_dependencies():
        print("\n❌ 请先安装缺失的依赖")
        return
    
    # Step 2: 测试模型
    if not test_x3d_model():
        print("\n❌ 模型测试失败，请检查 PyTorch 和 PyTorchVideo 安装")
        return
    
    # Step 3: 生成集成示例
    generate_integration_example()
    
    # Step 4: 下一步指引
    print("\n" + "="*60)
    print("🎯 下一步:")
    print("="*60)
    print("1. 查看 integration_example.py 了解集成方法")
    print("2. 运行测试脚本验证系统:")
    print("   cd backend/test/multi2")
    print("   python full_system_x3d_test.py")
    print("3. 分析结果:")
    print("   python analyze_x3d_results.py")
    print("="*60)


if __name__ == "__main__":
    main()
