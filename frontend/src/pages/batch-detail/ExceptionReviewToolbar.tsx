import { Input, Select } from "antd";
import { SearchOutlined } from "@ant-design/icons";
import type { ExceptionReview } from "../useExceptionReview";

function filterOptions(values: string[]) {
  return Array.from(new Set(values.filter(Boolean)))
    .sort((left, right) => left.localeCompare(right, "zh-CN"))
    .map((value) => ({ value, label: value }));
}

export default function ExceptionReviewToolbar({ review, onReset }: { review: ExceptionReview; onReset: () => void }) {
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
  return (
    <>
      <section className="review-overview" aria-label="审校概览">
        <div className="review-overview-copy">
          <strong>审校进度</strong>
          <span>默认优先显示未完成记录，保存后可连续处理下一条。</span>
        </div>
        <div className="review-scope-options">
          <button
            type="button"
            className="review-scope-card"
            aria-label={`未完成 ${reviewStats.unfinishedCount} 条，待处理 ${reviewStats.unfinishedQuantity} 件`}
            aria-pressed={reviewScope === "unfinished"}
            onClick={() => {
              changeScope("unfinished");
              onReset();
            }}
          >
            <span>未完成</span>
            <strong>{reviewStats.unfinishedCount} 条</strong>
            <small>待处理 {reviewStats.unfinishedQuantity} 件</small>
          </button>
          <button
            type="button"
            className="review-scope-card"
            aria-label={`已处理 ${reviewStats.resolvedCount} 条`}
            aria-pressed={reviewScope === "resolved"}
            onClick={() => {
              changeScope("resolved");
              onReset();
            }}
          >
            <span>已处理</span>
            <strong>{reviewStats.resolvedCount} 条</strong>
            <small>查看已完成记录</small>
          </button>
          <button
            type="button"
            className="review-scope-card"
            aria-label={`全部 ${reviewStats.totalCount} 条`}
            aria-pressed={reviewScope === "all"}
            onClick={() => {
              changeScope("all");
              onReset();
            }}
          >
            <span>全部</span>
            <strong>{reviewStats.totalCount} 条</strong>
            <small>查看完整审校队列</small>
          </button>
        </div>
      </section>
      <div className="table-toolbar exception-toolbar">
        <div className="exception-filter-field exception-search-field">
          <label htmlFor="exception-search">搜索</label>
          <Input
            id="exception-search"
            aria-label="搜索待处理记录"
            allowClear
            prefix={<SearchOutlined />}
            placeholder="搜索来源、SKU、站点或目的仓"
            value={query}
            onChange={(event) => {
              changeQuery(event.target.value);
              onReset();
            }}
          />
        </div>
        <div className="exception-filter-field">
          <label htmlFor="exception-site-filter">站点</label>
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
        <div className="exception-filter-field">
          <label htmlFor="exception-scale-filter">规模定位</label>
          <Select
            id="exception-scale-filter"
            aria-label="规模定位筛选"
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder="全部规模定位"
            options={scaleOptions}
            value={scaleFilter}
            onChange={(value) => {
              changeFilter("scale", value);
              onReset();
            }}
          />
        </div>
        <div className="exception-filter-field">
          <label htmlFor="exception-stocking-filter">备货定位</label>
          <Select
            id="exception-stocking-filter"
            aria-label="备货定位筛选"
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder="全部备货定位"
            options={stockingOptions}
            value={stockingFilter}
            onChange={(value) => {
              changeFilter("stocking", value);
              onReset();
            }}
          />
        </div>
        <div className="exception-filter-field">
          <label htmlFor="exception-reason-filter">原因</label>
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
      </div>
    </>
  );
}
