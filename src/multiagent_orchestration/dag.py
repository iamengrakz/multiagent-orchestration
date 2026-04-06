"""
dag.py — DirectedAcyclicGraph
==============================
Book reference: Chapter 4, §4.1–4.3

Provides a simple, dependency-tracking directed acyclic graph whose nodes are
``MCPToolContract`` instances.  The orchestrator uses this to determine
execution order via topological sort and to detect cycles before any tool
is scheduled.

Key design decisions (see ARCHITECTURAL_DECISIONS.md §ADR-002):

- Cycle detection runs eagerly on ``add_edge()``, not lazily at execution time.
  A cycle is a programming error; fail fast.
- The graph owns no state about individual tool *runs*; that belongs to
  ``DAGOrchestrator``.

Usage (Chapter 4, Listing 4.1)::

    dag = DirectedAcyclicGraph()
    dag.add_node(planner_tool)
    dag.add_node(search_tool)
    dag.add_node(summarise_tool)
    dag.add_edge(planner_tool, search_tool)   # planner must finish before search
    dag.add_edge(search_tool, summarise_tool)

    for tool in dag.topological_sort():
        result = tool.call(inputs[tool.name])
"""

from __future__ import annotations

from collections import deque
from typing import Iterator

from multiagent_orchestration.contracts import MCPToolContract


class CycleError(Exception):
    """Raised when ``add_edge`` would introduce a cycle.

    Book reference: Chapter 4, §4.2 — "Fail Fast on Cycles"
    """


class DirectedAcyclicGraph:
    """Dependency graph over :class:`~multiagent_orchestration.contracts.MCPToolContract` nodes.

    Book reference: Chapter 4, §4.1 — "Modelling Pipelines as DAGs"

    Attributes:
        nodes: Set of registered tool contracts.
        edges: Adjacency list: ``edges[tool] = set_of_downstream_tools``.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, MCPToolContract] = {}
        self._edges: dict[str, set[str]] = {}  # upstream → downstream
        self._reverse: dict[str, set[str]] = {}  # downstream → upstream (for topo)

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def add_node(self, tool: MCPToolContract) -> None:
        """Register *tool* as a node.  Idempotent.

        Args:
            tool: Any :class:`MCPToolContract` subclass instance.
        """
        if tool.name not in self._nodes:
            self._nodes[tool.name] = tool
            self._edges[tool.name] = set()
            self._reverse[tool.name] = set()

    def add_edge(self, upstream: MCPToolContract, downstream: MCPToolContract) -> None:
        """Add a dependency edge: *downstream* runs after *upstream*.

        Automatically registers both nodes if not already present.

        Args:
            upstream: The tool that must complete first.
            downstream: The tool that depends on *upstream*.

        Raises:
            CycleError: If adding this edge would create a cycle.
        """
        self.add_node(upstream)
        self.add_node(downstream)
        self._edges[upstream.name].add(downstream.name)
        self._reverse[downstream.name].add(upstream.name)
        self._check_for_cycle()

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def topological_sort(self) -> list[MCPToolContract]:
        """Return tools in a valid execution order (Kahn's algorithm).

        All upstream tools precede their downstream dependents.

        Returns:
            Ordered list of :class:`MCPToolContract` instances.

        Raises:
            CycleError: If a cycle exists (should have been caught by
                ``add_edge``, but included defensively).
        """
        in_degree: dict[str, int] = {
            name: len(deps) for name, deps in self._reverse.items()
        }
        queue: deque[str] = deque(
            name for name, degree in in_degree.items() if degree == 0
        )
        result: list[str] = []

        while queue:
            name = queue.popleft()
            result.append(name)
            for downstream in self._edges[name]:
                in_degree[downstream] -= 1
                if in_degree[downstream] == 0:
                    queue.append(downstream)

        if len(result) != len(self._nodes):
            raise CycleError(
                "Cycle detected during topological sort — this should not happen "
                "if add_edge() was used correctly."
            )

        return [self._nodes[name] for name in result]

    def __iter__(self) -> Iterator[MCPToolContract]:
        """Iterate in topological order."""
        return iter(self.topological_sort())

    def __len__(self) -> int:
        return len(self._nodes)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_for_cycle(self) -> None:
        """DFS-based cycle check.  Raises :class:`CycleError` on detection."""
        visited: set[str] = set()
        rec_stack: set[str] = set()

        def dfs(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)
            for neighbour in self._edges[node]:
                if neighbour not in visited:
                    if dfs(neighbour):
                        return True
                elif neighbour in rec_stack:
                    return True
            rec_stack.discard(node)
            return False

        for name in self._nodes:
            if name not in visited:
                if dfs(name):
                    raise CycleError(
                        f"Adding this edge introduced a cycle involving node '{name}'. "
                        "DAG invariant violated — check your pipeline definition."
                    )
