"""数据脱敏器 — HIPAA Safe Harbor 18 项标识符

设计来源：repowiki/zh/content/安全与合规/HIPAA脱敏规则.md
P0/P1：纯 Python 字符串/哈希脱敏，不依赖第三方库。
P3：可接入 Vault / HashiCorp / Protegrity 做企业级 tokenization。
"""
import hashlib
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings

logger = logging.getLogger(__name__)


# HIPAA Safe Harbor 18 项标识符类型
IDENTIFIER_TYPES: Tuple[str, ...] = (
    "name",          # 1. 姓名
    "geographic",    # 2. 地理信息（小于州级别）
    "dates",         # 3. 日期（除年份外）/ 年龄相关日期
    "telephone",     # 4. 电话
    "fax",           # 5. 传真
    "email",         # 6. 电子邮件
    "ssn",           # 7. 社会保障号
    "mrn",           # 8. 医疗记录号
    "account",       # 9. 账户号
    "certificate",   # 10. 证书/许可证号
    "vehicle",       # 11. 车辆标识符
    "device",        # 12. 设备标识符
    "url",           # 13. URL
    "ip",            # 14. IP 地址
    "biometric",     # 15. 生物特征
    "photo",         # 16. 全脸照片
    "profession",    # 17. 职业（Unique identifying characteristic）
    "age_over_89",   # 18. 89 岁以上年龄
)


