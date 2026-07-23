# Batch Workbench Design QA

## Comparison Target

- Source visual truth: `/root/.codex/generated_images/019f8893-842e-7d70-8b17-e99b0f6936e0/exec-e4ae502c-2321-49c6-8991-4963d6c0ab89.png`
- Source pixels: `1487 x 1058`
- Intended source viewport: `1440 x 1024`
- Implementation screenshot: `/tmp/deliverynote-batch-workbench-design-qa-20260722/02-workbench-top-1440x1024.png`
- Focused review screenshot: `/tmp/deliverynote-batch-workbench-design-qa-20260722/03-workbench-review-1440x1024.png`
- Full-view comparison: `/tmp/deliverynote-batch-workbench-design-qa-20260722/source-vs-implementation-final.png`
- Implementation CSS viewport: `1440 x 1024`
- Device scale factor: `1`
- Density normalization: the source was rendered at `1440 x 1024` beside the native `1440 x 1024` implementation capture. The source and target aspect ratios differ by less than 0.1%.
- State: operator viewing computed batch `QA 短尾规则 160`, with `160` delivered, `150` importable, and `10` pending under locked rule `QA V1 短尾 50`.

## Findings

- No actionable P0, P1, or P2 differences remain.
- [P3] The real Ant Design controls and production text metrics make the pending-review table begin slightly lower than in the generated mock at the same viewport. The review heading, all six labeled filters, and the table header remain visible above the fold; the primary action scrolls directly to the complete table.

## Required Fidelity Surfaces

- Fonts and typography: implementation retains the product font stack `Inter, Microsoft YaHei, sans-serif`; title, stage heading, metrics, helper text, and table hierarchy match the selected direction. Dynamic file names use controlled ellipsis with the full value available from the table cell title.
- Spacing and layout rhythm: focused batch detail removes the global sidebar, aligns the page margins and full-width workbench to the source, and matches its compact sequence of title, steps, action guidance, metrics, files, locked data, and review table. Section gaps remain consistently `18px`.
- Colors and visual tokens: existing `#176b5b` primary green, pale green guidance surface, neutral gray workspace, semantic pending amber, light borders, and restrained shadows match the selected visual direction and the established product tokens.
- Image quality and asset fidelity: the target contains no raster imagery. All visible icons use the existing Ant Design icon library; no placeholder imagery, custom SVG, emoji, or CSS-drawn substitute was introduced.
- Copy and content: the current stage is `异常审校`, the main action is `拆分审校（10）`, export remains explicitly secondary, and the quantity equation remains `160 = 150 + 10`. Locked versions and the immutable overreceipt rule remain visible.
- Accessibility: all six review filters have visible labels and accessible names. Chrome's accessibility tree reported no unnamed button, link, textbox, combobox, checkbox, or switch in the tested state. This is targeted evidence, not a claim of full accessibility conformance.
- Responsiveness: existing breakpoints were preserved and extended for the guidance and filter grids. The verified desktop viewport has zero document horizontal overflow and zero review-table horizontal overflow.

## Primary Interactions Tested

- Opened the synthetic QA batch from the batch list.
- Activated `拆分审校（10）`; the page scrolled and focus moved to the review section (`scrollY 396`).
- Opened the reason filter, selected `超出允许超收量`, and confirmed one matching row.
- Opened the `拆分审校 · SKU-A` drawer, verified its source/position/conservation fields and save control, then closed it without saving.
- Did not generate an export, save a split, delete data, or mutate a batch.
- Browser console errors: `0`.

## Comparison History

### Pass 1

- Earlier P2 finding: the persistent sidebar narrowed the batch workbench and pushed the pending-review table too far below the source composition.
- Earlier P2 finding: the steps, metrics, and source-file card were vertically looser than the selected mock.
- Fixes: added a batch-detail focus layout without the global sidebar; placed the account controls as a lightweight overlay; tightened workflow, guidance, metrics, file-table, and locked-data spacing; retained the established design tokens.
- Post-fix evidence: `/tmp/deliverynote-batch-workbench-design-qa-20260722/source-vs-implementation-final.png` and `/tmp/deliverynote-batch-workbench-design-qa-20260722/03-workbench-review-1440x1024.png`.

### Pass 2

