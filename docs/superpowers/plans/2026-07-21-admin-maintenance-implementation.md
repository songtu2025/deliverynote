# Admin Maintenance Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a PC-first administrator workspace that explains and previews all five input types and gives position data durable server drafts, row CRUD, Excel replacement, validation, and immutable version publishing.

**Architecture:** Keep `InputVersion` Excel files as the only source consumed by batches, CLI, and Worker. Add focused inspection helpers plus two maintenance-only tables (`input_drafts`, `position_draft_rows`); all web edits stay in one server draft until an atomic publish generates a new `MSKU_视图` workbook and activates a new `InputVersion`. Split the React administrator page into focused PC components so the input catalog, position editor, users, and audit history remain understandable independently.

**Tech Stack:** Python 3.11, pandas/openpyxl, FastAPI, SQLAlchemy, PostgreSQL/SQLite, React 19, TypeScript, Ant Design 6, Vitest, Docker Compose, Google Chrome.

## Global Constraints

- Preserve `交货总量 = 可导入总量 + 待处理总量` and every existing batch allocation rule.
- Do not change purchase matching, warehouse priority, split behavior, CLI inputs, template A:G output, delivery notes, or export naming.
- Existing batches must keep their locked `InputVersion` IDs and files.
- PC is the only design target; verify 1440×900 and 1920×1080.
- Do not introduce Redis, Celery, a new service, or a new frontend state library.
- Use new tables only; do not alter existing table columns while formal migrations are unavailable.
- Preserve all pre-existing working-tree changes. Stage exact paths, inspect `git diff --cached`, and defer a commit when an overlapping dirty file cannot be isolated safely.

## File Map

- Create `delivery_note/input_inspection.py`: read, summarize, preview, validate, diff, and write supported master-data workbooks.
- Modify `delivery_note/web/models.py`: add server draft metadata and normalized position draft rows.
- Create `delivery_note/web/position_drafts.py`: draft lifecycle, row mutation, import replacement, validation, and publish service.
- Modify `delivery_note/web/api.py`: Pydantic payloads and authenticated inspection/draft endpoints.
- Create `tests/test_input_inspection.py`: pure workbook inspection and position quality tests.
- Create `tests/test_position_drafts.py`: API-level draft persistence, revision conflict, import, and publish tests.
- Modify `tests/asgi_client.py`: add the DELETE convenience method used by draft API tests.
- Modify `frontend/src/types.ts`: inspection, draft, row, issue, and diff contracts.
- Create `frontend/src/pages/admin/adminConstants.ts`: type labels, descriptions, required fields, and audit labels.
- Create `frontend/src/pages/admin/InputDataPanel.tsx`: PC master-detail input catalog.
- Create `frontend/src/pages/admin/PositionMaintenance.tsx`: draft table, filters, row drawer, import preview, and publish flow.
- Create `frontend/src/pages/admin/UserManagementPanel.tsx`: current user actions in a focused component.
- Create `frontend/src/pages/admin/AuditLogPanel.tsx`: current audit table with clearer labels.
- Modify `frontend/src/pages/AdminPage.tsx`: compose the three administrator sections.
- Create `frontend/src/pages/admin/InputDataPanel.test.tsx` and `PositionMaintenance.test.tsx`: focused interaction tests.
- Modify `frontend/src/pages/AdminPage.test.tsx`: integration coverage for administrator tabs.
- Modify `frontend/src/styles.css`: PC master-detail, toolbar, table, issue, and drawer styling.
- Modify `README.md`, `HANDOFF_WEB_UPGRADE.md`, and `UI_UX_OPTIMIZATION_PLAN.md`: behavior, verification, and rollout notes.

---

### Task 1: Workbook Inspection and Position Validation

**Files:**
- Create: `delivery_note/input_inspection.py`
- Create: `tests/test_input_inspection.py`

