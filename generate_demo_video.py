import cv2
import numpy as np
import os
from PIL import Image, ImageDraw, ImageFont
import time

def create_title_frame(title, subtitle, bg_color=(15, 15, 35), duration=30):
    frame = np.full((720, 1280, 3), bg_color, dtype=np.uint8)
    
    cv2.putText(frame, title, (640, 300), cv2.FONT_HERSHEY_SIMPLEX, 2.5, (0, 217, 255), 4, cv2.LINE_AA)
    cv2.putText(frame, subtitle, (640, 380), cv2.FONT_HERSHEY_SIMPLEX, 1, (123, 47, 247), 2, cv2.LINE_AA)
    
    return [frame] * duration

def create_section_frame(title, features, bg_color=(15, 15, 35), duration=40):
    frame = np.full((720, 1280, 3), bg_color, dtype=np.uint8)
    
    cv2.putText(frame, title, (640, 100), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 217, 255), 3, cv2.LINE_AA)
    
    y_pos = 200
    for i, feature in enumerate(features):
        cv2.putText(frame, f"{i+1}. {feature}", (100, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2, cv2.LINE_AA)
        y_pos += 60
    
    return [frame] * duration

def create_stats_frame(stats, bg_color=(15, 15, 35), duration=30):
    frame = np.full((720, 1280, 3), bg_color, dtype=np.uint8)
    
    cv2.putText(frame, "系统核心指标", (640, 100), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 217, 255), 3, cv2.LINE_AA)
    
    cols = 4
    x_start = 100
    x_step = 270
    y_pos = 250
    
    for i, (label, value) in enumerate(stats.items()):
        x = x_start + (i % cols) * x_step
        y = y_pos + (i // cols) * 150
        
        cv2.putText(frame, value, (x + 60, y), cv2.FONT_HERSHEY_SIMPLEX, 2.5, (123, 47, 247), 4, cv2.LINE_AA)
        cv2.putText(frame, label, (x + 20, y + 60), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200, 200, 200), 1, cv2.LINE_AA)
    
    return [frame] * duration

def create_workflow_frame(steps, bg_color=(15, 15, 35), duration=50):
    frame = np.full((720, 1280, 3), bg_color, dtype=np.uint8)
    
    cv2.putText(frame, "工作流程", (640, 80), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 217, 255), 3, cv2.LINE_AA)
    
    x_start = 80
    x_step = 290
    
    for i, step in enumerate(steps):
        x = x_start + i * x_step
        
        cv2.circle(frame, (x + 70, 250), 50, (0, 217, 255), -1)
        cv2.putText(frame, str(i+1), (x + 70, 265), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 0), 2, cv2.LINE_AA)
        
        cv2.putText(frame, step, (x + 10, 340), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 1, cv2.LINE_AA)
        
        if i < len(steps) - 1:
            cv2.line(frame, (x + 120, 250), (x + 160, 250), (123, 47, 247), 3)
            cv2.arrowedLine(frame, (x + 120, 250), (x + 160, 250), (123, 47, 247), 3)
    
    return [frame] * duration

def create_evidence_frame(levels, bg_color=(15, 15, 35), duration=35):
    frame = np.full((720, 1280, 3), bg_color, dtype=np.uint8)
    
    cv2.putText(frame, "证据等级体系", (640, 80), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 217, 255), 3, cv2.LINE_AA)
    
    colors = [(0, 255, 0), (0, 217, 255), (123, 47, 247), (255, 255, 0)]
    y_pos = 180
    
    for i, (level, desc) in enumerate(levels):
        cv2.circle(frame, (100, y_pos), 15, colors[i], -1)
        cv2.putText(frame, f"{level}: {desc}", (140, y_pos + 5), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 2, cv2.LINE_AA)
        y_pos += 80
    
    return [frame] * duration