- The full-view comparison and focused review capture show no remaining P0/P1/P2 mismatches.
- All critical review headers are within the viewport: `来源文件`, `SKU`, `站点`, `目的仓`, `规模定位`, `待处理量`, `原因`, `状态`, `操作`.
- Final production assets verified in QA: `index-C86k-3FA.js` and `index-C1RqHEqO.css`.

## Follow-up Polish

- Optional P3: if operators prefer even more review-table content above the fold, the locked-data card could become a disclosure row in a later iteration. It is intentionally left expanded here so batch version and rule provenance remain immediately visible.

Batch workbench result: passed

# Batch List and Overreceipt UI Design QA

## Comparison Target

- Source visual truth: `/tmp/deliverynote-other-ui-audit-20260722/01-batch-list-desktop.png`, `/tmp/deliverynote-other-ui-audit-20260722/02-overreceipt-rules-top.png`, and `/tmp/deliverynote-other-ui-audit-20260722/07-batch-list-mobile.png`.
- Implementation screenshots: `/tmp/deliverynote-other-ui-implementation-20260722/01-batch-list-desktop.png`, `/tmp/deliverynote-other-ui-implementation-20260722/02-overreceipt-rules-top.png`, `/tmp/deliverynote-other-ui-implementation-20260722/07-batch-list-mobile.png`, `/tmp/deliverynote-other-ui-implementation-20260722/08-batch-cards-mobile.png`, `/tmp/deliverynote-other-ui-implementation-20260722/09-overreceipt-rules-mobile.png`, and `/tmp/deliverynote-other-ui-implementation-20260722/10-overreceipt-history-mobile.png`.
- CSS viewports: desktop `1440 x 1000`; mobile `390 x 844`.
- Device scale factor: native `1x` for both source and implementation captures; no density normalization was required.
- State: admin user in the isolated QA stack, with two synthetic batches, two immutable overreceipt rule versions, and one active warehouse whitelist.

## Findings

- No actionable P0, P1, or P2 differences remain.
- [P3] The desktop overreceipt history table reports `671px` scroll width inside a `669px` client width because of Ant Design table-border rounding. All five columns and the action remain visible, the page has no horizontal overflow, and no user content is hidden.

## Required Fidelity Surfaces

- Fonts and typography: the product font stack remains `Inter, Microsoft YaHei, sans-serif`; the established heading, label, helper-text, and table hierarchy is unchanged.
- Spacing and layout rhythm: the batch list uses labeled compact filters and a bordered desktop table; mobile batches become readable stacked cards. The overreceipt publish and history surfaces use the same compact card rhythm as the rest of the product.
- Colors and visual tokens: the existing green/neutral palette, semantic status colors, borders, radii, and shadows are reused without introducing a parallel visual language.
- Image quality and asset fidelity: these screens contain no raster image assets. Existing Ant Design icons remain in use; no custom SVG, placeholder, emoji, or CSS-drawn asset was added.
- Copy and content: business meaning is unchanged. Added copy is limited to visible filter labels, quantity units, accessible names, result count, and the explicit `未开放任何仓库` empty state.
- Accessibility: both tables have accessible names; filters have visible labels; row actions have record-specific labels. Chrome's accessibility tree reported `0` unnamed buttons, links, text boxes, comboboxes, checkboxes, or switches in the tested states.
- Responsiveness: document horizontal overflow is `0px` at both viewports. Batch tables measured `1146/1146px` on desktop and `308/308px` on mobile; the rule table measured `274/274px` on mobile.

## Primary Interactions Tested

- Searched the batch list for `无超收` and confirmed exactly one matching row, then restored the full result set.
- Opened the new-batch modal and closed it with `取消`; no batch was created.
- Navigated among batch list, overreceipt rules, base-data maintenance, user maintenance, and audit records.
- Confirmed workspace navigation resets retained page scroll and lands the destination screen at its top.
- Browser write requests: `0`; failed responses: `0`; console errors: `0`.

## Comparison History

### Pass 1

- P2: the mobile sidebar and vertically stacked readiness list consumed the first screen, leaving the actual batch list below the fold.
- P2: the desktop overreceipt history action column was clipped by the fixed-width table.
- P2: switching workspaces retained the previous scroll offset and could land the user in the middle of the overreceipt form.
- Fixes: reduced the mobile sidebar, condensed readiness into a two-column grid, converted mobile rows to complete labeled cards, removed the forced history-table width, compacted rule metadata, and reset workspace scroll on navigation.