**Interfaces:**
- Consumes: existing `read_purchase_workbook`, `read_product_workbook`, `read_supplier_workbook`, `read_position_workbook`, `validate_template_workbook`, `POSITION_SOURCE_COLUMNS`.
- Produces: `inspect_input_version(kind: str, path: Path) -> dict`, `preview_input_version(kind: str, path: Path, offset: int, limit: int) -> dict`, `validate_position_frame(frame: pd.DataFrame) -> list[dict]`, `position_diff(base: pd.DataFrame, candidate: pd.DataFrame) -> dict[str, int]`, and `write_position_workbook(path: Path, frame: pd.DataFrame) -> None`.

- [ ] **Step 1: Write failing inspection and validation tests**

```python
class InputInspectionTests(unittest.TestCase):
    def test_position_summary_preview_and_quality_issues(self):
        frame = pd.DataFrame([
            ["SEEKWAY:US", "SKU-A", "MSKU-A", "短尾", "备货", 90],
            ["SEEKWAY:US", "SKU-A", "MSKU-A", "未知", "", "many"],
        ], columns=POSITION_SOURCE_COLUMNS)
        issues = validate_position_frame(frame)
        self.assertIn("duplicate_msku", {item["code"] for item in issues})
        self.assertIn("unknown_scale", {item["code"] for item in issues})
        self.assertIn("non_numeric_days", {item["code"] for item in issues})

    def test_written_position_workbook_round_trips(self):
        write_position_workbook(self.path, self.frame)
        self.assertEqual(
            read_position_workbook(self.path).to_dict("records"),
            self.frame.to_dict("records"),
        )
```

- [ ] **Step 2: Run the focused tests and verify the missing module failure**

Run: `.venv/bin/python -m unittest tests.test_input_inspection -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'delivery_note.input_inspection'`.

- [ ] **Step 3: Implement exact inspection contracts**

```python
POSITION_KEY = ["店铺-站点", "积加SKU", "MSKU"]

def inspect_input_version(kind: str, path: Path) -> dict:
    frame = _read_frame(kind, path)
    result = {
        "kind": kind,
        "row_count": len(frame),
        "columns": [str(column) for column in frame.columns],
        "metrics": {},
        "issues": [],
    }
    if kind == "position":
        result["metrics"] = {
            "sites": int(frame["店铺-站点"].dropna().astype(str).str.strip().nunique()),
            "skus": int(frame["积加SKU"].dropna().astype(str).str.strip().nunique()),
            "mskus": int(frame["MSKU"].dropna().astype(str).str.strip().nunique()),
        }
        result["issues"] = validate_position_frame(frame)
    return result

def write_position_workbook(path: Path, frame: pd.DataFrame) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "MSKU_视图"
    sheet.append(POSITION_SOURCE_COLUMNS)
    for values in frame[POSITION_SOURCE_COLUMNS].itertuples(index=False, name=None):
        sheet.append([None if pd.isna(value) else value for value in values])
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
```

Implement `_read_frame` for all five kinds; templates expose row 2 headers and row 3+ preview values. Serialize pandas/NumPy values to JSON-safe primitives. Return errors for empty site/SKU and duplicate composite keys; return warnings for unknown scale, empty stocking value, and non-numeric ordered days.

- [ ] **Step 4: Run focused tests**

Run: `.venv/bin/python -m unittest tests.test_input_inspection -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit the focused helper when safe**

```bash
git add delivery_note/input_inspection.py tests/test_input_inspection.py
git diff --cached --check
git commit -m "feat: inspect and validate input workbooks"
```

### Task 2: Durable Draft Models and Lifecycle Service

**Files:**
- Modify: `delivery_note/web/models.py`
- Create: `delivery_note/web/position_drafts.py`
- Create: `tests/test_position_drafts.py`

**Interfaces:**
- Consumes: Task 1 validation/diff/write helpers, `InputVersion`, `AuditLog`, and SQLAlchemy `Session`.
- Produces: `InputDraft`, `PositionDraftRow`, `create_or_resume_draft`, `list_draft_rows`, `mutate_draft_row`, `replace_draft_from_frame`, `validate_draft`, `publish_draft`, and `discard_draft`.

- [ ] **Step 1: Write failing model/lifecycle tests**

```python
def test_draft_copies_active_version_and_survives_new_login(self):
    created = self.client.post("/api/input-drafts/position", headers=self.admin_headers)
    self.assertEqual(created.status_code, 201, created.text)
    second_headers = self.login("admin", "admin-pass")
    resumed = self.client.post("/api/input-drafts/position", headers=second_headers)
    self.assertEqual(resumed.json()["id"], created.json()["id"])
    self.assertEqual(resumed.json()["row_count"], 1)

