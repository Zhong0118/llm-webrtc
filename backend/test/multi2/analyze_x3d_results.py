"""
X3D Experiment Results Analysis and Visualization
===================================================

这个脚本分析 X3D-S 实验的结果并生成可视化图表。

分析内容：
1. Visual Drift (视觉漂移): AI 结果与 P2P 视频的时间差
2. Server Processing Time (服务器处理时间): 端到端延迟
3. Match Rate (匹配率): AI 能跟上视频的比率
4. Inference Time (推理时间): 纯模型计算时间

对比维度：
- 不同 chunk_size 的影响
- 不同 stride 的影响
- 延迟分解（Chunk 等待时间 vs 推理时间）

作者: AI Toolkit Assistant
日期: 2025-12-16
"""

import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
from pathlib import Path
import sys

# ============================================================
# 配置
# ============================================================
# 设置中文字体（解决 matplotlib 中文显示问题）
plt.rcParams['font.sans-serif'] = ['SimHei', 'Arial Unicode MS', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题

# 设置 Seaborn 风格
sns.set_style("whitegrid")
sns.set_palette("husl")

# 图表尺寸
FIGURE_SIZE = (16, 12)


# ============================================================
# 数据加载
# ============================================================
def load_experiment_results(csv_file: str) -> pd.DataFrame:
    """
    加载实验结果 CSV 文件
    
    Args:
        csv_file: CSV 文件路径
    
    Returns:
        pd.DataFrame: 实验结果数据
    """
    try:
        df = pd.read_csv(csv_file)
        print(f"✅ 成功加载数据: {csv_file}")
        print(f"   实验配置数量: {len(df)}")
        print(f"   列名: {list(df.columns)}")
        return df
    except FileNotFoundError:
        print(f"❌ 文件不存在: {csv_file}")
        print("请先运行 full_system_x3d_test.py 生成实验数据")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 加载数据失败: {e}")
        sys.exit(1)


# ============================================================
# 数据预处理
# ============================================================
def preprocess_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    数据预处理：添加辅助列用于可视化
    
    Args:
        df: 原始数据
    
    Returns:
        pd.DataFrame: 处理后的数据
    """
    # 1. 提取简短标签（用于 X 轴）
    df['config_label'] = df['desc'].apply(
        lambda x: x.split('.')[1].split('(')[0].strip() if '.' in str(x) else str(x)
    )
    
    # 2. 添加组合标签（chunk-stride）
    df['config_tag'] = df.apply(
        lambda row: f"{row['chunk_size']}-{row['stride']}", 
        axis=1
    )
    
    # 3. 计算 chunk 等待时间（假设 30fps）
    # chunk_wait_time = chunk_size / fps * 1000 (ms)
    fps = 30
    df['chunk_wait_time'] = (df['chunk_size'] / fps) * 1000
    
    # 4. 计算理论最小延迟
    # 理论延迟 = chunk_wait_time + avg_inference
    df['theoretical_min_latency'] = df['chunk_wait_time'] + df['avg_inference']
    
    # 5. 分类 chunk_size（用于分组）
    df['chunk_category'] = pd.cut(
        df['chunk_size'],
        bins=[0, 10, 20, 50],
        labels=['Short (≤10)', 'Medium (11-20)', 'Long (>20)']
    )
    
    print("\n📊 数据预处理完成:")
    print(df[['config_label', 'chunk_size', 'stride', 'avg_drift', 'avg_d_an']].to_string())
    
    return df


# ============================================================
# 可视化函数
# ============================================================
def plot_comprehensive_analysis(df: pd.DataFrame, output_dir: str = "."):
    """
    生成综合分析图表（4 子图）
    
    Args:
        df: 实验数据
        output_dir: 输出目录
    """
    fig, axes = plt.subplots(2, 2, figsize=FIGURE_SIZE)
    fig.suptitle('X3D-S Experiment Results: Comprehensive Analysis', 
                 fontsize=16, fontweight='bold')
    
    # --------------------------------------------------------
    # 图1: Visual Drift (视觉漂移)
    # --------------------------------------------------------
    ax1 = axes[0, 0]
    
    # 使用柱状图展示平均漂移，误差线表示标准差
    x_pos = np.arange(len(df))
    bars = ax1.bar(
        x_pos, 
        df['avg_drift'], 
        yerr=df['std_drift'],
        capsize=5,
        alpha=0.7,
        color=sns.color_palette("viridis", len(df))
    )
    
    ax1.set_xlabel('Configuration', fontweight='bold')
    ax1.set_ylabel('Average Drift (ms)', fontweight='bold')
    ax1.set_title('Visual Sync Latency (Lower is Better)', fontweight='bold')
    ax1.set_xticks(x_pos)
    ax1.set_xticklabels(df['config_tag'], rotation=45, ha='right')
    ax1.grid(axis='y', alpha=0.3)
    
    # 添加数值标签
    for i, (bar, val) in enumerate(zip(bars, df['avg_drift'])):
        ax1.text(bar.get_x() + bar.get_width()/2, val + df['std_drift'].iloc[i], 
                f'{val:.0f}', ha='center', va='bottom', fontsize=9)
    
    # --------------------------------------------------------
    # 图2: Server Processing Time (服务器延迟)
    # --------------------------------------------------------
    ax2 = axes[0, 1]
    
    # 堆叠柱状图：分解为 chunk_wait + inference
    width = 0.6
    
    # 注意：d_an 包含了 chunk_wait + inference + 其他开销
    # 这里我们展示理论值和实际值的对比
    ax2.bar(x_pos, df['chunk_wait_time'], width, label='Chunk Wait (Theory)', alpha=0.5)
    ax2.bar(x_pos, df['avg_inference'], width, bottom=df['chunk_wait_time'], 
            label='Inference Time', alpha=0.7)
    ax2.scatter(x_pos, df['avg_d_an'], color='red', s=100, zorder=5, 
                label='Actual D_an', marker='D')
    
    ax2.set_xlabel('Configuration', fontweight='bold')
    ax2.set_ylabel('Time (ms)', fontweight='bold')
    ax2.set_title('Server Processing Time Breakdown', fontweight='bold')
    ax2.set_xticks(x_pos)
    ax2.set_xticklabels(df['config_tag'], rotation=45, ha='right')
    ax2.legend(loc='upper left')
    ax2.grid(axis='y', alpha=0.3)
    
    # --------------------------------------------------------
    # 图3: Match Rate (匹配率)
    # --------------------------------------------------------
    ax3 = axes[1, 0]
    
    # 计算匹配率（如果数据中有）
    if 'match_rate' in df.columns:
        match_rate = df['match_rate'] * 100  # 转为百分比
    else:
        # 简化计算：match_count / total_ai_frames
        match_rate = (df['match_count'] / df['total_ai_frames']) * 100
    
    bars = ax3.bar(x_pos, match_rate, alpha=0.7, color='skyblue', edgecolor='navy')
    ax3.axhline(y=100, color='green', linestyle='--', label='Perfect Match (100%)')
    
    ax3.set_xlabel('Configuration', fontweight='bold')
    ax3.set_ylabel('Match Rate (%)', fontweight='bold')
    ax3.set_title('AI-Video Synchronization Rate (Higher is Better)', fontweight='bold')
    ax3.set_xticks(x_pos)
    ax3.set_xticklabels(df['config_tag'], rotation=45, ha='right')
    ax3.set_ylim([0, 105])
    ax3.legend()
    ax3.grid(axis='y', alpha=0.3)
    
    # 添加数值标签
    for i, (bar, val) in enumerate(zip(bars, match_rate)):
        ax3.text(bar.get_x() + bar.get_width()/2, val + 2, 
                f'{val:.1f}%', ha='center', va='bottom', fontsize=9)
    
    # --------------------------------------------------------
    # 图4: Throughput (吞吐量)
    # --------------------------------------------------------
    ax4 = axes[1, 1]
    
    # 计算吞吐量：match_count / duration（假设每个实验 30 秒）
    duration = 30  # 秒
    throughput = df['match_count'] / duration
    
    ax4.plot(x_pos, throughput, marker='o', linewidth=2, markersize=8, 
             color='green', label='AI Results per Second')
    ax4.fill_between(x_pos, 0, throughput, alpha=0.3, color='green')
    
    # 添加理论上限（30 fps）
    ax4.axhline(y=30, color='red', linestyle='--', label='Video FPS (30)')
    
    ax4.set_xlabel('Configuration', fontweight='bold')
    ax4.set_ylabel('AI Results / Second', fontweight='bold')
    ax4.set_title('AI Processing Throughput', fontweight='bold')
    ax4.set_xticks(x_pos)
    ax4.set_xticklabels(df['config_tag'], rotation=45, ha='right')
    ax4.legend()
    ax4.grid(True, alpha=0.3)
    
    # --------------------------------------------------------
    # 保存图表
    # --------------------------------------------------------
    plt.tight_layout()
    output_path = Path(output_dir) / "x3d_comprehensive_analysis.png"
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"\n✅ 图表已保存: {output_path}")
    
    plt.show()


def plot_chunk_vs_stride_heatmap(df: pd.DataFrame, output_dir: str = "."):
    """
    生成 Chunk Size vs Stride 的热力图（展示延迟）
    
    Args:
        df: 实验数据
        output_dir: 输出目录
    """
    # 创建透视表
    pivot_drift = df.pivot_table(
        values='avg_drift',
        index='chunk_size',
        columns='stride',
        aggfunc='mean'
    )
    
    pivot_d_an = df.pivot_table(
        values='avg_d_an',
        index='chunk_size',
        columns='stride',
        aggfunc='mean'
    )
    
    # 创建图表
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    fig.suptitle('Chunk Size vs Stride: Latency Heatmap', fontsize=14, fontweight='bold')
    
    # 热力图1: Visual Drift
    sns.heatmap(
        pivot_drift, 
        annot=True, 
        fmt='.1f', 
        cmap='YlOrRd',
        cbar_kws={'label': 'Drift (ms)'},
        ax=axes[0]
    )
    axes[0].set_title('Visual Drift', fontweight='bold')
    axes[0].set_xlabel('Stride', fontweight='bold')
    axes[0].set_ylabel('Chunk Size', fontweight='bold')
    
    # 热力图2: Server Delay (D_an)
    sns.heatmap(
        pivot_d_an, 
        annot=True, 
        fmt='.1f', 
        cmap='Blues',
        cbar_kws={'label': 'D_an (ms)'},
        ax=axes[1]
    )
    axes[1].set_title('Server Processing Time (D_an)', fontweight='bold')
    axes[1].set_xlabel('Stride', fontweight='bold')
    axes[1].set_ylabel('Chunk Size', fontweight='bold')
    
    plt.tight_layout()
    output_path = Path(output_dir) / "x3d_heatmap_analysis.png"
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"✅ 热力图已保存: {output_path}")
    
    plt.show()


def plot_latency_decomposition(df: pd.DataFrame, output_dir: str = "."):
    """
    延迟分解图：展示延迟的各个组成部分
    
    Args:
        df: 实验数据
        output_dir: 输出目录
    """
    fig, ax = plt.subplots(figsize=(12, 6))
    
    x_pos = np.arange(len(df))
    width = 0.5
    
    # 计算各部分延迟
    # 注意：这是简化模型，实际延迟还包括网络传输等
    chunk_wait = df['chunk_wait_time']
    inference = df['avg_inference']
    other = df['avg_d_an'] - df['chunk_wait_time'] - df['avg_inference']
    other = other.clip(lower=0)  # 避免负值
    
    # 堆叠柱状图
    p1 = ax.bar(x_pos, chunk_wait, width, label='Chunk Wait Time', color='#FF6B6B')
    p2 = ax.bar(x_pos, inference, width, bottom=chunk_wait, 
                label='Inference Time', color='#4ECDC4')
    p3 = ax.bar(x_pos, other, width, 
                bottom=chunk_wait + inference,
                label='Other Overhead', color='#95E1D3')
    
    # 添加总延迟线
    ax.plot(x_pos, df['avg_d_an'], 'ro-', linewidth=2, markersize=8, 
            label='Total D_an (Measured)', zorder=5)
    
    ax.set_xlabel('Configuration', fontweight='bold', fontsize=12)
    ax.set_ylabel('Latency (ms)', fontweight='bold', fontsize=12)
    ax.set_title('Latency Decomposition Analysis', fontweight='bold', fontsize=14)
    ax.set_xticks(x_pos)
    ax.set_xticklabels(df['config_tag'], rotation=45, ha='right')
    ax.legend(loc='upper left', fontsize=10)
    ax.grid(axis='y', alpha=0.3)
    
    # 添加公式说明
    formula_text = (
        "Latency Formula:\n"
        "D_an = T_chunk + T_infer + T_overhead\n"
        "T_chunk = chunk_size / fps"
    )
    ax.text(0.98, 0.98, formula_text, transform=ax.transAxes,
            fontsize=9, verticalalignment='top', horizontalalignment='right',
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    
    plt.tight_layout()
    output_path = Path(output_dir) / "x3d_latency_decomposition.png"
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"✅ 延迟分解图已保存: {output_path}")
    
    plt.show()


def generate_summary_report(df: pd.DataFrame, output_dir: str = "."):
    """
    生成文本摘要报告
    
    Args:
        df: 实验数据
        output_dir: 输出目录
    """
    report_lines = []
    report_lines.append("=" * 70)
    report_lines.append("X3D-S EXPERIMENT SUMMARY REPORT")
    report_lines.append("=" * 70)
    report_lines.append("")
    
    # 1. 最佳配置
    best_drift_idx = df['avg_drift'].idxmin()
    best_throughput_idx = df['match_count'].idxmax()
    
    report_lines.append("🏆 BEST CONFIGURATIONS:")
    report_lines.append("-" * 70)
    report_lines.append(f"Lowest Visual Drift: {df.loc[best_drift_idx, 'desc']}")
    report_lines.append(f"  - Drift: {df.loc[best_drift_idx, 'avg_drift']:.1f} ms")
    report_lines.append(f"  - Config: chunk={df.loc[best_drift_idx, 'chunk_size']}, "
                       f"stride={df.loc[best_drift_idx, 'stride']}")
    report_lines.append("")
    report_lines.append(f"Highest Throughput: {df.loc[best_throughput_idx, 'desc']}")
    report_lines.append(f"  - Matches: {df.loc[best_throughput_idx, 'match_count']}")
    report_lines.append(f"  - Config: chunk={df.loc[best_throughput_idx, 'chunk_size']}, "
                       f"stride={df.loc[best_throughput_idx, 'stride']}")
    report_lines.append("")
    
    # 2. 统计摘要
    report_lines.append("📊 STATISTICAL SUMMARY:")
    report_lines.append("-" * 70)
    report_lines.append(f"Total Experiments: {len(df)}")
    report_lines.append(f"Average Visual Drift: {df['avg_drift'].mean():.1f} ms "
                       f"(±{df['avg_drift'].std():.1f})")
    report_lines.append(f"Average Server Delay (D_an): {df['avg_d_an'].mean():.1f} ms "
                       f"(±{df['avg_d_an'].std():.1f})")
    report_lines.append(f"Average Inference Time: {df['avg_inference'].mean():.1f} ms "
                       f"(±{df['avg_inference'].std():.1f})")
    report_lines.append("")
    
    # 3. 关键发现
    report_lines.append("🔍 KEY FINDINGS:")
    report_lines.append("-" * 70)
    
    # 分析 chunk_size 的影响
    corr_chunk_drift = df['chunk_size'].corr(df['avg_drift'])
    report_lines.append(f"1. Chunk Size vs Drift Correlation: {corr_chunk_drift:.3f}")
    if corr_chunk_drift > 0.5:
        report_lines.append("   → Larger chunks lead to HIGHER drift")
    elif corr_chunk_drift < -0.5:
        report_lines.append("   → Larger chunks lead to LOWER drift")
    else:
        report_lines.append("   → Weak correlation")
    
    # 分析 stride 的影响
    corr_stride_throughput = df['stride'].corr(df['match_count'])
    report_lines.append(f"2. Stride vs Throughput Correlation: {corr_stride_throughput:.3f}")
    if corr_stride_throughput < -0.5:
        report_lines.append("   → Smaller stride leads to MORE AI results")
    
    report_lines.append("")
    report_lines.append("=" * 70)
    
    # 打印到控制台
    report_text = "\n".join(report_lines)
    print(report_text)
    
    # 保存到文件
    output_path = Path(output_dir) / "x3d_summary_report.txt"
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(report_text)
    
    print(f"\n✅ 摘要报告已保存: {output_path}")


# ============================================================
# 主函数
# ============================================================
def main(csv_file: str = None, output_dir: str = "."):
    """
    主分析流程
    
    Args:
        csv_file: 实验结果 CSV 文件路径（如果为 None，自动查找）
        output_dir: 输出目录
    """
    print("="*70)
    print("🔬 X3D-S Experiment Results Analysis")
    print("="*70)
    
    # 1. 查找 CSV 文件
    if csv_file is None:
        # 查找当前目录下最新的 CSV 文件
        csv_files = list(Path(".").glob("x3d_experiment_results_*.csv"))
        if not csv_files:
            print("❌ 未找到实验结果文件（x3d_experiment_results_*.csv）")
            print("请先运行 full_system_x3d_test.py")
            return
        
        csv_file = max(csv_files, key=lambda p: p.stat().st_mtime)
        print(f"📂 自动选择最新文件: {csv_file}")
    
    # 2. 加载数据
    df = load_experiment_results(csv_file)
    
    # 3. 预处理
    df = preprocess_data(df)
    
    # 4. 生成图表
    print("\n📈 生成可视化图表...")
    
    try:
        plot_comprehensive_analysis(df, output_dir)
        plot_chunk_vs_stride_heatmap(df, output_dir)
        plot_latency_decomposition(df, output_dir)
    except Exception as e:
        print(f"⚠️ 图表生成部分失败: {e}")
        import traceback
        traceback.print_exc()
    
    # 5. 生成摘要报告
    print("\n📝 生成摘要报告...")
    generate_summary_report(df, output_dir)
    
    print("\n" + "="*70)
    print("✅ 分析完成！")
    print("="*70)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='分析 X3D-S 实验结果')
    parser.add_argument('--csv', type=str, default=None, 
                       help='实验结果 CSV 文件路径（默认：自动查找最新文件）')
    parser.add_argument('--output', type=str, default=".", 
                       help='输出目录（默认：当前目录）')
    
    args = parser.parse_args()
    
    main(csv_file=args.csv, output_dir=args.output)
