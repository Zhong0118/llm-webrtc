import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

# 读取数据
df = pd.read_csv('real_system_results.csv')

# 我们只需要取 tolerance_ms = 100 的行来进行对比（因为数据是一样的）
df_clean = df[df['tolerance_ms'] == 100.0].copy()

# 提取简短的标签用于画图
df_clean['Label'] = df_clean['desc'].apply(lambda x: x.split('.')[1].split('(')[0])
df_clean['Chunk'] = df_clean['chunk'].astype(str)

# 设置画图风格
plt.style.use('seaborn-v0_8')
fig, axes = plt.subplots(1, 3, figsize=(18, 6))

# 图 1: 视觉同步延迟 (Visual Drift)
# 结论：所有策略的延迟都很低 (<120ms)，证明了 "Flush" 机制的有效性
sns.barplot(x='Label', y='avg_drift', hue='Chunk', data=df_clean, ax=axes[0], palette='viridis')
axes[0].set_title('Visual Sync Latency (Lower is Better)')
axes[0].set_ylabel('Drift (ms)')
axes[0].set_xticklabels(axes[0].get_xticklabels(), rotation=45)

# 图 2: 服务器单次处理耗时 (Server Processing Time)
# 结论：Chunk 越大，攒帧时间越长，但这对用户延迟无影响
sns.barplot(x='Label', y='server_proc', hue='Chunk', data=df_clean, ax=axes[1], palette='magma')
axes[1].set_title('Server Processing Time (Collecting + Infer)')
axes[1].set_ylabel('Time (ms)')
axes[1].set_xticklabels(axes[1].get_xticklabels(), rotation=45)

# 图 3: AI 结果刷新数量 (Match Count)
# 结论：Chunk 越大，前端收到的结果越稀疏
sns.barplot(x='Label', y='match_count', hue='Chunk', data=df_clean, ax=axes[2], palette='Blues')
axes[2].set_title('AI Feedback Frequency (Higher = Smoother)')
axes[2].set_ylabel('Total Matches (in 20s)')
axes[2].set_xticklabels(axes[2].get_xticklabels(), rotation=45)

plt.tight_layout()
plt.show()