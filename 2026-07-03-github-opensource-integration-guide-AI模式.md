# GitHub 开源项目集成指南 — 精准药物设计系统

**版本**：v1.0  
**日期**：2026-07-03  
**关联文档**：[规格文档](../specs/2026-07-03-precision-drug-design-system-design.md) | [实现计划](../plans/2026-07-03-precision-drug-design-implementation-plan.md)

---

## 概述

GitHub 上充满了构建精准药物设计系统所需的"乐高积木"。本文档将系统所需的 11 个核心开源项目，按子系统映射，说明集成方式、使用场景和注意事项。

---

## 子系统 A：数据处理与分析

### 1. Scanpy — 单细胞数据分析核心引擎

| 属性 | 信息 |
|---|---|
| 仓库 | [scverse/scanpy](https://github.com/scverse/scanpy) |
| 最新版本 | 1.12.1 |
| 能力 | 可扩展至 >1 亿个细胞，支持 dask 处理超内存数据集 |
| 许可证 | BSD-3-Clause |

**在系统中的角色**：子系统 A 的单细胞数据处理核心，替代原方案中的 Scater 流程。

**核心集成方式**：

```python
import scanpy as sc
import anndata

# 读取 10x Genomics 数据
adata = sc.read_10x_h5("filtered_feature_bc_matrix.h5")

# 标准预处理流程
sc.pp.filter_cells(adata, min_genes=200)
sc.pp.filter_genes(adata, min_cells=3)
sc.pp.normalize_total(adata, target_sum=1e4)
sc.pp.log1p(adata)
sc.pp.highly_variable_genes(adata, n_top_genes=2000)

# 降维与聚类
sc.pp.pca(adata, n_comps=50)
sc.pp.neighbors(adata, n_neighbors=10)
sc.tl.umap(adata)
sc.tl.leiden(adata)

# 差异表达分析 — 识别高表达基因（靶点候选）
sc.tl.rank_genes_groups(adata, groupby="leiden")
```

**集成到系统**：
- `backend/app/services/parser/scrna.py` 中调用 Scanpy 处理 10x Genomics 数据
- 支持超大数据集的 dask 模式，解决 Sid 案例 60 万细胞的性能问题
- UMAP 可视化结果直接嵌入前端报告

### 2. BioPython — 生物数据格式解析

| 属性 | 信息 |
|---|---|
| 仓库 | [biopython/biopython](https://github.com/biopython/biopython) |
| 能力 | 解析 FASTA/FASTQ/PDB/GenBank 等生物数据格式 |
| 许可证 | Biopython License |

**在系统中的角色**：子系统 A 的多格式生物数据解析器。

**核心集成方式**：

```python
from Bio import SeqIO
from Bio import Entrez

# 解析 FASTA 文件
for record in SeqIO.parse("sequences.fasta", "fasta"):
    gene_id = record.id
    sequence = str(record.seq)

# 从 NCBI 获取基因信息
Entrez.email = "your@email.com"
handle = Entrez.efetch(db="gene", id="EGFR", rettype="gene_table")
```

**集成到系统**：
- `backend/app/services/parser/fasta_parser.py` 处理原始测序数据
- `backend/app/services/parser/vcf_parser.py` 中配合 cyvcf2 处理 VCF 变异文件

### 3. Nextflow — 数据分析工作流管理

| 属性 | 信息 |
|---|---|
| 仓库 | [nextflow-io/nextflow](https://github.com/nextflow-io/nextflow) |
| 生态 | nf-core 社区提供 100+ 生产级 pipeline |
| 能力 | 并行执行、容器化支持、云原生部署 |
| 许可证 | Apache-2.0 |

**在系统中的角色**：子系统 A 的标准化数据分析管道管理器。

**核心集成方式**：

```groovy
// nextflow/rna_seq_pipeline.nf
process RNA_SEQ_QC {
    container 'quay.io/biocontainers/scanpy:1.12.1'
    
    input:
    path fastq_file
    
    output:
    path "results/*"
    
    script:
    """
    scanpy-cli preprocess --input ${fastq_file} --output results/
    """
}

workflow {
    Channel.fromPath("data/*.fastq") | RNA_SEQ_QC
}
```

**集成到系统**：
- 替代自建数据处理管道，复用 nf-core 社区的 rnaseq、scrnaseq 等成熟 pipeline
- 支持 Docker/Singularity 容器化，确保分析可复现
- 第一阶段使用 nf-core/scrnaseq pipeline 快速搭建单细胞分析流程

---

## 子系统 B：AI 模型与分子设计

### 4. DeepChem — 深度学习药物发现

| 属性 | 信息 |
|---|---|
| 仓库 | [deepchem/deepchem](https://github.com/deepchem/deepchem) |
| 能力 | 内置大量药物发现模型和数据集，支持 GNN 预测分子性质 |
| 许可证 | MIT |

**在系统中的角色**：子系统 B 的核心深度学习框架，替代自建 MTL 模型。

**核心集成方式**：

```python
import deepchem as dc
from deepchem.models import GraphConvModel

# 训练分子活性预测模型
featurizer = dc.feat.ConvMolFeaturizer()
tasks = ["toxicity", "solubility", "bioactivity"]
loader = dc.data.CSVLoader(tasks=tasks, feature_field="smiles", featurizer=featurizer)
dataset = loader.create_dataset("molecules.csv")

model = GraphConvModel(
    n_tasks=len(tasks),
    graph_conv_layers=[64, 64],
    dense_layer_size=512,
    mode="regression"
)
model.fit(dataset, nb_epoch=50)

# 预测新分子
predictions = model.predict_on_batch(new_molecules)
```

**集成到系统**：
- `backend/app/services/analyzer/molecule_designer.py` 中用于性质预测
- 替代原方案的"MTL Transformer"自研模型，使用 DeepChem 内置的 GraphConvModel
- 内置 Tox21、ChEMBL 等数据集，加速模型训练

### 5. PyTorch Geometric (PyG) — 图神经网络

| 属性 | 信息 |
|---|---|
| 仓库 | [pyg-team/pytorch_geometric](https://github.com/pyg-team/pytorch_geometric) |
| 能力 | GraphSAGE/GAT/GIN 等图神经网络模型 |
| 许可证 | MIT |

**在系统中的角色**：子系统 B 的蛋白质互作网络（PPI）分析基础。

**核心集成方式**：

```python
import torch
from torch_geometric.nn import GraphSAGE, global_mean_pool
from torch_geometric.data import Data

# 构建蛋白质互作网络图
edge_index = torch.tensor(ppi_edges, dtype=torch.long)
node_features = torch.tensor(gene_expression_matrix, dtype=torch.float)
graph_data = Data(x=node_features, edge_index=edge_index.t().contiguous())

# GraphSAGE 识别关键节点
model = GraphSAGE(
    in_channels=node_features.size(1),
    hidden_channels=128,
    num_layers=3,
    out_channels=64
)
embeddings = model(graph_data.x, graph_data.edge_index)

# 基于嵌入识别关键调控节点（driver nodes）
node_importance = torch.norm(embeddings, dim=1)
top_targets = torch.topk(node_importance, k=20)
```

**集成到系统**：
- `backend/app/services/analyzer/network_modeler.py` 中使用
- 构建 STRING + Reactome 蛋白质互作网络，用 GNN 识别关键调控节点
- 识别多靶点组合的协同效应

### 6. RDKit — 化学信息学工具包

| 属性 | 信息 |
|---|---|
| 仓库 | [rdkit/rdkit](https://github.com/rdkit/rdkit) |
| 能力 | 分子操作、描述符计算、类药性评估、SMILES 解析 |
| 许可证 | BSD-3-Clause |

**在系统中的角色**：子系统 B 的化学信息学标准库。

**核心集成方式**：

```python
from rdkit import Chem
from rdkit.Chem import Descriptors, Lipinski, Crippen

# 分子类药性评估
def assess_druglikeness(smiles: str) -> dict:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return {"valid": False}
    
    return {
        "valid": True,
        "molecular_weight": Descriptors.MolWt(mol),
        "logp": Crippen.MolLogP(mol),
        "hbd": Lipinski.NumHDonors(mol),
        "hba": Lipinski.NumHAcceptors(mol),
        "rotatable_bonds": Descriptors.NumRotatableBonds(mol),
        "tpsa": Descriptors.TPSA(mol),
        "lipinski_pass": all([
            Descriptors.MolWt(mol) < 500,
            Crippen.MolLogP(mol) < 5,
            Lipinski.NumHDonors(mol) < 5,
            Lipinski.NumHAcceptors(mol) < 10
        ])
    }
```

**集成到系统**：
- 贯穿子系统 B 的所有分子操作
- 类药性预测、SMILES 解析、分子描述符计算
- 配合 DeepChem 做分子性质预测的预处理

### 7. DiffDock — 深度学习分子对接

| 属性 | 信息 |
|---|---|
| 仓库 | [gcorso/diffdock](https://github.com/gcorso/diffdock) |
| 架构 | 扩散模型 + 3D 等变图神经网络（2000 万参数） |
| 能力 | 预测小分子-蛋白质 3D 结合构象，state-of-the-art |
| 许可证 | MIT |

**在系统中的角色**：子系统 B 的分子对接引擎，作为 AutoDock Vina 的现代替代方案。

**核心集成方式**：

```python
# 使用 NVIDIA NIM 托管的 DiffDock API（推荐，无需本地 GPU）
import requests

def dock_molecule(protein_pdb: str, ligand_smiles: str) -> dict:
    response = requests.post(
        "https://integrate.api.nvidia.com/v1/genai/biology/mit/diffdock",
        json={
            "protein": protein_pdb,
            "ligand": ligand_smiles,
            "num_poses": 10,
            "diffusion_steps": 20
        },
        headers={"Authorization": f"Bearer {NIM_API_KEY}"}
    )
    return response.json()

# 或本地部署（需要 GPU）
# from diffdock.diffdock import DiffDock
# dock = DiffDock(checkpoint="models/diffdock.pt")
# poses = dock.dock(protein_pdb, ligand_smiles)
```

**集成到系统**：
- `backend/app/services/analyzer/molecule_designer.py` 中调用
- 替代原方案的 AutoDock Vina，精度更高
- 药物重定位阶段：验证已获批药物与新靶点的结合可能性
- 优先使用 NVIDIA NIM API（免本地 GPU），本地部署作为备选

---

## 子系统 B：知识库与数据检索

### 8. MyGene.info / MyVariant.info — 基因与变异注释 API

| 属性 | 信息 |
|---|---|
| 网站 | [mygene.info](https://mygene.info) / [myvariant.info](https://myvariant.info) |
| 能力 | 高速基因和变异注释，集成 ClinVar/COSMIC/dbSNP/gnomAD 等 15+ 数据源 |
| 认证 | 无需认证，免费（学术和商业使用） |
| 更新 | 每周自动更新 |

**在系统中的角色**：子系统 B 的基因/变异注释核心，替代自建 ClinVar/COSMIC 本地数据库。

**核心集成方式**：

```python
import requests

# 查询基因信息
def query_gene(gene_symbol: str) -> dict:
    resp = requests.get(
        f"https://mygene.info/v3/query",
        params={"q": f"symbol:{gene_symbol}", "fields": "all"}
    )
    return resp.json()

# 批量查询变异注释（ClinVar + COSMIC 一次搞定）
def query_variants(variant_list: list) -> list:
    resp = requests.post(
        "https://myvariant.info/v1/variant",
        json={"ids": ",".join(variant_list)},
        params={"fields": "clinvar,cosmic,dbsnp,gnomad"}
    )
    return resp.json()

# 示例：查询 EGFR T790M
variant_info = query_variants(["chr7:55259515:T>A"])
# 返回 ClinVar 临床意义、COSMIC 突变频率、gnomAD 人群频率
```

**集成到系统**：
- `backend/app/services/knowledge/clinvar.py` 和 `cosmic.py` 改为调用 MyVariant.info API
- 替代原方案每月下载 ClinVar VCF 的方式，改为实时查询
- 显著降低第一阶段知识库构建的工作量（无需本地部署 ClinVar/COSMIC）
- 大批量查询使用 POST 批量接口

### 9. ChEMBL — 生物活性分子数据库

| 属性 | 信息 |
|---|---|
| 网站 | [ebi.ac.uk/chembl](https://www.ebi.ac.uk/chembl/) |
| 能力 | 药物研发生物活性数据库，丰富的 REST API |
| 数据量 | 230 万+ 化合物，1.9 万+ 药物靶点 |
| 许可证 | CC BY-SA 3.0 |

**在系统中的角色**：子系统 B 的药物重定位和活性数据来源。

**核心集成方式**：

```python
import requests

# 查询靶点对应的已知活性分子
def get_active_molecules(target_gene: str) -> list:
    resp = requests.get(
        f"https://www.ebi.ac.uk/chembl/api/data/activity",
        params={
            "target_chembl_id": get_target_chembl_id(target_gene),
            "activity_type": "IC50",
            "order_by": "-activity_property",
            "format": "json",
            "limit": 50
        }
    )
    return resp.json()["activities"]

# 药物重定位：查找已获批药物
def find_approved_drugs_for_target(target_gene: str) -> list:
    resp = requests.get(
        f"https://www.ebi.ac.uk/chembl/api/data/drug_indication",
        params={"target_chembl_id": get_target_chembl_id(target_gene), "format": "json"}
    )
    return resp.json()["drug_indications"]
```

**集成到系统**：
- `backend/app/services/analyzer/drug_repurposer.py` 的核心数据源
- 药物重定位引擎优先从 ChEMBL 查询已获批药物
- 配合 DrugBank 数据交叉验证可药性

---

## 子系统 C/D：联邦学习与隐私计算

### 10. Flower — 联邦学习框架

| 属性 | 信息 |
|---|---|
| 仓库 | [adap/flower](https://github.com/adap/flower) |
| 能力 | 轻量级联邦学习框架，与 PyTorch/TF 无缝集成 |
| 许可证 | Apache-2.0 |

**在系统中的角色**：子系统 C 的多中心数据协作核心。

**核心集成方式**：

```python
import flwr as fl
import torch
from torch import nn

# 定义联邦学习客户端
class PharmaClient(fl.client.NumPyClient):
    def __init__(self, model, train_data, val_data):
        self.model = model
        self.train_data = train_data
        self.val_data = val_data
    
    def get_parameters(self):
        return [val.cpu().numpy() for val in self.model.parameters()]
    
    def set_parameters(self, parameters):
        params_dict = zip(self.model.state_dict().keys(), parameters)
        self.model.load_state_dict({k: torch.tensor(v) for k, v in params_dict})
    
    def fit(self, parameters, config):
        self.set_parameters(parameters)
        # 本地训练（数据不出域）
        train(self.model, self.train_data, epochs=config["epochs"])
        return self.get_parameters(), len(self.train_data), {}
    
    def evaluate(self, parameters, config):
        self.set_parameters(parameters)
        loss, accuracy = test(self.model, self.val_data)
        return loss, len(self.val_data), {"accuracy": accuracy}

# 启动联邦学习
fl.client.start_client(
    server_address="flower-server:8080",
    client=PharmaClient(model, train_data, val_data)
)
```

**集成到系统**：
- `backend/app/services/optimizer/federated_learning.py` 中使用
- 替代原方案的自研 DCPd 框架，改用 Flower + 自定义聚合策略
- 多中心药物研发数据协作：各医院/研究机构本地训练，模型参数聚合

### 11. PySyft — 隐私保护机器学习

| 属性 | 信息 |
|---|---|
| 仓库 | [OpenMined/PySyft](https://github.com/OpenMined/PySyft) |
| 能力 | 联邦学习 + 多方安全计算（MPC）+ 同态加密 |
| 许可证 | Apache-2.0 |

**在系统中的角色**：子系统 D 的隐私保护层。

**核心集成方式**：

```python
import syft as sy

# 启动隐私计算域
domain = sy.Domain(name="hospital_a")

# 注册数据集（数据所有者）
dataset = sy.Dataset(name="patient_genomics")
dataset.add_asset(
    name="rna_seq_data",
    data=patient_rna_data,
    mock=mock_data  # 供外部研究者验证代码
)
domain.load_dataset(dataset)

# 数据科学家远程分析（数据不出域）
guest_client = sy.login(url="hospital_a.openmined.org", port=8081)
result = guest_client.rna_seq_data.remote_compute(
    "find_targets",
    code=analysis_code
)
# result 是差分隐私保护下的分析结果
```

**集成到系统**：
- `backend/app/services/knowledge/privacy_layer.py` 中使用
- 敏感基因组数据的跨机构分析：数据不出域，只共享分析结果
- 配合 Flower 使用：PySyft 做数据隐私层，Flower 做联邦训练层

---

## 工具映射总览

| 子系统 | 原方案 | 开源替代 | 集成阶段 |
|---|---|---|---|
| A 单细胞处理 | Scater | **Scanpy** | 第一阶段 |
| A 生物数据解析 | BioPython | **BioPython**（沿用） | 第一阶段 |
| A 工作流管理 | Apache Flink（过重） | **Nextflow** + nf-core | 第一阶段 |
| B 深度学习 | 自研 MTL | **DeepChem** | 第二阶段 |
| B 图神经网络 | PyG（沿用） | **PyG**（沿用） | 第二阶段 |
| B 化学信息学 | RDKit（沿用） | **RDKit**（沿用） | 第一阶段 |
| B 分子对接 | AutoDock Vina | **DiffDock**（精度更高） | 第二阶段 |
| B 基因注释 | 本地 ClinVar/COSMIC | **MyGene/MyVariant API** | 第一阶段 |
| B 药物数据 | DrugBank | **ChEMBL API**（更丰富） | 第一阶段 |
| C 联邦学习 | 自研 DCPd | **Flower** | 第三阶段 |
| D 隐私计算 | TenSEAL | **PySyft**（更全面） | 第三阶段 |

---

## 第一阶段优先集成的工具

| 优先级 | 工具 | 原因 |
|---|---|---|
| P0 | Scanpy | 单细胞数据处理核心，直接替代 Scater |
| P0 | MyGene/MyVariant API | 免本地部署 ClinVar/COSMIC，省 2-3 周工作量 |
| P0 | ChEMBL API | 药物重定位核心数据源 |
| P0 | RDKit | 类药性评估标准库 |
| P0 | Nextflow + nf-core | 标准化数据处理管道，替代自建流程 |
| P1 | BioPython | 多格式解析（FASTA/VCF），按需引入 |
| P2 | DeepChem | 第二阶段分子设计核心 |
| P2 | PyG | 第二阶段网络建模 |
| P2 | DiffDock | 第二阶段分子对接 |
| P3 | Flower | 第三阶段联邦学习 |
| P3 | PySyft | 第三阶段隐私计算 |

---

## 依赖安装清单

### 第一阶段依赖

```txt
# backend/requirements.txt (第一阶段)
# --- 数据处理 ---
scanpy==1.12.1
anndata>=0.10.0
bioapi>=0.3.0
biopython>=1.83
cyvcf2>=0.30.28

# --- 化学信息学 ---
rdkit>=2024.3.1

# --- 知识库 API ---
requests>=2.31.0

# --- 工作流 ---
nextflow>=24.04.0

# --- Web 框架 ---
fastapi>=0.110.0
uvicorn>=0.27.0

# --- 数据库 ---
sqlalchemy>=2.0.0
asyncpg>=0.29.0
redis>=5.0.0

# --- 向量检索 ---
chromadb>=0.5.0

# --- 大模型 ---
litellm>=1.30.0
openai>=1.30.0

# --- CDISC ---
pandas>=2.2.0
```

### 第二阶段新增依赖

```txt
# --- 深度学习 ---
deepchem>=2.8.0
torch>=2.2.0
torch-geometric>=2.5.0

# --- 分子对接 ---
# DiffDock 通过 NVIDIA NIM API 调用，无需本地安装
# 如需本地部署：
# git clone https://github.com/gcorso/diffdock.git
# pip install -e diffdock/
```

### 第三阶段新增依赖

```txt
# --- 联邦学习 ---
flwr>=1.8.0

# --- 隐私计算 ---
syft>=0.9.0
```

---

**文档结束**

本指南与规格文档和实现计划配套使用，指导各阶段开源工具的集成。
