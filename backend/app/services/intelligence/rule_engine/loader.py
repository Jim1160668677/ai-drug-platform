"""规则加载器 — YAML 文件加载、校验与缓存

支持从文件路径、目录、字符串加载规则集，自动校验 schema。
内置 presets 目录的预置规则集。
"""
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

import yaml
from pydantic import ValidationError

from app.services.intelligence.rule_engine.schemas import Rule, RuleSet

logger = logging.getLogger(__name__)

# presets 目录（随包分发）
_PRESETS_DIR = Path(__file__).parent / "presets"


class RuleLoader:
    """规则加载器

    用法：
        loader = RuleLoader()
        # 从文件加载
        ruleset = loader.load_file("/path/to/rules.yaml")
        # 从目录加载所有
        rulesets = loader.load_dir("/path/to/rules/")
        # 加载内置 preset
        ruleset = loader.load_preset("target_discovery")
        # 列出所有 preset
        names = loader.list_presets()
    """

    def __init__(self, presets_dir: Optional[Path] = None):
        self.presets_dir = presets_dir or _PRESETS_DIR

    def load_file(self, path: str) -> RuleSet:
        """从 YAML 文件加载规则集"""
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        return self._parse(raw, source=path)

    def load_string(self, content: str, source: str = "<string>") -> RuleSet:
        """从 YAML 字符串加载规则集"""
        raw = yaml.safe_load(content)
        return self._parse(raw, source=source)

    def load_dir(self, dir_path: str) -> List[RuleSet]:
        """从目录加载所有 .yaml/.yml 规则集"""
        rulesets: List[RuleSet] = []
        d = Path(dir_path)
        if not d.is_dir():
            logger.warning("[RuleLoader] 目录不存在: %s", dir_path)
            return rulesets
        for ext in ("*.yaml", "*.yml"):
            for f in sorted(d.glob(ext)):
                try:
                    rulesets.append(self.load_file(str(f)))
                except Exception as e:
                    logger.error("[RuleLoader] 加载 %s 失败: %s", f, e)
        return rulesets

    def load_preset(self, name: str) -> RuleSet:
        """加载内置 preset（presets 目录下的 {name}.yaml）"""
        path = self.presets_dir / f"{name}.yaml"
        if not path.is_file():
            raise FileNotFoundError(f"内置规则集不存在: {name}（路径 {path}）")
        return self.load_file(str(path))

    def list_presets(self) -> List[str]:
        """列出所有内置 preset 名称"""
        if not self.presets_dir.is_dir():
            return []
        names = []
        for f in self.presets_dir.glob("*.yaml"):
            names.append(f.stem)
        return sorted(names)

    def load_all_presets(self) -> List[RuleSet]:
        """加载所有内置 preset"""
        rulesets: List[RuleSet] = []
        for name in self.list_presets():
            try:
                rulesets.append(self.load_preset(name))
            except Exception as e:
                logger.error("[RuleLoader] 加载 preset %s 失败: %s", name, e)
        return rulesets

    def _parse(self, raw: dict, source: str) -> RuleSet:
        """解析原始字典为 RuleSet（带校验）"""
        if not isinstance(raw, dict):
            raise ValueError(f"规则文件必须是 YAML 字典: {source}")
        root = raw.get("ruleset")
        if not isinstance(root, dict):
            raise ValueError(f"规则文件缺少 ruleset 根节点: {source}")
        try:
            ruleset = RuleSet(
                ruleset=root,
                name=root.get("name", source),
                version=str(root.get("version", "1.0")),
                description=root.get("description"),
                rules=root.get("rules", []),
            )
        except ValidationError as e:
            raise ValueError(f"规则集校验失败 {source}: {e}") from e
        logger.info("[RuleLoader] 加载规则集 %s: %d 条规则", ruleset.name, len(ruleset.rules))
        return ruleset

    def flatten_rules(self, rulesets: List[RuleSet]) -> List[Rule]:
        """将多个规则集扁平化为单个规则列表（按 priority 降序）"""
        rules: List[Rule] = []
        for rs in rulesets:
            rules.extend(r for r in rs.rules if r.enabled)
        rules.sort(key=lambda r: r.priority, reverse=True)
        return rules


__all__ = ["RuleLoader"]
