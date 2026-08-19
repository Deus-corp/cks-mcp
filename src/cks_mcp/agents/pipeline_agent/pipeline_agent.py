"""
Pipeline Agent: the console-script entry point for ADR-007's
``CKSAgentOrchestrator``, Milestone 1 (Researcher + Reviewer) plus
Milestone 2 (Synthesizer + Arbiter).

Same process shape as ``cks_mcp.agents.critic_agent.critic_agent``/``cks_mcp.agents.enrichment_agent.enrichment_agent``:
its own OS process, its own ``Runtime`` sharing storage with the main
``cks-mcp`` server (same SQLite file or Postgres DSN), looping
``CKSAgentOrchestrator.run_sequential()`` -- drain each step's queue in
turn (Researcher, Reviewer, Synthesizer, Arbiter), sleep
``poll_interval`` if nothing was processed, repeat.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from dataclasses import dataclass, field
from typing import Any

from cks_runtime.adapters.cks_core import CksCoreAdapter
from cks_runtime.config import RuntimeConfig
from cks_runtime.runtime import Runtime

from cks_mcp.agents.agent_loop import LivenessReporter
from cks_mcp.orchestrator import CKSAgentOrchestrator
from cks_mcp.paths import data_dir
from cks_mcp.pipeline.arbiter_step import ArbiterStep, ArbiterStepSettings
from cks_mcp.pipeline.researcher_step import ResearcherStep, ResearcherStepSettings
from cks_mcp.pipeline.reviewer_step import ReviewerStep, ReviewerStepSettings
from cks_mcp.pipeline.synthesizer_step import SynthesizerStep, SynthesizerStepSettings

_DEFAULT_POLL_INTERVAL_SECONDS = 5.0
_DEFAULT_LIVENESS_INTERVAL_SECONDS = 30.0  # process liveness (ADR-014)


@dataclass(slots=True)
class PipelineAgentSettings:
    poll_interval: float = _DEFAULT_POLL_INTERVAL_SECONDS
    storage_path: str = field(default_factory=lambda: "")
    liveness_interval: float = _DEFAULT_LIVENESS_INTERVAL_SECONDS

    @classmethod
    def from_env(cls) -> PipelineAgentSettings:
        return cls(
            poll_interval=float(
                os.environ.get("CKS_PIPELINE_POLL_INTERVAL", _DEFAULT_POLL_INTERVAL_SECONDS)
            ),
            storage_path=os.environ.get("CKS_MCP_DB_PATH") or str(data_dir() / "cks_mcp.db"),
            liveness_interval=float(
                os.environ.get(
                    "CKS_PIPELINE_LIVENESS_INTERVAL", _DEFAULT_LIVENESS_INTERVAL_SECONDS
                )
            ),
        )


async def run_pipeline_agent(
    *,
    settings: PipelineAgentSettings | None = None,
    max_iterations: int | None = None,
    stop_event: asyncio.Event | None = None,
) -> None:
    """``stop_event``, when given, is used instead of creating a fresh
    ``asyncio.Event``/installing signal handlers -- see
    ``cks_mcp.agents.critic_agent.critic_agent.run_critic_agent``'s docstring for why
    (embedded-agents mode, ADR-012)."""
    settings = settings or PipelineAgentSettings.from_env()

    config = RuntimeConfig(storage_path=settings.storage_path)
    runtime = await Runtime.create(core=CksCoreAdapter(), config=config)

    orchestrator = CKSAgentOrchestrator(
        runtime,
        [
            ResearcherStep(ResearcherStepSettings.from_env()),
            ReviewerStep(ReviewerStepSettings.from_env()),
            SynthesizerStep(SynthesizerStepSettings.from_env()),
            ArbiterStep(ArbiterStepSettings.from_env()),
        ],
    )

    owns_signals = stop_event is None
    stop = stop_event if stop_event is not None else asyncio.Event()

    if owns_signals:

        def _handle_signal(*_: Any) -> None:
            stop.set()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, _handle_signal)
            except (NotImplementedError, RuntimeError):
                pass

    print(
        f"[cks-pipeline-agent] started (storage_path={settings.storage_path!r}, "
        f"poll_interval={settings.poll_interval}s, "
        f"liveness_interval={settings.liveness_interval}s, "
        "steps=Researcher,Reviewer,Synthesizer,Arbiter)",
        file=sys.stderr,
    )

    liveness = LivenessReporter(
        runtime, "pipeline", settings.liveness_interval, stop_event=stop
    )
    await liveness.start()

    try:
        iterations = 0
        while not stop.is_set():
            result = await orchestrator.run_sequential()
            if result.total_processed == 0:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=settings.poll_interval)
                except TimeoutError:
                    pass
            iterations += 1
            if max_iterations is not None and iterations >= max_iterations:
                break
    finally:
        await liveness.stop()
        await runtime.aclose()
        print("[cks-pipeline-agent] stopped", file=sys.stderr)


def main_sync() -> None:
    """Console-script entry point (see pyproject.toml's [project.scripts])."""
    asyncio.run(run_pipeline_agent())


if __name__ == "__main__":
    main_sync()