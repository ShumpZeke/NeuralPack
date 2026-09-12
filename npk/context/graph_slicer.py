"""Program Dependency Graph Slicer for Multi-Module Context Slicing."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple


class ProgramGraphSlicer:
    def build_dependency_graph(self, blocks: List[Dict[str, Any]]) -> Tuple[Dict[int, Set[int]], Dict[str, int]]:
        """
        Constructs directed dependency graph over code blocks:
        Edge i -> j exists if block i imports or calls symbols defined in block j.
        """
        n = len(blocks)
        edges: Dict[int, Set[int]] = {i: set() for i in range(n)}
        defs: Dict[str, int] = {}
        module_map: Dict[str, int] = {}

        # Pass 1: Index definitions and module names
        for i, b in enumerate(blocks):
            name = b.get("name", "").strip()
            mod_name = name.replace(".py", "").replace(".ts", "").replace(".js", "").split("/")[-1].strip()
            if mod_name:
                module_map[mod_name] = i
                defs[mod_name] = i

            body = b.get("content", "")
            # Extract defs: functions, classes, uppercase constants
            func_defs = re.findall(r"\b(?:def|class|function)\s+([a-zA-Z_][a-zA-Z0-9_]*)\b", body)
            const_defs = re.findall(r"^([A-Z_][A-Z0-9_]{2,})\s*=", body, flags=re.MULTILINE)
            for sym in func_defs + const_defs:
                defs[sym] = i

        # Pass 2: Extract call/import references and connect edges
        for i, b in enumerate(blocks):
            body = b.get("content", "")
            # Imports: from x import y OR import x
            imported_modules = re.findall(r"(?:from|import)\s+([a-zA-Z0-9_.]+)", body)
            for imp in imported_modules:
                leaf = imp.split(".")[-1]
                if leaf in module_map and module_map[leaf] != i:
                    edges[i].add(module_map[leaf])

            # Calls & Constant references
            called_symbols = re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", body)
            referenced_constants = re.findall(r"\b([A-Z_][A-Z0-9_]{2,})\b", body)
            for sym in set(called_symbols + referenced_constants):
                if sym in defs and defs[sym] != i:
                    edges[i].add(defs[sym])

        return edges, defs

    def compute_transitive_closure(
        self,
        seed_nodes: Set[int],
        edges: Dict[int, Set[int]],
        max_depth: int = 2,
        block_costs: Optional[Sequence[int]] = None,
        token_budget: Optional[int] = None,
    ) -> Set[int]:
        """Bounded-depth reachability expansion from ``seed_nodes``.

        This is a **bounded BFS, not a transitive closure**. It only reaches
        nodes within ``max_depth`` hops, so it provides no recall guarantee for
        dependency chains longer than that (see
        ``research/math/INDEPENDENT_MATH_AUDIT.md``, Theorem 3').

        Two audit findings are addressed here:

        * ``Closure_D(emptyset) = emptyset`` -- expansion cannot manufacture
          evidence from an empty seed set. Callers must detect a failed seed
          stage *before* calling this.
        * Expansion previously ignored the token budget, so a budget-respecting
          selection could be expanded back over budget. When ``block_costs`` and
          ``token_budget`` are supplied, expansion stops at the budget.
        """
        reachable: Set[int] = set(seed_nodes)
        if not reachable:
            return reachable

        budget_enforced = block_costs is not None and token_budget is not None
        used = sum(block_costs[i] for i in reachable) if budget_enforced else 0

        current_frontier = set(seed_nodes)
        for _ in range(max_depth):
            next_frontier: Set[int] = set()
            for u in sorted(current_frontier):
                for v in sorted(edges.get(u, set())):
                    if v in reachable:
                        continue
                    if budget_enforced:
                        cost = block_costs[v]
                        if used + cost > token_budget:
                            continue
                        used += cost
                    reachable.add(v)
                    next_frontier.add(v)
            current_frontier = next_frontier
            if not current_frontier:
                break
        return reachable
