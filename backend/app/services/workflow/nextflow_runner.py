"""Nextflow 工作流执行器 — 任务调度与状态追踪"""
import asyncio
import logging
import os
import random
import time
import uuid
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflow_run import WorkflowRun, WorkflowStatus

logger = logging.getLogger(__name__)


# Nextflow 脚本路径映射
PIPELINE_SCRIPTS = {
    "scrna_pipeline": "nextflow/scrna_pipeline.nf",
    "rna_seq_pipeline": "nextflow/rna_seq_pipeline.nf",
    "variant_annotation": "nextflow/variant_annotation.nf",
}

# 模拟输出文件
MOCK_OUTPUTS = {
    "scrna_pipeline": ["annotated.h5ad", "markers.csv", "qc_report.html"],
    "rna_seq_pipeline": ["deseq2_results.csv", "normalized_counts.csv"],
    "variant_annotation": ["annotated.vcf", "summary.json"],
}


class NextflowRunner:
    """Nextflow 工作流执行器

    P0 模拟模式（默认）：返回模拟结果，不实际执行 nextflow。
    真实模式（EXECUTE_NEXTFLOW=true）：通过 subprocess 执行 nextflow 命令。
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self._execute_real = os.getenv("EXECUTE_NEXTFLOW", "false").lower() == "true"

    async def run(self, workflow_run: WorkflowRun) -> Dict[str, Any]:
        """执行 Nextflow 工作流

        Args:
            workflow_run: WorkflowRun ORM 对象
        Returns:
            {status, run_id, output_path, duration_sec, pipeline_name}
        """
        pipeline_name = workflow_run.pipeline_name
        run_id = f"nf-{uuid.uuid4().hex[:12]}"
        start = time.time()

        if self._execute_real:
            result = await self._run_real(workflow_run, run_id)
        else:
            result = await self._run_mock(workflow_run, run_id)

        duration_sec = int(time.time() - start)

        # 更新 workflow_run 记录
        workflow_run.run_id = run_id
        workflow_run.status = result.get("status", WorkflowStatus.COMPLETED)
        workflow_run.output_path = result.get("output_path")
        workflow_run.duration_sec = duration_sec
        workflow_run.trace_url = f"https://nextflow.io/traces/{run_id}"
        if result.get("error"):
            workflow_run.error = result["error"]

        return {
            "status": workflow_run.status,
            "run_id": run_id,
            "output_path": workflow_run.output_path,
            "duration_sec": duration_sec,
            "pipeline_name": pipeline_name,
            "trace_url": workflow_run.trace_url,
            "mock": not self._execute_real,
        }

    async def _run_mock(self, workflow_run: WorkflowRun, run_id: str) -> Dict[str, Any]:
        """模拟执行 — 返回模拟结果"""
        pipeline_name = workflow_run.pipeline_name
        await asyncio.sleep(0.5)  # 模拟执行延迟

        output_files = MOCK_OUTPUTS.get(pipeline_name, ["output.txt"])
        output_path = f"/data/outputs/{run_id}/"
        params = workflow_run.params or {}

        return {
            "status": WorkflowStatus.COMPLETED,
            "output_path": output_path,
            "output_files": output_files,
            "params_used": params,
            "mock_summary": {
                "total_processes": random.randint(4, 12),
                "succeeded": random.randint(4, 12),
                "failed": 0,
                "cached": random.randint(0, 5),
            },
        }

    async def _run_real(self, workflow_run: WorkflowRun, run_id: str) -> Dict[str, Any]:
        """真实执行 — 调用 nextflow 命令"""
        pipeline_name = workflow_run.pipeline_name
        script_path = PIPELINE_SCRIPTS.get(pipeline_name, f"nextflow/{pipeline_name}.nf")

        import json
        import tempfile

        # 写入参数文件
        params = workflow_run.params or {}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(params, f)
            params_file = f.name

        try:
            cmd = ["nextflow", "run", script_path, "-params-file", params_file, "-name", run_id]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                return {
                    "status": WorkflowStatus.COMPLETED,
                    "output_path": f"/data/outputs/{run_id}/",
                    "stdout": stdout.decode()[:1000] if stdout else "",
                }
            else:
                return {
                    "status": WorkflowStatus.FAILED,
                    "error": stderr.decode()[:2000] if stderr else "Unknown error",
                    "output_path": None,
                }
        except FileNotFoundError:
            return {
                "status": WorkflowStatus.FAILED,
                "error": "nextflow 命令未找到，请安装 Nextflow 或设置 EXECUTE_NEXTFLOW=false",
            }
        finally:
            try:
                os.unlink(params_file)
            except OSError:
                pass

    async def check_status(self, run_id: str) -> Dict[str, Any]:
        """查询工作流运行状态

        Args:
            run_id: Nextflow run ID
        Returns:
            {run_id, status, progress}
        """
        if self._execute_real:
            # 真实模式：可查询 nextflow log
            return {
                "run_id": run_id,
                "status": "unknown",
                "note": "真实模式需实现 nextflow log 查询",
            }

        # 模拟模式
        return {
            "run_id": run_id,
            "status": WorkflowStatus.COMPLETED,
            "progress": 100,
            "mock": True,
        }
