"""
tests/unit/test_dag.py
Book reference: Chapter 4
"""

from __future__ import annotations

import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "src"))

import pytest

from multiagent_orchestration.contracts import MCPToolContract, ToolSchema
from multiagent_orchestration.dag import DirectedAcyclicGraph, CycleError


def make_tool(name: str) -> MCPToolContract:
    """Factory: creates a minimal anonymous tool with the given name."""

    class _T(MCPToolContract):
        input_schema = ToolSchema(required=[], properties={})
        output_schema = ToolSchema(required=[], properties={})

        def execute(self, inputs):
            return {}

    _T.name = name
    _T.version = "1.0.0"
    _T.description = f"Test tool: {name}"
    return _T()


class TestDirectedAcyclicGraph:
    def test_empty_graph_has_zero_length(self):
        assert len(DirectedAcyclicGraph()) == 0

    def test_add_node_increases_length(self):
        dag = DirectedAcyclicGraph()
        dag.add_node(make_tool("a"))
        assert len(dag) == 1

    def test_add_node_is_idempotent(self):
        dag = DirectedAcyclicGraph()
        t = make_tool("a")
        dag.add_node(t)
        dag.add_node(t)
        assert len(dag) == 1

    def test_topological_sort_linear_chain(self):
        dag = DirectedAcyclicGraph()
        a, b, c = make_tool("a"), make_tool("b"), make_tool("c")
        dag.add_edge(a, b)
        dag.add_edge(b, c)
        order = [t.name for t in dag.topological_sort()]
        assert order.index("a") < order.index("b")
        assert order.index("b") < order.index("c")

    def test_topological_sort_diamond(self):
        dag = DirectedAcyclicGraph()
        a, b, c, d = make_tool("a"), make_tool("b"), make_tool("c"), make_tool("d")
        dag.add_edge(a, b)
        dag.add_edge(a, c)
        dag.add_edge(b, d)
        dag.add_edge(c, d)
        order = [t.name for t in dag.topological_sort()]
        assert order[0] == "a"
        assert order[-1] == "d"

    def test_direct_cycle_raises(self):
        dag = DirectedAcyclicGraph()
        a, b = make_tool("a"), make_tool("b")
        dag.add_edge(a, b)
        with pytest.raises(CycleError):
            dag.add_edge(b, a)

    def test_indirect_cycle_raises(self):
        dag = DirectedAcyclicGraph()
        a, b, c = make_tool("a"), make_tool("b"), make_tool("c")
        dag.add_edge(a, b)
        dag.add_edge(b, c)
        with pytest.raises(CycleError):
            dag.add_edge(c, a)

    def test_iteration_uses_topological_order(self):
        dag = DirectedAcyclicGraph()
        a, b = make_tool("a"), make_tool("b")
        dag.add_edge(a, b)
        names = [t.name for t in dag]
        assert names == ["a", "b"]
