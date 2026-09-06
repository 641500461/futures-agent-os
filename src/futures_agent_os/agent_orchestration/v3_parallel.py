from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable


class ParallelFanout:
    def __init__(self, max_workers: int = 3):
        if max_workers < 1:
            raise ValueError("max_workers must be positive")
        self.max_workers = max_workers

    def run(self, tasks: dict[str, Callable[[], object]]) -> dict[str, object]:
        if not tasks:
            return {}
        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(tasks))) as pool:
            futures = {k: pool.submit(fn) for k, fn in tasks.items()}
            return {k: futures[k].result() for k in tasks}
