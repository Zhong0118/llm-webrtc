import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np

def plot():
    df = pd.read_csv('research_results.csv')
    sns.set_theme(style="whitegrid")
    
    # 图表 1: 帕累托权衡 (Trade-off): 延迟 vs 准确度 (假定 Confidence 代表准确度)
    # 这种图在论文里非常常见，展示“为了提高一点准确度，我们牺牲了多少延迟”
    # x是延迟，越往右越慢；y是准确度，越往上越好
    plt.figure(figsize=(10, 6))
    sns.scatterplot(data=df, x='d_an', y='mean_confidence', hue='chunk_size', size='chunk_size', sizes=(50, 200), palette="viridis")
    plt.title("Trade-off: Analysis Latency vs Confidence")
    plt.xlabel("Server Analysis Latency (ms) [Accumulation + Inference]")
    plt.ylabel("Mean Confidence (Accuracy Proxy)")
    plt.savefig("1_tradeoff.png")
    
    # 图表 2: 延迟构成分解 (Stacked Area)
    # 展示随着 Chunk Size 变大，哪部分延迟在变大？(肯定是堆积延迟变大了)
    # 随着 Chunk 变大，延迟增加主要是因为“等待数据”，而不是“计算变慢”
    df['waiting_time'] = df['d_an'] - df['inference_time']
    avg_df = df.groupby('experiment')[['inference_time', 'waiting_time']].mean().reset_index()
    # 为了排序好看，按 chunk_size 排序
    # (这里简化处理，实际代码可根据 chunk_size 列排序)
    
    avg_df.plot(x='experiment', y=['inference_time', 'waiting_time'], kind='bar', stacked=True, figsize=(10,6), colormap='viridis')
    plt.title("Latency Composition: Compute vs. Wait")
    plt.ylabel("Time (ms)")
    plt.xticks(rotation=15)
    plt.savefig("2_latency_composition.png")

    # --- [新增] 图表 3: 延迟分布 CDF (长尾效应分析) ---
    # 这是一个非常“高级”的图，证明你的系统在 99% 的情况下都稳定
    plt.figure(figsize=(10, 6))
    for exp_name in df['experiment'].unique():
        subset = df[df['experiment'] == exp_name]
        sorted_data = np.sort(subset['e2e_delay'])
        yvals = np.arange(len(sorted_data)) / float(len(sorted_data) - 1)
        plt.plot(sorted_data, yvals, label=exp_name, linewidth=2)
        
    plt.title("E2E Latency CDF (Cumulative Distribution)")
    plt.xlabel("Latency (ms)")
    plt.ylabel("Probability")
    plt.legend()
    plt.grid(True, linestyle='--', alpha=0.7)
    plt.savefig("3_latency_cdf.png")

    # --- [新增] 图表 4: 稳定性箱线图 (Stability) ---
    # 展示不同配置下，延迟的抖动范围。箱子越短，说明系统越稳。
    plt.figure(figsize=(10, 6))
    sns.boxplot(x='experiment', y='e2e_delay', data=df, palette="Set3")
    plt.title("Latency Stability Analysis")
    plt.ylabel("E2E Latency (ms)")
    plt.xticks(rotation=15)
    plt.savefig("4_stability_boxplot.png")

    print("✅ 4组科研级图表已生成！")

if __name__ == "__main__":
    plot()