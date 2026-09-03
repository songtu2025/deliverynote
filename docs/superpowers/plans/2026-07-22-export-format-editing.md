# Export Excel Format Editing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow users to change cell formatting, column widths, and row heights after opening generated delivery workbooks while keeping protected header content and the A:G import structure unchanged.

**Architecture:** Extend the existing `_protect_header_only` helper in the shared OpenPyXL writer so both generated worksheets keep protection enabled but permit formatting operations. The Web worker and CLI already call `write_delivery_workbook`, so one focused backend change covers single-file downloads, batch ZIP contents, and CLI output without API, database, or frontend changes.

**Tech Stack:** Python 3.11, OpenPyXL, pandas, `unittest`, Docker Compose

## Global Constraints

- Keep worksheet protection enabled.
- Keep rows 1 and 2, including the official A:G import headers, content-locked.
- Allow formatting cells, columns, and rows, including fonts, colors, fills, borders, alignment, wrapping, column widths, and row heights.
- Keep data cells from row 3 onward editable.
- Preserve existing A:G fields, field order, template-provided initial styles, output naming, and business data.
- Apply the same behavior to Web single-file exports, files inside batch ZIP archives, and CLI output through the shared writer.
- Do not add a Web configuration UI, database fields, dependencies, or a second export variant.
- Do not change purchase matching, quantity conservation, split behavior, ERP write-back behavior, or Excel data content.
- Use TDD: demonstrate the regression test failing before modifying production code.

## File Map

- Modify `tests/test_excel_io.py`: assert the serialized protection permissions for both generated worksheets while retaining the existing header/data lock assertions.
- Modify `delivery_note/excel_io.py`: configure the protected worksheets to permit cell, column, and row formatting and selecting locked header cells.
- Reference `docs/superpowers/specs/2026-07-22-export-format-editing-design.md`: approved behavior and acceptance criteria; no changes expected during implementation.

---

### Task 1: Permit formatting without unlocking header content

**Files:**
- Modify: `tests/test_excel_io.py:189-225`
- Modify: `delivery_note/excel_io.py:180-196`

**Interfaces:**
- Consumes: `_protect_header_only(sheet) -> None`, called by `write_delivery_workbook(...)` for “交货导入” and “待处理导入”.
- Produces: protected OpenPyXL worksheets with `sheet=True`, `formatCells=False`, `formatColumns=False`, `formatRows=False`, and `selectLockedCells=False`; rows 1–2 remain locked and rows 3+ remain unlocked.

- [ ] **Step 1: Add the failing serialized-workbook regression assertions**

In `ExcelOutputTests.test_write_delivery_workbook_contains_import_details_and_editable_pending_rows`, insert the following block immediately after the sheet-name assertions and before the existing cell protection assertions:

```python
        for sheet_name in ("交货导入", "待处理导入"):
            protection = workbook[sheet_name].protection
            self.assertTrue(protection.sheet)
            self.assertFalse(protection.formatCells)
            self.assertFalse(protection.formatColumns)
            self.assertFalse(protection.formatRows)
            self.assertFalse(protection.selectLockedCells)
```

Keep the existing assertions that verify `A1` and `A2` are locked, `A3` and later data cells are unlocked, headers/data are unchanged, and template widths/heights remain present. Reading the workbook back from `output_path` is required because the feature depends on serialized XLSX protection attributes rather than only in-memory values.

- [ ] **Step 2: Run the focused test and confirm the expected failure**

Run:

```bash
/root/deliverynote/.venv/bin/python -m unittest tests.test_excel_io.ExcelOutputTests.test_write_delivery_workbook_contains_import_details_and_editable_pending_rows -v
```

Expected: `FAIL`, with the first new format-permission assertion reporting `AssertionError: True is not false`. This proves the current exported workbook blocks at least one requested formatting operation.

- [ ] **Step 3: Implement the minimal protection-permission change**

Update `_protect_header_only` in `delivery_note/excel_io.py` so its opening block is exactly:

```python
def _protect_header_only(sheet) -> None:
    """锁定前两行内容，同时允许用户调整导出文件格式。"""
    sheet.protection.sheet = True
    sheet.protection.formatCells = False
    sheet.protection.formatColumns = False
    sheet.protection.formatRows = False
    sheet.protection.selectLockedCells = False
```

Leave both existing cell loops unchanged:

```python
    for row in sheet.iter_rows(
        min_row=1, max_row=2, min_col=1, max_col=sheet.max_column
    ):
        for cell in row:
            cell._style = copy(cell._style)
            cell.protection = Protection(locked=True, hidden=True)
    for row in sheet.iter_rows(
        min_row=3, max_row=sheet.max_row, min_col=1, max_col=sheet.max_column
    ):
        for cell in row:
            cell._style = copy(cell._style)
            protection = copy(cell.protection)
            protection.locked = False
            cell.protection = protection
```

Do not set `sheet.protection.sheet = False`, do not remove `hidden=True` from protected header cells, and do not change `_populate_import_sheet`, `_populate_pending_position_columns`, or any output data.

- [ ] **Step 4: Run the focused test and confirm it passes**

Run:

```bash
/root/deliverynote/.venv/bin/python -m unittest tests.test_excel_io.ExcelOutputTests.test_write_delivery_workbook_contains_import_details_and_editable_pending_rows -v
```

Expected: `Ran 1 test` followed by `OK`.

- [ ] **Step 5: Run the complete Python verification required by the repository**

Run:

```bash
/root/deliverynote/.venv/bin/python -m unittest discover -s tests -v
/root/deliverynote/.venv/bin/python -m pip check
```

Expected: all 108 Python tests pass and `pip check` prints `No broken requirements found.` If the test count has increased because another approved change landed first, every discovered test must still pass.

- [ ] **Step 6: Verify the shared branch build and deployment configuration**

Run:

```bash
cd frontend
npm run test
npm run build
cd ..
WEB_PORT=18081 docker compose --env-file /root/deliverynote/.env -p deliverynoteqa config --quiet
git diff --check
```

Expected: all 55 frontend tests pass, the Vite production build succeeds, Compose exits with status 0 and no output, and `git diff --check` exits with status 0. The known Vite bundle-size warning is acceptable; test, build, or Compose errors are not.

- [ ] **Step 7: Review the exact diff and commit the independently verified change**

Run:

```bash
git diff -- tests/test_excel_io.py delivery_note/excel_io.py
git status --short
git add tests/test_excel_io.py delivery_note/excel_io.py
git diff --cached --name-only
git diff --cached --check
git commit -m "feat: allow formatting protected exports"
```

Expected staged paths before commit:

```text
delivery_note/excel_io.py
tests/test_excel_io.py
```

The commit must contain no `.env`, Excel workbook, database, log, upload, export, screenshot, or unrelated branch file.

- [ ] **Step 8: Record the release checkpoint without deploying unreviewed code**

Run:

```bash
git status -sb
git log -2 --oneline --decorate
```

Expected: the feature worktree is clean and the new feature commit is at `HEAD`. Request a fresh code review before any production rebuild. Production deployment remains a separate authorized release action and must also account for the two pre-existing administrator-maintenance review findings already tracked on this branch.
