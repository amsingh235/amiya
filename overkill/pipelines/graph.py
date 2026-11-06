"""A 40-line subset of LangGraph's StateGraph: nodes, edges, conditional edges, invoke.

Why not the real thing (yet): three nodes and one conditional edge do not need a framework
(CLAUDE.md: no framework where 30 lines would do). The API mirrors LangGraph on purpose, so
switching is an import change once you want its checkpointing or streaming:

    from langgraph.graph import StateGraph, START, END

Semantics kept identical: a node receives the full state and returns a partial update that is
merged in; a conditional edge maps router(state) through path_map to the next node.
"""
from __future__ import annotations

START, END = "__start__", "__end__"


class StateGraph:
    def __init__(self, state_schema=dict):
        self.state_schema = state_schema
        self.nodes: dict[str, callable] = {}
        self.edges: dict[str, str] = {}
        self.branches: dict[str, tuple] = {}

    def add_node(self, name: str, fn) -> "StateGraph":
        self.nodes[name] = fn
        return self

    def add_edge(self, src: str, dst: str) -> "StateGraph":
        self.edges[src] = dst
        return self

    def add_conditional_edges(self, src: str, router, path_map: dict | None = None) -> "StateGraph":
        self.branches[src] = (router, path_map)
        return self

    def compile(self) -> "CompiledGraph":
        for src, dst in self.edges.items():
            assert src in self.nodes or src == START, f"edge from unknown node {src}"
            assert dst in self.nodes or dst == END, f"edge to unknown node {dst}"
        return CompiledGraph(self)


class CompiledGraph:
    def __init__(self, graph: StateGraph):
        self.g = graph

    def invoke(self, state: dict, max_steps: int = 25) -> dict:
        state = dict(state)
        node = self.g.edges[START]
        for _ in range(max_steps):
            if node == END:
                return state
            state.update(self.g.nodes[node](state) or {})
            if node in self.g.branches:
                router, path_map = self.g.branches[node]
                key = router(state)
                node = path_map[key] if path_map else key
            else:
                node = self.g.edges.get(node, END)
        raise RuntimeError("graph exceeded max_steps (cycle?)")

    def edges(self) -> list[tuple[str, str, str]]:
        """(src, dst, kind) for drawing the graph on the dashboard."""
        out = [(s, d, "edge") for s, d in self.g.edges.items()]
        for s, (_, pm) in self.g.branches.items():
            out += [(s, d, f"if {k}") for k, d in (pm or {}).items()]
        return out
