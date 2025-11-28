# analyze_data.py
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import os
import numpy as np

BATCH_SIZES = [1, 5, 10, 20]

def ensure_dir(directory):
    if not os.path.exists(directory):
        os.makedirs(directory)

def plot_cdf(data, column, ax, label):
    """辅助函数：绘制累积分布函数 (CDF)"""
    sorted_data = np.sort(data[column])
    yvals = np.arange(len(sorted_data)) / float(len(sorted_data) - 1)
    ax.plot(sorted_data, yvals, label=label)

def analyze_single_file(batch_size):
    filename = f'benchmark_log_batch_{batch_size}.csv'
    
    if not os.path.exists(filename):
        print(f"⚠️ 跳过: 找不到 {filename}")
        return

    print(f"\n📊 正在分析: {filename} ...")
    df = pd.read_csv(filename)
    
    # 创建输出目录
    output_dir = os.path.join("analysis_results", f"batch_{batch_size}")
    ensure_dir(output_dir)
    
    # 设置绘图风格
    sns.set_theme(style="whitegrid", context="notebook")
    
    # ================= 图表 1: 推理耗时分布 (Boxplot) =================
    # 不同帧数和分辨率下的推理时间对比。箱子高说明推理慢，长说明性能不稳定
    plt.figure(figsize=(10, 6))
    sns.boxplot(x='fps', y='inference_time', hue='resolution', data=df, palette="Set2")
    plt.title(f"AI Model Inference Latency (Batch: {batch_size})")
    plt.ylabel("Time (ms)")
    plt.xlabel("Target FPS")
    plt.savefig(os.path.join(output_dir, "1_inference_latency.png"))
    plt.close()

    # ================= 图表 2: E2E 延迟稳定性 (Lineplot) =================
    # 是平的那就稳定，向上倾斜说明发生积压
    plt.figure(figsize=(12, 6))
    sns.lineplot(x=df.index, y='e2e_delay', hue='fps', style='resolution', data=df, alpha=0.8, palette="tab10")
    plt.title(f"End-to-End Latency Stability (Batch: {batch_size})")
    plt.ylabel("Latency (ms)")
    plt.xlabel("Sample Sequence")
    plt.ylim(bottom=0)
    plt.savefig(os.path.join(output_dir, "2_e2e_stability.png"))
    plt.close()

    # ================= 图表 3: FPS 达标率分析 (Barplot) =================
    # 对比 "设置的 FPS" 和 "服务器实际处理 FPS"
    plt.figure(figsize=(10, 6))
    # 融化数据以便绘图
    fps_df = df.melt(id_vars=['resolution', 'fps'], value_vars=['server_fps'], var_name='metric', value_name='value')
    sns.barplot(x='fps', y='value', hue='resolution', data=fps_df, palette="viridis")
    # 画一条理想线
    plt.plot([-0.5, 3.5], [15, 15], 'r--', alpha=0.5, label='Target 15')
    plt.plot([-0.5, 3.5], [30, 30], 'r:', alpha=0.5, label='Target 30')
    plt.title(f"Server Actual Throughput (FPS) vs Target")
    plt.ylabel("Actual FPS")
    plt.ylim(0, 35)
    plt.savefig(os.path.join(output_dir, "3_fps_performance.png"))
    plt.close()

    # ================= 图表 4: 延迟构成分析 (Network vs Compute) =================
    # 红色是AI的计算速度，蓝色是解码编码等杂项，绿色是网络延迟（估算）
    df['network_overhead'] = df['e2e_delay'] - df['process_time']
    df['network_overhead'] = df['network_overhead'].clip(lower=0) # 修正负数噪音
    
    # 取均值绘图
    avg_data = df.groupby(['resolution', 'fps']).mean().reset_index()
    
    fig, ax = plt.subplots(figsize=(10, 6))
    x = range(len(avg_data))
    labels = [f"{r}\n@{f}fps" for r, f in zip(avg_data['resolution'], avg_data['fps'])]
    
    # 堆叠柱状图：最底下是推理，中间是处理杂项，最上面是网络
    p1 = plt.bar(x, avg_data['inference_time'], label='AI Inference (GPU)', color='#ff9999')
    p2 = plt.bar(x, avg_data['process_time'] - avg_data['inference_time'], bottom=avg_data['inference_time'], label='Decode/Encode (CPU)', color='#66b3ff')
    p3 = plt.bar(x, avg_data['network_overhead'], bottom=avg_data['process_time'], label='Network RTT (Est.)', color='#99ff99')
    
    plt.xticks(x, labels)
    plt.ylabel("Latency (ms)")
    plt.title("Latency Composition Breakdown")
    plt.legend()
    plt.savefig(os.path.join(output_dir, "4_latency_composition.png"))
    plt.close()

    # ================= 图表 5: 负载影响 (散点图) =================
    # 看看画面里人越多，推理是不是越慢？
    plt.figure(figsize=(10, 6))
    sns.scatterplot(x='object_count', y='inference_time', hue='resolution', style='fps', data=df, s=100)
    plt.title("Impact of Object Count on Inference Speed")
    plt.xlabel("Detected Objects Count")
    plt.ylabel("Inference Time (ms)")
    plt.savefig(os.path.join(output_dir, "5_load_impact.png"))
    plt.close()

    # ================= 图表 6: 延迟分布 CDF (累积分布) =================
    # 回答百分之多少的样本之下的延迟，看是否达标
    fig, ax = plt.subplots(figsize=(10, 6))
    for name, group in df.groupby(['resolution', 'fps']):
        label = f"{name[0]} @ {name[1]}fps"
        plot_cdf(group, 'e2e_delay', ax, label)
    
    plt.title("Latency CDF (Cumulative Distribution Function)")
    plt.xlabel("Latency (ms)")
    plt.ylabel("Probability")
    plt.grid(True, which='both', linestyle='--', alpha=0.7)
    plt.legend()
    plt.savefig(os.path.join(output_dir, "6_latency_cdf.png"))
    plt.close()

    print(f"✅ [Batch {batch_size}] 6张图表已保存至: {output_dir}")

def main():
    print("🚀 开始生成深度分析图表...")
    if not os.path.exists("analysis_results"):
        os.makedirs("analysis_results")
        
    for size in BATCH_SIZES:
        analyze_single_file(size)
    print("\n🎉 全部图表生成完毕！请查看 analysis_results 文件夹。")

if __name__ == "__main__":
    main()