import { Button, Input, Popover, Select } from "antd";
import { SearchOutlined } from "@ant-design/icons";
import type { ExceptionReview } from "./useExceptionReview";

function filterOptions(values: string[]) {
  return Array.from(new Set(values.filter(Boolean)))
    .sort((left, right) => left.localeCompare(right, "zh-CN"))
    .map((value) => ({ value, label: value }));
}

export default function ExceptionReviewToolbar({
  selfOperated,
  review,
  onReset
}: {
  selfOperated: boolean;
  review: ExceptionReview;
  onReset: () => void;
}) {
  const {
    reviewStats,
    reviewScope,
    query,
    siteFilter,
    scaleFilter,
    stockingFilter,
    reasonFilter,
    changeScope,
    changeQuery,
    changeFilter,
    exceptionFilters
  } = review;
  const reasonOptions = filterOptions(exceptionFilters.reasons);
  const siteOptions = filterOptions(exceptionFilters.sites);
  const scaleOptions = filterOptions(exceptionFilters.scales);
  const stockingOptions = filterOptions(exceptionFilters.stocking);
  const moreFilterCount = [scaleFilter, stockingFilter].filter(Boolean).length;
  const positionFilters = (
    <div className="exception-more-filters">
      {(
        [
          ["scale", "规模定位", scaleOptions, scaleFilter],
          ["stocking", "备货定位", stockingOptions, stockingFilter]
        ] as const
      ).map(([field, label, options, value]) => (
        <Select
          key={field}
          aria-label={`${label}筛选`}
          allowClear
          showSearch
          optionFilterProp="label"
          placeholder={`全部${label}`}
          options={options}
          value={value}
          onChange={(nextValue) => {
            changeFilter(field, nextValue);
            onReset();
          }}
        />
      ))}
    </div>
  );
  return (
    <div className="table-toolbar exception-toolbar">
      {selfOperated && reviewScope !== "resolved" && (
        <Select
          aria-label="处理范围"
          value={reviewScope}
          options={[
            { value: "unfinished", label: "未完成" },
            { value: "all", label: "全部待处理" }
          ]}
          onChange={(scope) => {
            changeScope(scope);
            onReset();
          }}
        />
      )}
      {!selfOperated && (
        <section className="review-scope-switch" aria-label="审校概览">
          {(
            [
              ["unfinished", "待审校", reviewStats.unfinishedCount],
              ["resolved", "已处理", reviewStats.resolvedCount],
              ["all", "全部", reviewStats.totalCount]
            ] as const
          ).map(([scope, label, count]) => (
            <button
              key={scope}
              type="button"
              aria-pressed={reviewScope === scope}
              onClick={() => {
                changeScope(scope);
                onReset();
              }}
            >
              {label} <strong>{count}</strong>
            </button>
          ))}
        </section>
      )}
      <div className="exception-filter-field exception-search-field">
        <Input
          id="exception-search"
          aria-label="搜索待处理记录"
          allowClear
          prefix={<SearchOutlined />}
          placeholder={selfOperated ? "搜索来源、SKU、站点或入库仓" : "搜索来源、SKU、站点或目的仓"}
          value={query}
          onChange={(event) => {
            changeQuery(event.target.value);
            onReset();
          }}
        />
      </div>
      <div className="exception-filter-field">
        <Select
          id="exception-reason-filter"
          aria-label="原因筛选"
          allowClear
          placeholder="全部原因"
          options={reasonOptions}
          value={reasonFilter}
          onChange={(value) => {
            changeFilter("reason", value);
            onReset();
          }}
        />
      </div>
      <div className="exception-filter-field">
        <Select
          id="exception-site-filter"
          aria-label="站点筛选"
          allowClear
          showSearch
          optionFilterProp="label"
          placeholder="全部站点"
          options={siteOptions}
          value={siteFilter}
          onChange={(value) => {
            changeFilter("site", value);
            onReset();
          }}
        />
      </div>
      {!selfOperated && (
        <Popover trigger="click" placement="bottomRight" content={positionFilters}>
          <Button>更多筛选{moreFilterCount ? ` ${moreFilterCount}` : ""}</Button>
        </Popover>
      )}
    </div>
  );
}