def create_molecule_frame(molecules, bg_color=(15, 15, 35), duration=40):
    frame = np.full((720, 1280, 3), bg_color, dtype=np.uint8)
    
    cv2.putText(frame, "分子设计结果", (640, 80), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 217, 255), 3, cv2.LINE_AA)
    
    y_pos = 200
    for molecule in molecules:
        cv2.putText(frame, molecule["name"], (100, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (123, 47, 247), 2, cv2.LINE_AA)
        cv2.putText(frame, f"SMILES: {molecule['smiles']}", (100, y_pos + 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200, 200, 200), 1, cv2.LINE_AA)
        cv2.putText(frame, f"结合亲和力: {molecule['affinity']}", (100, y_pos + 80), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 1, cv2.LINE_AA)
        y_pos += 140
    
    return [frame] * duration

def create_chat_frame(messages, bg_color=(15, 15, 35), duration=50):
    frame = np.full((720, 1280, 3), bg_color, dtype=np.uint8)
    
    cv2.putText(frame, "AI智能问答", (640, 80), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 217, 255), 3, cv2.LINE_AA)
    
    y_pos = 160
    for msg in messages:
        if msg["role"] == "user":
            cv2.rectangle(frame, (50, y_pos), (1230, y_pos + 80), (30, 30, 50), -1)
            cv2.putText(frame, f"用户: {msg['content']}", (80, y_pos + 45), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 1, cv2.LINE_AA)
        else:
            cv2.rectangle(frame, (50, y_pos), (1230, y_pos + 100), (20, 40, 60), -1)
            cv2.putText(frame, f"AI助手: {msg['content']}", (80, y_pos + 45), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 217, 255), 1, cv2.LINE_AA)
        y_pos += 110
    
    return [frame] * duration

