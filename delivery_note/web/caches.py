"""API 进程内的资料、分页检查和草稿分析缓存。"""

from collections import OrderedDict
from concurrent.futures import Future
from pathlib import Path
from threading import Lock
from typing import Any, Callable, TypedDict

import pandas as pd

from ..excel_io import read_position_workbook
from ..input_inspection import (
    inspect_input_version_with_preview,
    preview_input_version_page,
)
from .models import InputVersion


class _InspectionEntry(TypedDict):
    summary: dict[str, Any]
    pages: OrderedDict[tuple[int, int], dict[str, Any]]


class InputInspectionCache:
    """按版本缓存摘要和少量页面，并协调并发加载。"""

    def __init__(self, max_entries: int, max_pages_per_version: int = 4) -> None:
        if max_entries <= 0 or max_pages_per_version <= 0:
            raise ValueError("输入检查缓存容量必须大于 0")
        self._max_entries = max_entries
        self._max_pages_per_version = max_pages_per_version
        self._inspections: OrderedDict[int, _InspectionEntry] = OrderedDict()
        self._version_loads: dict[int, Future[None]] = {}
        self._page_loads: dict[tuple[int, int, int], Future[dict[str, Any]]] = {}
        self._lock = Lock()

    def inspect(self, version: InputVersion, offset: int, limit: int) -> dict:
        return self.get(
            version.id,
            offset,
            limit,
            lambda: inspect_input_version_with_preview(
                version.kind, Path(version.storage_path), offset, limit
            ),
            lambda summary: preview_input_version_page(
                version.kind, Path(version.storage_path), offset, limit, summary
            ),
        )

    @staticmethod
    def _result(entry: _InspectionEntry, page_key: tuple[int, int]) -> dict[str, Any]:
        return {
            "summary": entry["summary"],
            "preview": entry["pages"][page_key],
        }

    def _store_page(
        self,
        entry: _InspectionEntry,
        page_key: tuple[int, int],
        preview: dict[str, Any],
    ) -> None:
        pages = entry["pages"]
        pages[page_key] = preview
        pages.move_to_end(page_key)
        if len(pages) > self._max_pages_per_version:
            pages.popitem(last=False)

    def get(
        self,
        version_id: int,
        offset: int,
        limit: int,
        loader: Callable[[], dict[str, Any]],
        page_loader: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        page_key = (offset, limit)
        with self._lock:
            entry = self._inspections.get(version_id)
            if entry is not None:
                self._inspections.move_to_end(version_id)
                if page_key in entry["pages"]:
                    entry["pages"].move_to_end(page_key)
                    return self._result(entry, page_key)
                load_key = (version_id, offset, limit)
                pending_page = self._page_loads.get(load_key)
                load_page = pending_page is None
                page_future: Future[dict[str, Any]] = (
                    pending_page if pending_page is not None else Future()
                )
                if load_page:
                    self._page_loads[load_key] = page_future
            else:
                pending_version = self._version_loads.get(version_id)
                load_version = pending_version is None
                version_future: Future[None] = (
                    pending_version if pending_version is not None else Future()
                )
                if load_version:
                    self._version_loads[version_id] = version_future

        if entry is None:
            if not load_version:
                version_future.result()
                return self.get(version_id, offset, limit, loader, page_loader)
            return self._load_version(version_id, page_key, loader, version_future)

        if not load_page:
            preview = page_future.result()
            return {"summary": entry["summary"], "preview": preview}

        return self._load_page(load_key, entry, page_loader, page_future)

    def _load_version(
        self,
        version_id: int,
        page_key: tuple[int, int],
        loader: Callable[[], dict[str, Any]],
        future: Future[None],
    ) -> dict[str, Any]:
        """加载版本摘要及首个页面，并向等待者传递加载结果。"""
        try:
            inspection = loader()
            entry: _InspectionEntry = {
                "summary": inspection["summary"],
                "pages": OrderedDict(),
            }
            self._store_page(entry, page_key, inspection["preview"])
        except BaseException as error:
            with self._lock:
                self._version_loads.pop(version_id, None)
            future.set_exception(error)
            raise

        with self._lock:
            self._inspections[version_id] = entry
            self._inspections.move_to_end(version_id)
            if len(self._inspections) > self._max_entries:
                self._inspections.popitem(last=False)
            self._version_loads.pop(version_id, None)
        future.set_result(None)
        return self._result(entry, page_key)

    def _load_page(
        self,
        load_key: tuple[int, int, int],
        entry: _InspectionEntry,
        loader: Callable[[dict[str, Any]], dict[str, Any]],
        future: Future[dict[str, Any]],
    ) -> dict[str, Any]:
        """只加载缺失页面，不重复检查整个版本。"""
        try:
            preview = loader(entry["summary"])
        except BaseException as error:
            with self._lock:
                self._page_loads.pop(load_key, None)
            future.set_exception(error)
            raise

        with self._lock:
            current_entry = self._inspections.get(load_key[0])
            if current_entry is entry:
                self._store_page(entry, (load_key[1], load_key[2]), preview)
            self._page_loads.pop(load_key, None)
        future.set_result(preview)
        return {"summary": entry["summary"], "preview": preview}


class PositionFrameCache:
    """按最近使用顺序缓存不可变的库位资料版本。"""

    def __init__(self, max_entries: int) -> None:
        if max_entries <= 0:
            raise ValueError("库位资料缓存容量必须大于 0")
        self._max_entries = max_entries
        self._frames: OrderedDict[int, pd.DataFrame] = OrderedDict()
        self._lock = Lock()

    def get(
        self,
        version_id: int,
        path: Path,
        loader: Callable[[Path], pd.DataFrame] | None = None,
    ) -> pd.DataFrame:
        frame_loader = loader or read_position_workbook
        with self._lock:
            frame = self._frames.get(version_id)
            if frame is not None:
                self._frames.move_to_end(version_id)
                return frame

            frame = frame_loader(path)
            self._frames[version_id] = frame
            if len(self._frames) > self._max_entries:
                self._frames.popitem(last=False)
            return frame


class DraftAnalysisCache:
    """按草稿修订缓存纯数据分析结果，不保留跨会话 ORM 实体。"""

    def __init__(self, max_entries: int) -> None:
        if max_entries <= 0:
            raise ValueError("草稿分析缓存容量必须大于 0")
        self._max_entries = max_entries
        self._analyses: OrderedDict[tuple[int, int], dict[str, Any]] = OrderedDict()
        self._lock = Lock()

    def get(
        self,
        draft_id: int,
        revision: int,
        loader: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        key = (draft_id, revision)
        with self._lock:
            analysis = self._analyses.get(key)
            if analysis is not None:
                self._analyses.move_to_end(key)
                return analysis

            analysis = loader()
            self._analyses[key] = analysis
            if len(self._analyses) > self._max_entries:
                self._analyses.popitem(last=False)
            return analysis