class DataMasker:
    """数据脱敏器 — HIPAA Safe Harbor 合规

    支持 18 种标识符类型，每种类型有对应的脱敏策略：
    - 哈希（hash）：单向 SHA-256 + 盐
    - 掩码（mask）：保留首/尾部分字符
    - 泛化（generalize）：粒度降低（如日期->年份、地理->州）
    - 删除（redact）：直接替换为占位符
    """

    def __init__(self, salt: Optional[str] = None) -> None:
        """初始化脱敏器

        Args:
            salt: 哈希盐值；None 时使用 settings 配置或默认
        """
        self._salt = salt or getattr(settings, "MASK_SALT", "") or "pdd_salt_v1"
        self._rules: Dict[str, str] = self._default_rules()
        if settings.USE_MOCK:
            logger.info("DataMasker: Mock 模式，使用固定盐值以便复现")

    # ---------- 公开 API ----------
    def mask_records(
        self,
        records: List[Dict[str, Any]],
        rules: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        """批量脱敏记录

        Args:
            records: 原始记录列表（每条为 dict）
            rules: 字段名 -> 标识符类型 的映射；None 时按字段名自动推断
        Returns:
            脱敏后的记录列表（新对象，不修改原数据）
        """
        if not records:
            return []
        merged_rules = {**self._rules, **(rules or {})}
        masked: List[Dict[str, Any]] = []
        for rec in records:
            if not isinstance(rec, dict):
                masked.append(rec)
                continue
            new_rec: Dict[str, Any] = {}
            for k, v in rec.items():
                field_type = self._infer_field_type(k, merged_rules)
                if field_type is None:
                    new_rec[k] = v
                else:
                    try:
                        new_rec[k] = self.mask_field(v, field_type)
                    except Exception as e:
                        logger.warning("脱敏字段 %s 失败: %s", k, e)
                        new_rec[k] = "[MASK_FAILED]"
            masked.append(new_rec)
        logger.info("脱敏完成：%d 条记录", len(masked))
        return masked

    def mask_field(self, value: Any, field_type: str) -> Any:
        """单字段脱敏

        Args:
            value: 原始值
            field_type: 标识符类型（见 IDENTIFIER_TYPES）
        Returns:
            脱敏后的值
        Raises:
            ValueError: 未知 field_type
        """
        if value is None:
            return None
        if field_type not in IDENTIFIER_TYPES:
            raise ValueError(f"未知标识符类型: {field_type}")

        handler = getattr(self, f"_mask_{field_type}", None)
        if handler is None:
            # 默认：哈希
            return self._hash(str(value))
        return handler(value)

    def assess_k_anonymity(
        self,
        records: List[Dict[str, Any]],
        quasi_identifiers: List[str],
    ) -> Dict[str, Any]:
        """评估 k-匿名性

        k-匿名：在准标识符组合上，每组至少有 k 条记录。

        Args:
            records: 记录列表
            quasi_identifiers: 准标识符字段名列表
        Returns:
            {
                "k": 最小等价组大小,
                "groups": 等价组数,
                "violation_groups": 小于 k 的组数（k=2 阈值示例）,
                "distribution": {group_size: count}
            }
        """
        if not records:
            return {"k": 0, "groups": 0, "violation_groups": 0, "distribution": {}}

        groups: Dict[Tuple, int] = {}
        for rec in records:
            key = tuple(rec.get(qi) for qi in quasi_identifiers)
            groups[key] = groups.get(key, 0) + 1

        if not groups:
            return {"k": 0, "groups": 0, "violation_groups": 0, "distribution": {}}

        k_min = min(groups.values())
        distribution: Dict[int, int] = {}
        for size in groups.values():
            distribution[size] = distribution.get(size, 0) + 1
        # 通常 k >= 2 视为达标；此处用 2 作为违规阈值
        violation_groups = sum(1 for s in groups.values() if s < 2)

        logger.info(
            "k-匿名评估：%d 记录 / %d 等价组 / k_min=%d",
            len(records), len(groups), k_min,
        )
        return {
            "k": k_min,
            "groups": len(groups),
            "violation_groups": violation_groups,
            "distribution": distribution,
        }

    # ---------- 默认规则 ----------
    def _default_rules(self) -> Dict[str, str]:
        """字段名 -> 标识符类型 默认映射"""
        return {
            "name": "name",
            "patient_name": "name",
            "first_name": "name",
            "last_name": "name",
            "phone": "telephone",
            "telephone": "telephone",
            "tel": "telephone",
            "fax": "fax",
            "email": "email",
            "mail": "email",
            "ssn": "ssn",
            "social_security": "ssn",
            "mrn": "mrn",
            "medical_record_number": "mrn",
            "account": "account",
            "account_number": "account",
            "certificate": "certificate",
            "license": "certificate",
            "vehicle": "vehicle",
            "plate": "vehicle",
            "device": "device",
            "device_id": "device",
            "url": "url",
            "website": "url",
            "ip": "ip",
            "ip_address": "ip",
            "biometric": "biometric",
            "fingerprint": "biometric",
            "photo": "photo",
            "image": "photo",
            "profession": "profession",
            "occupation": "profession",
            "address": "geographic",
            "city": "geographic",
            "zip": "geographic",
            "zipcode": "geographic",
            "birth_date": "dates",
            "dob": "dates",
            "admission_date": "dates",
            "discharge_date": "dates",
            "age": "age_over_89",
        }

    def _infer_field_type(
        self,
        field_name: str,
        rules: Dict[str, str],
    ) -> Optional[str]:
        """从字段名推断标识符类型"""
        key = field_name.lower()
        if key in rules:
            ft = rules[key]
            return ft if ft in IDENTIFIER_TYPES else None
        return None

    # ---------- 各类型脱敏实现 ----------
    def _hash(self, value: str) -> str:
        """SHA-256 + 盐"""
        salted = f"{self._salt}:{value}"
        return "h_" + hashlib.sha256(salted.encode("utf-8")).hexdigest()[:16]

    def _mask(self, value: str, keep_head: int = 1, keep_tail: int = 1) -> str:
        """通用掩码：保留首尾若干字符，中间用 * 替换"""
        s = str(value)
        if len(s) <= keep_head + keep_tail:
            return "*" * len(s)
        head = s[:keep_head]
        tail = s[-keep_tail:] if keep_tail > 0 else ""
        middle = "*" * (len(s) - keep_head - keep_tail)
        return f"{head}{middle}{tail}"

    def _mask_name(self, value: Any) -> str:
        return self._hash(str(value))

    def _mask_telephone(self, value: Any) -> str:
        # 保留后 4 位：***-***-1234
        s = re.sub(r"\D", "", str(value))
        if len(s) < 4:
            return "*" * len(s)
        return f"***-***-{s[-4:]}"

    def _mask_fax(self, value: Any) -> str:
        return self._mask_telephone(value)

    def _mask_email(self, value: Any) -> str:
        s = str(value)
        if "@" not in s:
            return self._hash(s)
        local, _, domain = s.partition("@")
        if not local:
            return f"@{domain}"
        masked_local = local[0] + "*" * max(len(local) - 1, 1)
        return f"{masked_local}@{domain}"

    def _mask_ssn(self, value: Any) -> str:
        # ***-**-1234
        s = re.sub(r"\D", "", str(value))
        if len(s) < 4:
            return "*" * len(s)
        return f"***-**-{s[-4:]}"

    def _mask_mrn(self, value: Any) -> str:
        return self._hash(str(value))

    def _mask_account(self, value: Any) -> str:
        s = str(value)
        return self._mask(s, keep_head=2, keep_tail=4)

    def _mask_certificate(self, value: Any) -> str:
        return self._mask(str(value), keep_head=2, keep_tail=2)

    def _mask_vehicle(self, value: Any) -> str:
        return self._mask(str(value), keep_head=1, keep_tail=2)

    def _mask_device(self, value: Any) -> str:
        return self._hash(str(value))

    def _mask_url(self, value: Any) -> str:
        s = str(value)
        if "://" in s:
            scheme, _, rest = s.partition("://")
            host, _, path = rest.partition("/")
            masked_host = self._mask(host, keep_head=3, keep_tail=0)
            return f"{scheme}://{masked_host}/{path}"
        return self._mask(s, keep_head=4, keep_tail=0)

    def _mask_ip(self, value: Any) -> str:
        # IPv4: 保留前两段，后两段掩码
        s = str(value)
        parts = s.split(".")
        if len(parts) == 4:
            return f"{parts[0]}.{parts[1]}.*.*"
        return self._hash(s)

    def _mask_biometric(self, value: Any) -> str:
        return self._hash(str(value))

    def _mask_photo(self, value: Any) -> str:
        return "[REDACTED_PHOTO]"

    def _mask_profession(self, value: Any) -> str:
        # 泛化为职业大类
        s = str(value).lower().strip()
        profession_map = {
            "doctor": "healthcare_worker",
            "nurse": "healthcare_worker",
            "physician": "healthcare_worker",
            "teacher": "education",
            "engineer": "technical",
            "lawyer": "legal",
            "farmer": "agriculture",
        }
        return profession_map.get(s, "other")

    def _mask_geographic(self, value: Any) -> str:
        # 泛化到州/省级别
        s = str(value).strip()
        # 简化处理：取首词或截断
        if " " in s:
            return s.split()[-1]  # 假设最后一段是州
        return s[:2] + "***"

    def _mask_dates(self, value: Any) -> str:
        # 泛化为年份
        s = str(value)
        # 匹配 4 位年份
        m = re.search(r"\b(19|20)\d{2}\b", s)
        if m:
            return m.group(0)
        return self._hash(s)

    def _mask_age_over_89(self, value: Any) -> str:
        try:
            age = int(value)
        except (TypeError, ValueError):
            return "[AGE_MASKED]"
        if age > 89:
            return "90+"
        return str(age)
