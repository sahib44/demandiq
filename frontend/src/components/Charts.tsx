import {
  Area,
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { date, methodName, number } from './format';
import type { Metric, NumericRow } from '../types/api';

export function DemandChart({
  rows,
  interval = false,
  comparison = false,
  predictionLabel = 'Selected forecast',
}: {
  rows: NumericRow[];
  interval?: boolean;
  comparison?: boolean;
  predictionLabel?: string;
}) {
  const data = rows.map((row) => ({
    ...row,
    interval: row.lower == null ? undefined : [row.lower, row.upper],
  }));
  return (
    <div
      className="chart demand-chart"
      role="img"
      aria-label={`Weekly actual demand and ${predictionLabel.toLowerCase()}; numerical values are available in the adjacent data table.`}
    >
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 16, right: 18, bottom: 0, left: 2 }}>
          <CartesianGrid stroke="#e7ece9" vertical={false} />
          <XAxis
            dataKey="week"
            tickFormatter={(value: string) => date(value, true)}
            tickLine={false}
            axisLine={false}
            minTickGap={32}
            tick={{ fill: '#6b777a', fontSize: 11 }}
          />
          <YAxis
            tickFormatter={(value: number) => number(value)}
            tickLine={false}
            axisLine={false}
            width={52}
            tick={{ fill: '#6b777a', fontSize: 11 }}
          />
          <Tooltip
            labelFormatter={(value) => date(String(value), true)}
            contentStyle={{ borderRadius: 8, border: '1px solid #dce3df', fontSize: 12 }}
            formatter={(value, name) => [
              Array.isArray(value)
                ? value.map((item) => number(Number(item))).join(' – ')
                : number(Number(value)),
              String(name),
            ]}
          />
          {interval && (
            <Area
              isAnimationActive={false}
              type="monotone"
              dataKey="interval"
              name="Empirical interval"
              stroke="none"
              fill="#d9ebe5"
              connectNulls={false}
            />
          )}
          <Line
            isAnimationActive={false}
            type="monotone"
            dataKey="actual"
            name="Actual demand"
            stroke="#263f4a"
            strokeWidth={2}
            dot={false}
            connectNulls={false}
          />
          <Line
            isAnimationActive={false}
            type="monotone"
            dataKey="prediction"
            name={predictionLabel}
            stroke="#188275"
            strokeWidth={2.5}
            dot={{ r: 3, strokeWidth: 0, fill: '#188275' }}
            connectNulls={false}
          />
          {comparison && (
            <Line
              isAnimationActive={false}
              type="monotone"
              dataKey="baseline"
              name="Four-week mean"
              stroke="#967137"
              strokeWidth={1.5}
              strokeDasharray="5 4"
              dot={false}
            />
          )}
          <Legend
            iconType="plainline"
            wrapperStyle={{ fontSize: 12, paddingTop: 16 }}
            formatter={(value) => <span style={{ color: '#435e54' }}>{value}</span>}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
export function MetricChart({
  rows,
  metric = 'wape',
}: {
  rows: Metric[];
  metric?: 'wape' | 'mae' | 'rmse';
}) {
  const data = rows.map((row) => ({ name: methodName(row.model), value: row[metric] }));
  return (
    <div
      className="chart metric-chart"
      role="img"
      aria-label={`Comparison of ${metric.toUpperCase()} by forecasting method; exact values are in the performance table.`}
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ top: 0, right: 28, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="#e7ece9" horizontal={false} />
          <XAxis
            type="number"
            axisLine={false}
            tickLine={false}
            tick={{ fill: '#6b777a', fontSize: 11 }}
          />
          <YAxis
            dataKey="name"
            type="category"
            axisLine={false}
            tickLine={false}
            width={145}
            tick={{ fill: '#3e5359', fontSize: 11 }}
          />
          <Tooltip
            cursor={{ fill: '#f3f6f3' }}
            formatter={(value) => [number(Number(value), 2), metric.toUpperCase()]}
          />
          <Bar
            isAnimationActive={false}
            dataKey="value"
            fill="#228578"
            radius={[0, 4, 4, 0]}
            barSize={16}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
export function CostChart({
  rows,
  currency,
}: {
  rows: { name: string; value: number }[];
  currency: string;
}) {
  return (
    <div
      className="chart cost-chart"
      role="img"
      aria-label={`Simulated ${currency} net inventory cost by policy; exact values are in the comparison table.`}
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} margin={{ top: 20, left: 5, right: 12, bottom: 25 }}>
          <CartesianGrid vertical={false} stroke="#e7ece9" />
          <XAxis
            dataKey="name"
            axisLine={false}
            tickLine={false}
            tick={{ fill: '#6b777a', fontSize: 10 }}
            interval={0}
            angle={-12}
            textAnchor="end"
          />
          <YAxis
            axisLine={false}
            tickLine={false}
            tickFormatter={(v: number) => `${number(v / 1000)}k`}
            tick={{ fill: '#6b777a', fontSize: 11 }}
            width={45}
          />
          <Tooltip
            formatter={(value) => [`${currency} ${number(Number(value), 2)}`, 'Simulated net cost']}
            cursor={{ fill: '#f3f6f3' }}
          />
          <Bar
            isAnimationActive={false}
            dataKey="value"
            fill="#228578"
            radius={[4, 4, 0, 0]}
            maxBarSize={48}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