def test_stale_revision_is_rejected(self):
    draft = self.create_draft()
    payload = {"revision": draft["revision"], **self.valid_row}
    first = self.client.post(f"/api/input-drafts/{draft['id']}/rows", headers=self.admin_headers, json=payload)
    stale = self.client.post(f"/api/input-drafts/{draft['id']}/rows", headers=self.admin_headers, json=payload)
    self.assertEqual(first.status_code, 201)
    self.assertEqual(stale.status_code, 409)
```

- [ ] **Step 2: Run the focused tests and confirm missing endpoints/models**

Run: `.venv/bin/python -m unittest tests.test_position_drafts -v`

Expected: FAIL because `/api/input-drafts/position` returns 404.

- [ ] **Step 3: Add maintenance-only models**

```python
class InputDraft(Base):
    __tablename__ = "input_drafts"
    __table_args__ = (
        Index("uq_editing_input_draft_kind", "kind", unique=True,
              postgresql_where=text("status = 'editing'"),
              sqlite_where=text("status = 'editing'")),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(30), index=True)
    base_version_id: Mapped[int] = mapped_column(ForeignKey("input_versions.id"))
    status: Mapped[str] = mapped_column(String(20), default="editing", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

class PositionDraftRow(Base):
    __tablename__ = "position_draft_rows"
    id: Mapped[int] = mapped_column(primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("input_drafts.id"), index=True)
    row_order: Mapped[int] = mapped_column(Integer)
    base_row_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    store_site: Mapped[str] = mapped_column(Text, default="")
    jiaji_sku: Mapped[str] = mapped_column(Text, default="")
    msku: Mapped[str] = mapped_column(Text, default="")
    scale_position: Mapped[str] = mapped_column(Text, default="")
    stocking_position: Mapped[str] = mapped_column(Text, default="")
    ordered_days: Mapped[str] = mapped_column(Text, default="")
    change_type: Mapped[str] = mapped_column(String(20), default="unchanged")
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
```

- [ ] **Step 4: Implement lifecycle service with optimistic revision checks**

```python
class DraftConflict(Exception):
    pass

def require_revision(draft: InputDraft, expected_revision: int) -> None:
    if draft.status != "editing" or draft.revision != expected_revision:
        raise DraftConflict

def touch_draft(draft: InputDraft, user_id: int) -> None:
    draft.revision += 1
    draft.updated_by = user_id
    draft.updated_at = utcnow()
```

Copy the active workbook into rows on first creation. Keep `base_row_number` for original rows, set copied rows to `unchanged`, new rows to `added`, changed originals to `modified`, and soft-delete original rows as `deleted`. Deleting an `added` row removes it physically. Build validation frames without deleted rows.

- [ ] **Step 5: Run model/lifecycle tests**

Run: `.venv/bin/python -m unittest tests.test_position_drafts -v`

Expected: lifecycle and revision tests PASS; endpoint-only tests may remain skipped until Task 3 only if explicitly decorated for that boundary.

- [ ] **Step 6: Commit model and service paths when safe**

```bash
git add delivery_note/web/models.py delivery_note/web/position_drafts.py tests/test_position_drafts.py
git diff --cached --check
git commit -m "feat: persist position maintenance drafts"
```

### Task 3: Inspection and Draft APIs

**Files:**
- Modify: `delivery_note/web/api.py`
- Modify: `tests/test_position_drafts.py`
- Modify: `tests/asgi_client.py`

**Interfaces:**
- Consumes: Task 1 inspection functions and Task 2 service functions/models.
- Produces: authenticated endpoints from design sections 8 and 9 with JSON contracts used by the frontend.

- [ ] **Step 1: Add failing API contract tests**

```python
def test_version_summary_preview_and_download(self):
    version_id = self.upload_position()["id"]
    summary = self.client.get(f"/api/input-versions/{version_id}/summary", headers=self.admin_headers)
    preview = self.client.get(f"/api/input-versions/{version_id}/preview?limit=20", headers=self.admin_headers)
    download = self.client.get(f"/api/input-versions/{version_id}/download", headers=self.admin_headers)
    self.assertEqual(summary.json()["metrics"]["sites"], 1)
    self.assertEqual(preview.json()["rows"][0]["积加SKU"], "SKU-A")
    self.assertEqual(download.status_code, 200)

def test_publish_creates_new_active_version_without_mutating_base(self):
    draft = self.create_draft()
    published = self.client.post(
        f"/api/input-drafts/{draft['id']}/publish",
        headers=self.admin_headers,
        json={"revision": draft["revision"], "name": "position-v2", "confirm_warnings": True},
    )
    self.assertEqual(published.status_code, 201, published.text)
    self.assertNotEqual(published.json()["id"], draft["base_version_id"])
    self.assertTrue(published.json()["active"])
```

Add the synchronous DELETE facade used by row and draft tests:

```python
def delete(self, url: str, **kwargs) -> Response:
    return self.request("DELETE", url, **kwargs)
```

- [ ] **Step 2: Run the API tests and verify 404/422 failures**

Run: `.venv/bin/python -m unittest tests.test_position_drafts -v`

Expected: FAIL because inspection and draft routes are not registered.

- [ ] **Step 3: Add exact Pydantic payloads and serializers**

```python
class DraftMutationPayload(BaseModel):
    revision: int = Field(ge=1)

class PositionRowPayload(DraftMutationPayload):
    store_site: str = Field(min_length=1)
    jiaji_sku: str = Field(min_length=1)
    msku: str = ""
    scale_position: str = ""
    stocking_position: str = ""
    ordered_days: str = ""

class PublishDraftPayload(DraftMutationPayload):
    name: str = Field(min_length=1, max_length=200)
    confirm_warnings: bool = False
```

Return 403 for operators, 404 for missing versions/drafts, 409 for stale revisions or duplicate version names, and 422-style business details as HTTP 400 for invalid workbooks or publish errors, matching existing API message conventions.

- [ ] **Step 4: Register read-only inspection/download routes**

```python
@app.get("/api/input-versions/{version_id}/summary")
def input_version_summary(version_id: int, _admin=Depends(admin_user), session=Depends(get_session)):
    version = session.get(InputVersion, version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="输入版本不存在")
    return inspect_input_version(version.kind, Path(version.storage_path))
```

Add preview pagination bounds `offset >= 0`, `1 <= limit <= 200`, and use `FileResponse` with `version.original_name` for download.

- [ ] **Step 5: Register draft create/read/row/import/validate/publish/discard routes**

Map `DraftConflict` to HTTP 409 with `草稿已被其他管理员更新，请刷新后重试`. Ensure every successful mutation commits once, refreshes the draft, and returns the new revision. Import preview stores the parsed candidate in a server temporary file tied to draft ID/revision; apply rejects a token from an older revision and removes the temporary file after use.

- [ ] **Step 6: Run API and complete Python regressions**

Run: `.venv/bin/python -m unittest tests.test_position_drafts -v`

Expected: all draft API tests PASS.

Run: `.venv/bin/python -m unittest discover -s tests -v`

Expected: all existing 44 tests plus new tests PASS.

- [ ] **Step 7: Commit the API checkpoint only after inspecting overlap**

```bash
git add delivery_note/web/api.py tests/test_position_drafts.py tests/asgi_client.py
git diff --cached --name-only
git diff --cached --check
git commit -m "feat: expose position draft maintenance APIs"
```

If `delivery_note/web/api.py` contains inseparable pre-existing changes, leave this checkpoint uncommitted and report it instead of committing unrelated work.

### Task 4: PC Input Catalog and Version Inspection

**Files:**
- Modify: `frontend/src/types.ts`
- Create: `frontend/src/pages/admin/adminConstants.ts`
- Create: `frontend/src/pages/admin/InputDataPanel.tsx`
- Create: `frontend/src/pages/admin/InputDataPanel.test.tsx`

**Interfaces:**
- Consumes: `/api/input-versions`, `/{id}/summary`, `/{id}/preview`, `/{id}/download`, existing upload/activate endpoints.
- Produces: `InputDataPanel({ versions, loading, onVersionsChanged, onOpenPositionDraft })`.

- [ ] **Step 1: Write a failing master-detail interaction test**

```tsx
it("shows a type-specific position explanation and current content", async () => {
  render(<InputDataPanel versions={versions} loading={false} onVersionsChanged={vi.fn()} onOpenPositionDraft={vi.fn()} />);
  fireEvent.click(screen.getByText("库位/排仓数据"));
  expect(await screen.findByText("仅用于补充待处理导出的定位信息")).toBeInTheDocument();
  expect(await screen.findByText("1 个站点")).toBeInTheDocument();
  expect(await screen.findByText("SEEKWAY:US")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "开始网页维护" })).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the focused frontend test and confirm missing component failure**

Run: `npm run test -- src/pages/admin/InputDataPanel.test.tsx`

Expected: FAIL because `InputDataPanel.tsx` does not exist.

- [ ] **Step 3: Add typed API contracts**

```ts
export interface InputVersionSummary {
  kind: string;
  row_count: number;
  columns: string[];
  metrics: Record<string, number>;
  issues: PositionIssue[];
}

export interface InputVersionPreview {
  offset: number;
  limit: number;
  total: number;
  rows: Record<string, string | number | null>[];
}
```

- [ ] **Step 4: Implement the PC master-detail component**

Use a 280px `input-data-catalog` with five buttons and a flexible `input-data-detail`. Selecting a type fetches only its active version summary and preview. Put type-specific upload inside the selected detail so the administrator never chooses the type twice. Keep historical versions for the selected type only. Use `download()` for the current file and current upload endpoint with `activate=true` by default.

- [ ] **Step 5: Run focused tests**

Run: `npm run test -- src/pages/admin/InputDataPanel.test.tsx`

Expected: tests PASS.

- [ ] **Step 6: Commit new focused frontend files when safe**

```bash
git add frontend/src/types.ts frontend/src/pages/admin/adminConstants.ts frontend/src/pages/admin/InputDataPanel.tsx frontend/src/pages/admin/InputDataPanel.test.tsx
git diff --cached --check
git commit -m "feat: add input data maintenance catalog"
```

### Task 5: Position Draft Table, Editor, Import, and Publish UI

**Files:**
- Create: `frontend/src/pages/admin/PositionMaintenance.tsx`
- Create: `frontend/src/pages/admin/PositionMaintenance.test.tsx`
- Modify: `frontend/src/types.ts`

**Interfaces:**
- Consumes: Task 3 draft APIs and `api`, `download`, Ant Design Table/Drawer/Modal/Upload.
- Produces: `PositionMaintenance({ activeVersion, onPublished, onBack })`.

- [ ] **Step 1: Write failing workflow tests**

```tsx
it("resumes a server draft and saves a row with the current revision", async () => {
  render(<PositionMaintenance activeVersion={version} onPublished={vi.fn()} onBack={vi.fn()} />);
  expect(await screen.findByText("草稿已自动保存")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "新增记录" }));
  await userEvent.type(screen.getByLabelText("店铺-站点"), "SEEKWAY:UK");
  await userEvent.type(screen.getByLabelText("积加 SKU"), "SKU-B");
  fireEvent.click(screen.getByRole("button", { name: "保存到草稿" }));
  await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/rows"), expect.objectContaining({ method: "POST" })));
});

it("blocks publish when validation returns errors", async () => {
  render(<PositionMaintenance activeVersion={version} onPublished={vi.fn()} onBack={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "发布新版本" }));
  expect(await screen.findByText("存在 1 个错误，修正后才能发布")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "确认发布" })).toBeDisabled();
});
```

- [ ] **Step 2: Run focused tests and confirm missing component failure**

Run: `npm run test -- src/pages/admin/PositionMaintenance.test.tsx`

Expected: FAIL because the component does not exist.

- [ ] **Step 3: Add draft types**

```ts
export type PositionChangeType = "unchanged" | "added" | "modified" | "deleted";
export interface PositionDraft {
  id: number;
  base_version_id: number;
  status: "editing" | "published" | "discarded";
  revision: number;
  row_count: number;
  changed_count: number;
  error_count: number;
  warning_count: number;
  updated_by: number;
  updated_at: string;
}
export interface PositionDraftRow {
  id: number;
  store_site: string;
  jiaji_sku: string;
  msku: string;
  scale_position: string;
  stocking_position: string;
  ordered_days: string;
  change_type: PositionChangeType;
}
```

- [ ] **Step 4: Implement draft entry and server-side filtering**

Create/resume on mount. Fetch rows with `query`, `site`, `scale`, `issue`, `changed`, `page`, and `page_size`. Keep server `revision` as the single write token; replace it with every successful mutation response. A 409 expires the local editor state and shows a refresh action.

- [ ] **Step 5: Implement right-side create/edit drawer and row actions**

Use vertical labels with field descriptions. `store_site` and `jiaji_sku` are required. `scale_position` offers 短尾/中尾/长尾 but accepts existing other text. Provide Save, Copy, Delete, and bulk delete. Close only after the server confirms save.

- [ ] **Step 6: Implement Excel replacement preview and publish confirmation**

Upload returns an import token plus diff/issue counts. Show the counts before applying. Publish fetches validation, disables confirmation on errors, requires warning confirmation, accepts a version name, and calls `onPublished` after success.

- [ ] **Step 7: Run focused tests**

Run: `npm run test -- src/pages/admin/PositionMaintenance.test.tsx`

Expected: tests PASS.

- [ ] **Step 8: Commit new position UI files when safe**

```bash
git add frontend/src/types.ts frontend/src/pages/admin/PositionMaintenance.tsx frontend/src/pages/admin/PositionMaintenance.test.tsx
git diff --cached --check
git commit -m "feat: add position draft maintenance workspace"
```

### Task 6: Administrator Page Integration and PC Styling

**Files:**
- Create: `frontend/src/pages/admin/UserManagementPanel.tsx`
- Create: `frontend/src/pages/admin/AuditLogPanel.tsx`
- Modify: `frontend/src/pages/AdminPage.tsx`
- Modify: `frontend/src/pages/AdminPage.test.tsx`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Consumes: Tasks 4–5 components, existing user/audit APIs, and `currentUser`.
- Produces: integrated three-section administrator page without duplicating existing user or audit behavior.

- [ ] **Step 1: Update the integration test before implementation**

```tsx
it("moves between input catalog, user accounts, and audit history", async () => {
  render(<AdminPage currentUser={admin} />);
  expect(await screen.findByText("基础资料目录")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("tab", { name: "用户账号" }));
  expect(await screen.findByText("内部账号")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("tab", { name: "操作记录" }));
  expect(await screen.findByText("最近 200 条操作记录")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the administrator test and verify it fails on the old layout**

Run: `npm run test -- src/pages/AdminPage.test.tsx`

Expected: FAIL because `基础资料目录` and `用户账号` are absent.

- [ ] **Step 3: Extract existing user and audit behavior without semantic changes**

Move create/disable/reset logic into `UserManagementPanel`; set `cancelText="取消"` and keep self-disable blocked. Move the table into `AuditLogPanel`, extend labels for draft actions, and retain the existing 200-record API scope.

- [ ] **Step 4: Compose the new administrator page**

Keep shared loading of users, versions, and audit logs at the page level. Render `InputDataPanel`, `UserManagementPanel`, and `AuditLogPanel` in tabs. Open `PositionMaintenance` inside the input area, with a clear back action rather than a new application route.

- [ ] **Step 5: Add PC-only layout styles**

```css
.input-data-layout { display: grid; grid-template-columns: 280px minmax(0, 1fr); gap: 20px; }
.input-data-catalog { position: sticky; top: 84px; align-self: start; }
.position-toolbar { display: flex; align-items: center; gap: 12px; position: sticky; top: 64px; z-index: 5; }
.position-table .ant-table-cell { white-space: nowrap; }
@media (max-width: 1279px) {
  .admin-maintenance-pc { min-width: 1100px; }
}
```

Do not add new mobile-specific administrator rules. Existing application navigation can still collapse, but this maintenance workspace is allowed to scroll horizontally below 1280px.

- [ ] **Step 6: Run all frontend tests and build**

Run: `npm run test`

Expected: all frontend tests PASS.

Run: `npm run build`

Expected: TypeScript and Vite build PASS; the existing bundle-size warning may remain.

- [ ] **Step 7: Commit integration only after inspecting overlapping dirty files**

```bash
git add frontend/src/pages/admin/UserManagementPanel.tsx frontend/src/pages/admin/AuditLogPanel.tsx frontend/src/pages/AdminPage.tsx frontend/src/pages/AdminPage.test.tsx frontend/src/styles.css
git diff --cached --name-only
git diff --cached --check
git commit -m "feat: redesign administrator maintenance workspace"
```

If `AdminPage.tsx` or `styles.css` contains inseparable earlier work, defer the checkpoint rather than committing unrelated changes.

### Task 7: Regression, Docker, and PC Visual Acceptance

**Files:**
- Modify: `README.md`
- Modify: `HANDOFF_WEB_UPGRADE.md`
- Modify: `UI_UX_OPTIMIZATION_PLAN.md`
- Create: `design/admin-maintenance-qa/` screenshots and evidence JSON

**Interfaces:**
- Consumes: all previous tasks.
- Produces: verified local and deployed feature plus accurate handoff notes.

- [ ] **Step 1: Run complete code verification**

Run: `.venv/bin/python -m unittest discover -s tests -v`

Expected: all tests PASS with the new total reported.

Run: `.venv/bin/python -m pip check`

Expected: `No broken requirements found.`

Run: `npm run test` from `frontend/`

Expected: all Vitest files and tests PASS.

Run: `npm run build` from `frontend/`

Expected: production build PASS.

- [ ] **Step 2: Run deployment configuration verification**

Run: `docker compose config --quiet`

Expected: exit 0 with no output.

Run: `docker compose up -d --build`

Expected: db remains healthy; api, worker, and web are rebuilt and running.

Run: `docker compose ps`

Expected: db and api healthy; worker and web running.

- [ ] **Step 3: Run live API acceptance without exposing credentials**

Log in from environment variables, then verify summary, preview, draft creation, one mutation, validation, discard on a disposable draft only when it cannot affect an existing human draft. Prefer the test database for destructive draft flows. Verify public `/health` and the new frontend asset hashes.

- [ ] **Step 4: Capture fresh Chrome evidence at PC viewports**

Capture and inspect these states at 1440×900 and the main state at 1920×1080:

1. Base-data catalog with position selected.
2. Current position content and summary.
3. Server draft table and filters.
4. Create/edit drawer.
5. Excel diff confirmation.
6. Publish validation with an error.
7. Publish confirmation with warnings only.
8. Users and audit panels.

Reject screenshots with loading states, clipped primary actions, horizontal page overflow at target widths, or English modal actions.

- [ ] **Step 5: Update documentation with actual evidence only**

Document the new workflow, test totals, deployment result, and remaining operations limits. Do not mark backup/restore or production readiness complete unless separately verified.

- [ ] **Step 6: Final diff and safety review**

Run: `git diff --check`

Expected: no whitespace errors.

Run: `git status -sb`

Expected: only intentional source, test, documentation, and QA evidence changes; no `.env`, Excel, database, logs, uploads, or exported business files.
