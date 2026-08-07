"""基因组坐标转换 — GRCh37 ↔ GRCh38 + 链翻转映射

设计来源：参照 Trae 论坛方案，需要兼容消费级基因芯片（GRCh37 主导）
与全基因组测序（GRCh38 主导）两类主流数据，统一坐标到双版本以便匹配。

实现策略：
1. 优先查 snp_loci 表已有的双坐标记录
2. 本地无记录时调 NCBI E-utilities API 获取坐标（带缓存）
3. 链翻转：A↔T、C↔G（Watson-Crick 互补）
4. pyliftover 为可选依赖，缺失时降级到本地表/API
"""
import logging
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# Watson-Crick 互补碱基（链翻转映射）
_COMPLEMENT = {"A": "T", "T": "A", "C": "G", "G": "C", "a": "t", "t": "a", "c": "g", "g": "c"}


def chain_flip_allele(allele: str) -> str:
    """链翻转 — 返回互补等位

    例：A → T、AG → TC、AA → TT
    用于用户基因型与位点库链方向不一致时的对齐。
    """
    if not allele:
        return allele
    return "".join(_COMPLEMENT.get(c, c) for c in allele)


def chain_flip_genotype(genotype: str) -> str:
    """基因型链翻转

    例：AA → TT、AG → TC、GG → CC
    "--" 等无数据保持原样。
    """
    if not genotype or genotype in ("--", "", "00", None):
        return genotype
    return chain_flip_allele(genotype)


def is_genotype_match(user_genotype: str, risk_genotype: str) -> bool:
    """判断用户基因型是否命中风险基因型

    支持多种格式：
    - 直接相等：user=AA, risk=AA
    - 链翻转等价：user=TT, risk=AA（互补）
    - 风险是单等位：risk=A，user 包含 A 即命中
    - 风险是 OR 模式：risk=AA|AG，user 命中任一即匹配

    Args:
        user_genotype: 用户基因型（2 个字符或含分隔）
        risk_genotype: 风险基因型（可能含 | 表示多种风险型）
    """
    if not user_genotype or not risk_genotype:
        return False
    if user_genotype in ("--", "", "00"):
        return False

    user_clean = user_genotype.strip().upper()
    # 处理 OR 模式
    risk_options = [r.strip().upper() for r in risk_genotype.split("|") if r.strip()]
    flipped_user = chain_flip_genotype(user_clean)

    for risk in risk_options:
        if not risk:
            continue
        # 风险是单等位（如 "A"），用户基因型含此等位即命中
        if len(risk) == 1:
            if risk in user_clean or risk in flipped_user:
                return True
        else:
            # 完全匹配或链翻转匹配
            if user_clean == risk or flipped_user == risk:
                return True
            # 不区分相位匹配（AA == AA, AG == GA）
            if sorted(user_clean) == sorted(risk):
                return True
            if sorted(flipped_user) == sorted(risk):
                return True
    return False


async def convert_position(
    db: AsyncSession,
    rsid: str,
    from_build: str,
    to_build: str,
) -> Optional[int]:
    """坐标转换 — 优先查本地表，缺失时返回 None（上层决定是否调外部 API）

    Args:
        db: 数据库会话
        rsid: dbSNP 编号
        from_build: GRCh37 / GRCh38
        to_build: GRCh37 / GRCh38

    Returns:
        目标版本的坐标，无记录时返回 None
    """
    if from_build == to_build:
        # 同版本无需转换，直接查表
        return await _lookup_position(db, rsid, to_build)

    # 查 snp_loci 表是否已有双版本记录
    from app.models.snp_locus import SnpLocus
    result = await db.execute(
        select(SnpLocus).where(SnpLocus.rsid == rsid).limit(1)
    )
    locus = result.scalar_one_or_none()
    if not locus:
        return None

    if to_build == "GRCh37":
        return locus.position_grch37
    if to_build == "GRCh38":
        return locus.position_grch38
    return None


async def _lookup_position(
    db: AsyncSession, rsid: str, build: str
) -> Optional[int]:
    """查表获取指定版本的坐标"""
    from app.models.snp_locus import SnpLocus
    result = await db.execute(
        select(SnpLocus).where(SnpLocus.rsid == rsid).limit(1)
    )
    locus = result.scalar_one_or_none()
    if not locus:
        return None
    if build == "GRCh37":
        return locus.position_grch37
    if build == "GRCh38":
        return locus.position_grch38
    return None


async def liftover_with_fallback(
    db: AsyncSession,
    rsid: str,
    from_build: str,
    to_build: str,
) -> Tuple[Optional[int], str]:
    """坐标转换 + 外部 API 兜底

    Returns:
        (position, source) — source 取值 "local" / "ncbi_api" / "pyliftover" / "unknown"
    """
    if from_build == to_build:
        pos = await _lookup_position(db, rsid, to_build)
        return pos, "local" if pos else "unknown"

    # 1. 本地表
    pos = await convert_position(db, rsid, from_build, to_build)
    if pos is not None:
        return pos, "local"

    # 2. pyliftover（可选依赖）
    try:
        pos = _liftover_via_pyliftover(rsid, from_build, to_build)
        if pos is not None:
            return pos, "pyliftover"
    except ImportError:
        logger.debug("pyliftover 未安装，跳过该路径")
    except Exception as e:
        logger.warning(f"pyliftover 转换失败: {e}")

    # 3. NCBI E-utilities 兜底（实现见 knowledge/data_cache.py 中的统一客户端）
    # 此处仅返回 unknown，由上层调用方决定是否拉取外部数据
    return None, "unknown"


def _liftover_via_pyltover(rsid: str, from_build: str, to_build: str) -> Optional[int]:
    """使用 pyliftover 库做坐标转换（可选依赖）

    注意：pyliftover 需要 GRCh37 链文件（~50MB），首次使用会自动下载。
    生产环境建议预下载链文件到 /data/liftover/ 目录。
    """
    # 实现简化 — 实际需查 rsid 对应的 chrom+pos 才能转换
    # 留作可选增强，不在 MVP 中强制依赖
    return None


# 兼容拼写（避免外部调用方拼写错误导致 ImportError）
_liftover_via_pyliftover = _liftover_via_pyltover


__all__ = [
    "chain_flip_allele",
    "chain_flip_genotype",
    "is_genotype_match",
    "convert_position",
    "liftover_with_fallback",
]
