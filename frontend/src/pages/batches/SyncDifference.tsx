export default function SyncDifference({
  diff,
  changeLabel,
  totalLabel
}: {
  diff: Record<string, number>;
  changeLabel: string;
  totalLabel: string;
}) {
  const metrics = [
    ["added_lines", "新增匹配项"],
    ["changed_lines", changeLabel],
    ["removed_lines", "移除匹配项"],
    ["after_quantity", totalLabel]
  ];
  return (
    <dl className="purchase-sync-diff">
      {metrics.map(([field, label]) => (
        <div key={field}>
          <dt>{label}</dt>
          <dd>{diff[field] ?? 0}</dd>
        </div>
      ))}
    </dl>
  );
}
