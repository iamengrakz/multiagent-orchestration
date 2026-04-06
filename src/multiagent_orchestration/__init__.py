"""
multiagent_orchestration
========================
Production reference implementation for the book
"Multi-Agent Orchestration in Action: MCP Contracts · DAG Orchestration · Production Resilience"

Authors: Aimal Khan, Shamvail Khan

Public API surface — import from here, not from sub-modules directly.
"""

from multiagent_orchestration.contracts import MCPToolContract, ToolSchema
from multiagent_orchestration.dag import DirectedAcyclicGraph
from multiagent_orchestration.orchestrator import DAGOrchestrator, OrchestrationConfig
from multiagent_orchestration.result import Ok, Err, Result
from multiagent_orchestration.loop_detector import InvocationFingerprinter, LoopError
from multiagent_orchestration.idempotency import IdempotencyMiddleware, InMemoryStore
from multiagent_orchestration.token_budget import TokenBudgetManager, BudgetExceededError
from multiagent_orchestration.circuit_breaker import CircuitBreaker, CircuitState
from multiagent_orchestration.observability import StructuredLogger
from multiagent_orchestration.human_in_the_loop import (
    HumanInTheLoop,
    EscalationPolicy,
    EscalationTier,
    EscalationDecision,
    StubHumanGateway,
    PipelineAbortedByHuman,
)
from multiagent_orchestration.semantic_loop_detector import (
    SemanticLoopDetector,
    CompositeLoopDetector,
    SemanticLoopError,
    TFIDFEmbedder,
)
from multiagent_orchestration.saga import (
    SagaOrchestrator,
    SagaStep,
    SagaResult,
)
from multiagent_orchestration.state_sync import (
    InMemoryEventStore,
    AgentEvent,
    ConcurrentWriteError,
    DuplicateEventError,
)

__version__ = "0.1.0"

__all__ = [
    # contracts
    "MCPToolContract",
    "ToolSchema",
    # dag & orchestration
    "DirectedAcyclicGraph",
    "DAGOrchestrator",
    "OrchestrationConfig",
    # result type
    "Ok",
    "Err",
    "Result",
    # loop detection
    "InvocationFingerprinter",
    "LoopError",
    # idempotency
    "IdempotencyMiddleware",
    "InMemoryStore",
    # token budget
    "TokenBudgetManager",
    "BudgetExceededError",
    # circuit breaker
    "CircuitBreaker",
    "CircuitState",
    # observability
    "StructuredLogger",
    # human-in-the-loop
    "HumanInTheLoop",
    "EscalationPolicy",
    "EscalationTier",
    "EscalationDecision",
    "StubHumanGateway",
    "PipelineAbortedByHuman",
    # semantic loop detection
    "SemanticLoopDetector",
    "CompositeLoopDetector",
    "SemanticLoopError",
    "TFIDFEmbedder",
    # saga / compensating transactions
    "SagaOrchestrator",
    "SagaStep",
    "SagaResult",
    # state synchronisation
    "InMemoryEventStore",
    "AgentEvent",
    "ConcurrentWriteError",
    "DuplicateEventError",
]
