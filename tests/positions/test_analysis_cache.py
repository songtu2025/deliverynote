from tests.support.position_drafts import PositionDraftCase
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, BrokenBarrierError


import delivery_note.web.caches as cache_module


class PositionDraftTests(PositionDraftCase):
    def test_draft_analysis_cache_is_bounded_and_serializes_same_revision(self):
        cache = cache_module.DraftAnalysisCache(max_entries=2)
        loaded_keys: list[tuple[int, int]] = []

        def load(key):
            loaded_keys.append(key)
            return {"key": key}

        first = cache.get(1, 1, lambda: load((1, 1)))
        cache.get(2, 1, lambda: load((2, 1)))
        self.assertIs(cache.get(1, 1, lambda: load((1, 1))), first)
        cache.get(3, 1, lambda: load((3, 1)))
        cache.get(2, 1, lambda: load((2, 1)))
        self.assertEqual(loaded_keys, [(1, 1), (2, 1), (3, 1), (2, 1)])

        concurrent_cache = cache_module.DraftAnalysisCache(max_entries=2)
        concurrent_loads = 0
        concurrent_misses = Barrier(2)

        def load_once():
            nonlocal concurrent_loads
            concurrent_loads += 1
            try:
                concurrent_misses.wait(timeout=0.2)
            except BrokenBarrierError:
                pass
            return {"revision": 1}

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(concurrent_cache.get, 1, 1, load_once) for _ in range(2)
            ]
            analyses = [future.result(timeout=5) for future in futures]

        self.assertEqual(concurrent_loads, 1)
        self.assertIs(analyses[0], analyses[1])