### Pass 2

- The first real batch card is now visible above the fold on mobile, with all row data and the `打开` action preserved.
- Every immutable-rule column and action is visible on desktop; mobile history cards preserve the same information without horizontal scrolling.
- Mobile overreceipt navigation now starts at the page heading and active-rule summary.
- Final browser evidence: `10` screenshots, `0` unnamed interactive controls, `0` write requests, `0` failed responses, and `0` console errors.

final result: passed

# Base Data Workspace Design QA

## Comparison Target

- Source visual truth: `/root/.codex/generated_images/019f8893-842e-7d70-8b17-e99b0f6936e0/exec-874ba06f-dbee-44e2-8dd0-846ac9cfb70c.png`.
- Source pixels: `1487 x 1058`.
- Implementation screenshot: `/tmp/deliverynote-base-data-ui-qa-20260723/01-position-ready-workspace-1487x1058.png`.
- Upload-drawer screenshot: `/tmp/deliverynote-base-data-ui-qa-20260723/04-purchase-upload-drawer.png`.
- Same-size comparison input: `/tmp/deliverynote-base-data-ui-qa-20260723/06-reference-vs-implementation.png` (source first, implementation second).
- CSS viewport: `1487 x 1058`; device scale factor: `1`.
- Density normalization: none. Both source and implementation were reviewed at native `1487 x 1058` pixels.
- State: admin user in the isolated QA stack, viewing the only active QA input (`库位/排仓数据`) in its ready-state preview. The source uses active purchase data; the selected-version, preview-tab, expanded-context, and table states are equivalent, while the record labels and readiness count reflect real QA data.

## Findings

- No actionable P0, P1, or P2 visual differences remain.
- [P3] The real product retains its administrator page title and top-level tabs, whereas the generated source collapses that context into a breadcrumb. This intentionally preserves established navigation and makes the implementation begin lower; the compacted base-data workspace still shows the complete first preview row above the fold.

## Required Fidelity Surfaces

- Fonts and typography: the existing `Inter, Microsoft YaHei, sans-serif` stack and established heading, label, helper-text, metric, and table hierarchy remain unchanged.
- Spacing and layout rhythm: the five data types form one equal-width horizontal rail; the selected version, size, creator, time, and actions share one compact header; required fields and business impact share one disclosure band; the full-width tab workspace follows without a permanent side catalog.
- Colors and visual tokens: the existing `#176b5b` green, neutral workspace gray, pale ready-state tint, warning amber, borders, and restrained radii are reused. No parallel theme was introduced.
- Image quality and asset fidelity: the screen contains no raster content. Visible controls use the existing Ant Design icon library; no placeholder image, emoji, handwritten SVG, or CSS-drawn icon was introduced.
- Copy and content: the five source-data purposes, required fields, version-lock impact, active/inactive states, filenames, creator metadata, and position-maintenance action retain their business meaning.
- Accessibility: each data-type card has a stateful accessible name; tabs, preview/history tables, status region, drawer fields, and action buttons remain named. Chrome's accessibility tree reported `0` unnamed buttons, links, text boxes, comboboxes, checkboxes, or switches in the tested state.
- Desktop behavior: the verified `1487 x 1058` viewport has no positive document horizontal overflow. Mobile behavior was not redesigned or claimed, per user direction.

## Primary Interactions Tested

- Selected all five data types and confirmed title, active card, preview-tab reset, open context band, and zero positive document overflow after every switch.
- Collapsed and reopened the required-fields/business-impact disclosure.
- Switched among data preview, version history, and quality check; the active QA position version exposed `38` version rows with `8` visible on the current page.
- Opened and closed the first-version upload drawer for purchase data without choosing a file or submitting.
- Entered the position web-maintenance route, verified the `库位草稿记录` table, and returned to base data. The only browser write was the expected QA draft initialization `POST /api/input-drafts/position`; no version was published.
- Browser evidence: `0` failed responses, `0` console errors, and `0` unnamed interactive controls.

## Comparison History

### Pass 1

- P2: the rail retained an extra container and version-name row, making the five choices taller than the selected source.
- P2: the expanded context duplicated a summary row above required fields and business impact.
- P2: four position metric cards repeated information already present in the active-version header and pushed the preview table below the fold.
- Fixes: flattened and shortened the data-type rail, hid redundant version names from cards, tightened the status header, combined open context content into one band, and moved position metrics into the preview summary.
- Browser functionality passed before visual compaction; the first pass used QA assets `index-BV5TQoTl.js` and `index-Bl_vswW6.css`.

