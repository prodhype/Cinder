from __future__ import annotations

import heapq
from dataclasses import dataclass

from cinder.diagnostics import Span
from cinder.symbols import LockSymbol


@dataclass(frozen=True, slots=True)
class LockConstraint:
    before: str
    after: str
    span: Span
    explicit: bool


class LockOrderGraph:
    def __init__(self) -> None:
        self.nodes: dict[str, LockSymbol] = {}
        self.edges: dict[str, dict[str, LockConstraint]] = {}

    def add_lock(self, lock: LockSymbol) -> LockSymbol | None:
        previous = self.nodes.get(lock.qualified_name)
        if previous is not None:
            return previous
        self.nodes[lock.qualified_name] = lock
        self.edges.setdefault(lock.qualified_name, {})
        return None

    def add_constraint(
        self,
        before: LockSymbol,
        after: LockSymbol,
        span: Span,
        *,
        explicit: bool,
    ) -> None:
        targets = self.edges.setdefault(before.qualified_name, {})
        previous = targets.get(after.qualified_name)
        if previous is None or (explicit and not previous.explicit):
            targets[after.qualified_name] = LockConstraint(
                before.qualified_name,
                after.qualified_name,
                span,
                explicit,
            )

    def path(self, start: str, target: str) -> tuple[str, ...] | None:
        if start == target:
            return (start,)
        pending: list[tuple[str, tuple[str, ...]]] = [(start, (start,))]
        visited = {start}
        while pending:
            current, prefix = pending.pop()
            for successor in sorted(self.edges.get(current, {}), reverse=True):
                if successor == target:
                    return (*prefix, successor)
                if successor not in visited:
                    visited.add(successor)
                    pending.append((successor, (*prefix, successor)))
        return None

    def find_cycle(self) -> tuple[str, ...] | None:
        visiting: set[str] = set()
        visited: set[str] = set()
        stack: list[str] = []

        def visit(node: str) -> tuple[str, ...] | None:
            if node in visiting:
                start = stack.index(node)
                return (*stack[start:], node)
            if node in visited:
                return None
            visiting.add(node)
            stack.append(node)
            for successor in sorted(self.edges.get(node, {})):
                cycle = visit(successor)
                if cycle is not None:
                    return cycle
            stack.pop()
            visiting.remove(node)
            visited.add(node)
            return None

        for node in sorted(self.nodes):
            cycle = visit(node)
            if cycle is not None:
                return cycle
        return None

    def cycle_constraint(self, cycle: tuple[str, ...]) -> LockConstraint | None:
        if len(cycle) < 2:
            return None
        return self.edges.get(cycle[-2], {}).get(cycle[-1])

    def assign_canonical_keys(self) -> tuple[str, ...]:
        indegree = dict.fromkeys(self.nodes, 0)
        for targets in self.edges.values():
            for target in targets:
                indegree[target] += 1
        ready = [node for node, count in indegree.items() if count == 0]
        heapq.heapify(ready)
        ordered: list[str] = []
        while ready:
            node = heapq.heappop(ready)
            ordered.append(node)
            for successor in sorted(self.edges.get(node, {})):
                indegree[successor] -= 1
                if indegree[successor] == 0:
                    heapq.heappush(ready, successor)
        if len(ordered) != len(self.nodes):
            raise ValueError("lock order graph contains a cycle")
        for key, name in enumerate(ordered):
            self.nodes[name].canonical_key = key
        return tuple(ordered)

    @staticmethod
    def display_name(qualified_name: str) -> str:
        return qualified_name.rsplit("::", 1)[-1]

