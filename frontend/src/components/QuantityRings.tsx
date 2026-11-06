import { useId } from "react";
import { Tooltip } from "antd";

type RingMetric = { label: string; value?: number | null; total?: number | null };
type QuantityRingsProps = {
  outer: RingMetric;
  inner?: RingMetric;
  small?: boolean;
  description?: string;
};

const detailGeometry = { center: 66, dimension: 112, viewBox: "0 0 132 132", radius: 54, width: 13 };
const smallGeometry = { center: 14, dimension: 28, viewBox: "0 0 28 28", radius: 10, width: 5 };

function ratio(metric: RingMetric) {
  return metric.total ? Math.max(0, Math.min(1, (metric.value ?? 0) / metric.total)) : 0;
}

function metricLabel(metric: RingMetric, unit: string) {
  const value = metric.value?.toLocaleString("zh-CN") ?? "—";
  const total = metric.total?.toLocaleString("zh-CN") ?? "—";
  const percent = metric.value == null || metric.total == null ? "—" : `${(ratio(metric) * 100).toFixed(1)}%`;
  return `${metric.label} ${value} / ${total} ${unit}，占比 ${percent}`;
}

export default function QuantityRings({ outer, inner, small = false, description }: QuantityRingsProps) {
  const id = useId();
  const outerId = `${id}-outer`;
  const innerId = `${id}-inner`;
  const innerMetric = small ? undefined : inner;
  const label = [metricLabel(outer, "件"), innerMetric && metricLabel(innerMetric, "条"), description]
    .filter(Boolean)
    .join("；");
  const { center, dimension, viewBox, radius, width } = small ? smallGeometry : detailGeometry;
  return (
    <Tooltip title={label} trigger={["hover", "focus"]}>
      <svg
        className="quantity-rings"
        width={dimension}
        height={dimension}
        viewBox={viewBox}
        role="img"
        aria-label={label}
        tabIndex={0}
      >
        {!small && (
          <defs>
            <linearGradient id={outerId} x1="0" y1="0" x2="1" y2="1">
              <stop stopColor="#2fa386" />
              <stop offset="1" stopColor="#16775f" />
            </linearGradient>
            <linearGradient id={innerId} x1="0" y1="0" x2="1" y2="1">
              <stop stopColor="#f08a6c" />
              <stop offset="1" stopColor="#d9532f" />
            </linearGradient>
          </defs>
        )}
        <g transform={`rotate(-90 ${center} ${center})`} fill="none">
          <RingArc
            center={center}
            radius={radius}
            width={width}
            share={ratio(outer)}
            track="#e3f0ec"
            fill={small ? "#1f8a72" : `url(#${outerId})`}
          />
          {innerMetric && (
            <RingArc
              center={center}
              radius={37}
              width={13}
              share={ratio(innerMetric)}
              track="#fbe7e1"
              fill={`url(#${innerId})`}
            />
          )}
        </g>
        {small && ratio(outer) === 1 && (
          <path
            aria-label={`全部${outer.label}`}
            d="M9.5 14.5l3 3 6-6.5"
            fill="none"
            stroke="#1f8a72"
            strokeWidth="2.2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        )}
      </svg>
    </Tooltip>
  );
}

function RingArc({
  center,
  radius,
  width,
  share,
  track,
  fill
}: {
  center: number;
  radius: number;
  width: number;
  share: number;
  track: string;
  fill: string;
}) {
  const circumference = 2 * Math.PI * radius;
  const visibleLength = circumference * share;
  const strokeWidth = Math.min(width, visibleLength / 2);
  return (
    <>
      <circle cx={center} cy={center} r={radius} stroke={track} strokeWidth={width} />
      {share > 0 && (
        <circle
          cx={center}
          cy={center}
          r={radius}
          stroke={fill}
          strokeWidth={share === 1 ? width : strokeWidth}
          strokeLinecap="round"
          strokeDasharray={share === 1 ? undefined : `${visibleLength - strokeWidth} ${circumference}`}
        />
      )}
    </>
  );
}