def create_hypothesis_frame(hypotheses, bg_color=(15, 15, 35), duration=40):
    frame = np.full((720, 1280, 3), bg_color, dtype=np.uint8)
    
    cv2.putText(frame, "多假设并行管理", (640, 80), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 217, 255), 3, cv2.LINE_AA)
    
    colors = [(0, 255, 0), (0, 217, 255), (123, 47, 247), (100, 100, 100)]
    y_pos = 180
    
    for i, hyp in enumerate(hypotheses):
        cv2.rectangle(frame, (50, y_pos), (1230, y_pos + 70), (30, 30, 50), -1)
        cv2.rectangle(frame, (50, y_pos), (100, y_pos + 70), colors[i], -1)
        cv2.putText(frame, hyp["name"], (120, y_pos + 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(frame, hyp["status"], (1000, y_pos + 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, colors[i], 1, cv2.LINE_AA)
        y_pos += 90
    
    return [frame] * duration

def create_federated_frame(nodes, stats, bg_color=(15, 15, 35), duration=35):
    frame = np.full((720, 1280, 3), bg_color, dtype=np.uint8)
    
    cv2.putText(frame, "联邦学习网络", (640, 80), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 217, 255), 3, cv2.LINE_AA)
    
    cv2.circle(frame, (640, 360), 60, (123, 47, 247), -1)
    cv2.putText(frame, "中心节点", (600, 370), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 1, cv2.LINE_AA)
    
    positions = [(200, 200), (1080, 200), (200, 520), (1080, 520)]
    
    for i, (pos, node) in enumerate(zip(positions, nodes)):
        cv2.circle(frame, pos, 40, (0, 217, 255), -1)
        cv2.putText(frame, node, (pos[0] - 30, pos[1] + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 1, cv2.LINE_AA)
        cv2.line(frame, pos, (640, 360), (123, 47, 247), 2)
    
    y_pos = 620
    for label, value in stats.items():
        cv2.putText(frame, f"{label}: {value}", (50, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200, 200, 200), 1, cv2.LINE_AA)
        y_pos += 30
    
    return [frame] * duration

def create_footer_frame(bg_color=(15, 15, 35), duration=20):
    frame = np.full((720, 1280, 3), bg_color, dtype=np.uint8)
    
    cv2.putText(frame, "AI精准药物设计系统", (640, 300), cv2.FONT_HERSHEY_SIMPLEX, 2.5, (0, 217, 255), 4, cv2.LINE_AA)
    cv2.putText(frame, "精准医疗 · 智能研发", (640, 380), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (123, 47, 247), 2, cv2.LINE_AA)
    cv2.putText(frame, "感谢观看", (640, 480), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 2, cv2.LINE_AA)
    
    return [frame] * duration

def main():
    frames = []
    
    frames.extend(create_title_frame("AI精准药物设计系统", "AI-Driven Precision Drug Design System"))
    
    frames.extend(create_stats_frame({
        "数据类型": "12+",
        "靶点识别": "100+",
        "分子设计": "500+",
        "评估准确率": "99%",
        "实验案例": "156",
        "迭代轮次": "8",
        "响应时间": "<5s",
        "系统稳定性": "99.9%"
    }))
    
    frames.extend(create_section_frame("多组学数据管理平台", [
        "支持RNA-seq、scRNA-seq、WES、WGS、VCF、FASTA等12种数据类型",
        "自动数据质量评估报告（测序深度、GC含量、重复率）",
        "差异表达分析、聚类分析、功能富集分析自动化流程",
        "数据导入导出支持多种格式（CSV、Excel、JSON、NDJSON）"
    ]))
    
    frames.extend(create_workflow_frame(["数据上传", "质量评估", "生信分析", "结果可视化"]))
    
    frames.extend(create_section_frame("AI靶点发现引擎", [
        "多组学数据整合与差异表达分析",
        "GO/KEGG功能富集分析筛选关键通路",
        "四级证据链构建（临床/实验/计算/文献）",
        "老药新用扫描，药物重定位预测"
    ]))
    
    frames.extend(create_evidence_frame([
        ("I级证据", "临床验证 - 最高可信度"),
        ("II级证据", "实验验证 - 体外/体内实验"),
        ("III级证据", "计算预测 - AI模型预测"),
        ("IV级证据", "文献支持 - 文献挖掘证据")
    ]))
    
    frames.extend(create_section_frame("分子设计与类药性评估", [
        "Lipinski五规则评估（分子量、脂溶性、氢键供体/受体）",
        "Veber规则评估（可旋转键数、拓扑极性表面积）",
        "ADMET预测（吸收、分布、代谢、排泄、毒性）",
        "多靶点协同设计，分子结构3D可视化"
    ]))
    
    frames.extend(create_molecule_frame([
        {"name": "EGFR抑制剂候选分子", "smiles": "CCOc1ccc2c(c1)C(=O)N2C(=O)C(=O)N", "affinity": "9.2 nM"},
        {"name": "ALK抑制剂候选分子", "smiles": "CC(C)N1CCN(CC1)C(=O)c2ccccc2", "affinity": "7.8 nM"}
    ]))
    
    frames.extend(create_section_frame("多假设并行管理", [
        "同时创建多个治疗假设，独立分析对比",
        "AI自动生成科学假设（描述、证据、验证方法）",
        "假设优先级排序与淘汰机制",
        "一键流水线整合假设生成与验证"
    ]))
    
    frames.extend(create_hypothesis_frame([
        {"name": "假设A: EGFR抑制剂联合免疫治疗", "status": "验证中"},
        {"name": "假设B: ALK抑制剂单独治疗", "status": "分析中"},
        {"name": "假设C: 多靶点联合治疗方案", "status": "待评估"},
        {"name": "假设D: 传统化疗方案", "status": "已淘汰"}
    ]))
    
    frames.extend(create_section_frame("干湿实验闭环", [
        "湿实验→数据分析→干实验预测→临床验证完整闭环",
        "实验结果回流更新AI模型参数",
        "预测值vs实测值对比分析",
        "患者疗效反馈机制与数据收集"
    ]))
    
    frames.extend(create_workflow_frame(["湿实验数据", "生信分析", "AI预测", "临床验证"]))
    
    frames.extend(create_section_frame("AI智能问答系统", [
        "分级路由：快速筛查/深度洞察自适应",
        "RAG检索增强生成，知识图谱整合",
        "专业医学问题解答与证据引用",
        "多轮对话支持，上下文记忆"
    ]))
    
    frames.extend(create_chat_frame([
        {"role": "user", "content": "什么是EGFR基因突变？"},
        {"role": "assistant", "content": "EGFR是表皮生长因子受体，其突变在肺癌中约占15-20%，是重要的治疗靶点"}
    ]))
    
    frames.extend(create_section_frame("联邦学习平台", [
        "去中心化模型训练，数据隐私保护",
        "多中心协作，跨机构知识共享",
        "动态模型更新与性能监控",
        "合规数据隐私保护，符合GDPR"
    ]))
    
    frames.extend(create_federated_frame(
        ["医院A", "医院B", "研究院C", "药企D"],
        {"参与节点": "4个", "训练轮次": "100+", "数据规模": "10万+样本", "模型精度": "95%"}
    ))
    
    frames.extend(create_section_frame("系统特色功能", [
        "断点续传：分析管道支持断点恢复",
        "结果可复现：完整数据血缘追踪",
        "多格式导出：支持CDISC SDTM/ADaM标准",
        "实时监控：联邦学习节点性能监控"
    ]))
    
    frames.extend(create_footer_frame())
    
    height, width = frames[0].shape[:2]
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter('AI精准药物设计系统演示视频.mp4', fourcc, 10.0, (width, height))
    
    for frame in frames:
        out.write(frame)
    
    out.release()
    print("视频生成完成！文件: AI精准药物设计系统演示视频.mp4")
    print(f"总帧数: {len(frames)}")
    print(f"视频时长: {len(frames) / 10:.1f} 秒")

if __name__ == "__main__":
    main()