import { useEffect, useState } from "react";
import { Input, Select } from "./ui";

const UNITS = [
  { value: 1, label: "minuta" },
  { value: 60, label: "sati" },
  { value: 1440, label: "dana" },
];

function bestUnit(minutes: number) {
  if (minutes % 1440 === 0) return 1440;
  if (minutes % 60 === 0) return 60;
  return 1;
}

/** Unos intervala u minutima, satima ili danima; vrednost se uvek predaje u minutima. */
export default function IntervalInput({ value, onChange, disabled }: { value: number; onChange: (minutes: number) => void; disabled?: boolean }) {
  const [unit, setUnit] = useState(() => bestUnit(value));
  const [amount, setAmount] = useState(() => String(value / bestUnit(value)));

  useEffect(() => {
    const u = bestUnit(value);
    setUnit(u);
    setAmount(String(value / u));
  }, [value]);

  const emit = (rawAmount: string, nextUnit: number) => {
    const n = Number(rawAmount);
    if (Number.isFinite(n) && n > 0) onChange(Math.round(n * nextUnit));
  };

  return (
    <div className="flex gap-2">
      <Input
        type="number"
        min={1}
        step={1}
        className="w-28"
        value={amount}
        disabled={disabled}
        onChange={(e) => {
          setAmount(e.target.value);
          emit(e.target.value, unit);
        }}
      />
      <Select
        className="w-32"
        value={unit}
        disabled={disabled}
        onChange={(e) => {
          const next = Number(e.target.value);
          setUnit(next);
          emit(amount, next);
        }}
      >
        {UNITS.map((u) => (
          <option key={u.value} value={u.value}>
            {u.label}
          </option>
        ))}
      </Select>
    </div>
  );
}
