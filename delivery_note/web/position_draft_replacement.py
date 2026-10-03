from collections import defaultdict, deque

import pandas as pd
from sqlalchemy import delete
from sqlalchemy.orm import Session

from ..inspection.positions import position_diff
from ..processing.models import (POSITION_SOURCE_COLUMNS)
from .models import InputDraft, PositionDraftRow
from .position_draft_state import list_draft_rows
from .position_draft_state import (
    _audit,
    _flush_revision,
    _identity,
    _make_row,
    _record_values,
    _signature,
    load_base_frame,
    position_frame,
    require_revision,
    touch_draft,
)


def replace_draft_from_frame(
    session: Session,
    draft: InputDraft,
    expected_revision: int,
    user_id: int,
    frame: pd.DataFrame,
) -> dict[str, int]:
    require_revision(draft, expected_revision)
    candidate = frame[POSITION_SOURCE_COLUMNS].copy()
    current = position_frame(list_draft_rows(session, draft.id))
    base = load_base_frame(session, draft)
    diff = position_diff(current, candidate)

    base_rows: dict[tuple[str, str, str], deque[tuple[int, dict[str, str]]]] = (
        defaultdict(deque)
    )
    for offset, record in enumerate(base.to_dict("records"), start=2):
        values = _record_values(record)
        base_rows[_identity(values)].append((offset, values))

    replacement_rows: list[PositionDraftRow] = []
    for row_order, record in enumerate(candidate.to_dict("records"), start=1):
        values = _record_values(record)
        matches = base_rows[_identity(values)]
        if matches:
            base_row_number, base_values = matches.popleft()
            change_type = (
                "unchanged"
                if _signature(values) == _signature(base_values)
                else "modified"
            )
        else:
            base_row_number = None
            change_type = "added"
        replacement_rows.append(
            _make_row(
                draft_id=draft.id,
                row_order=row_order,
                values=values,
                base_row_number=base_row_number,
                change_type=change_type,
            )
        )

    next_order = len(replacement_rows) + 1
    deleted_base_rows = sorted(
        (item for matches in base_rows.values() for item in matches),
        key=lambda item: item[0],
    )
    for base_row_number, values in deleted_base_rows:
        replacement_rows.append(
            _make_row(
                draft_id=draft.id,
                row_order=next_order,
                values=values,
                base_row_number=base_row_number,
                change_type="deleted",
            )
        )
        next_order += 1

    session.execute(
        delete(PositionDraftRow).where(PositionDraftRow.draft_id == draft.id)
    )
    session.add_all(replacement_rows)
    touch_draft(draft, user_id)
    _audit(session, user_id, "import_input_draft", draft.id, {"diff": diff})
    _flush_revision(session)
    return diff