### Pass 2

- The same-size comparison shows the intended information hierarchy and a complete first preview row above the fold.
- Final isolated QA assets: `index-DAoqjyPZ.js` and `index-7i915fyY.css`.
- Focused component tests: `14/14` passed. Full frontend suite: `64/64` passed. Frontend production build passed with only the existing chunk-size advisory.

Base data workspace result: passed

# Top-right Account Controls Design QA

## Comparison Target

- Selected visual source: `/root/.codex/generated_images/019f8893-842e-7d70-8b17-e99b0f6936e0/call_IyLFlkKPhRNwDTD2z4WpkArO.png`.
- Source pixels: `1487 x 1058`.
- Implementation screenshot: `/tmp/deliverynote-topbar-ui-qa-20260723/01-admin-workspace-account-controls-1487x1058.png`.
- Focused and full-state comparison input: `/tmp/deliverynote-topbar-ui-qa-20260723/02-selected-vs-implementation.png`.
- CSS viewport: `1487 x 1058`; device scale factor: `1`.
- Density normalization: none. Source and implementation were compared at the same native pixel dimensions.
- State: admin user in the isolated QA stack, viewing the administrator base-data workspace. The selected source contains active position data while QA contains its current real readiness state; the review scope is the unchanged header and the top-right account controls.

## Findings

- No actionable P0, P1, or P2 differences remain in the targeted top-right surface.
- [P3] The real QA page has a browser scrollbar because its current base-data content exceeds the viewport; the generated source does not depict one. The account controls remain aligned to the content edge with the established `28px` header inset.

## Required Fidelity Surfaces

- Structure: the previous flat `admin · 管理员` string is now a bounded identity surface with a separate outlined logout action. No dropdown, menu, profile page, or new permission behavior was introduced.
- Typography: the username and role use two lines with restrained `14px`/`11px` hierarchy. The final username weight was reduced after comparison so it no longer appears heavier than the selected visual.
- Spacing and geometry: the identity surface is `126 x 48px`, avatar `34 x 34px`, logout action `94 x 40px`, and the two surfaces use the selected separated-cluster rhythm.
- Colors and visual tokens: the existing `#176b5b` primary green, white surfaces, neutral borders, `8px` radius, and product typography stack are reused.
- Asset fidelity: the avatar is the real user initial and the logout action uses the existing Ant Design `LogoutOutlined` icon. No custom SVG, emoji, placeholder, or CSS-drawn icon was added.
- Accessibility: the cluster is named `当前用户`; the logout button is named `退出登录`; Chrome confirmed a visible `3px solid` focus outline and reported `0` unnamed interactive controls in the tested page.
- Desktop behavior: the verified page had no positive horizontal overflow. Mobile was not redesigned or claimed, per user direction.

## Primary Interactions Tested

- Loaded the QA workspace as the real admin account and navigated to administrator maintenance.
- Verified avatar `A`, username `admin`, role `管理员`, visible label `退出`, and accessible name `退出登录`.
- Moved focus to logout and confirmed the existing visible focus treatment.
- Activated logout in Chrome, confirmed `POST /api/auth/logout`, verified both stored token and user were cleared, and observed the login form.
- Re-authenticated and left the verified administrator preview open.
- Browser evidence: `0` failed responses, `0` console errors, and `0` unnamed interactive controls.

## Comparison History

### Pass 1

- P2: the inherited header line height placed the avatar initial against the bottom of its square instead of centering it.
- P2: the logout action was visibly tighter than the selected visual and made the two-part account cluster feel unbalanced.
- Fixes: set an explicit avatar line height, widened the logout surface, and tuned the separation between identity and action.

### Pass 2

- P2: the username remained heavier than the selected visual in the same-image focused comparison.
- Fix: reduced username weight while preserving clear hierarchy over the role label.
- Final isolated QA assets: `index-CvZ_LMth.js` and `index-BiMsXO3P.css`.
- Account regression tests: `5/5` passed. Full frontend suite: `65/65` passed. Production build and Docker Compose configuration checks passed; the build retains only the existing chunk-size advisory.

final result: passed
