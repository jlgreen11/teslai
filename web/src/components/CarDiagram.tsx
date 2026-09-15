import { fmtTemp } from "../format";

interface Props {
  tpms: { fl: number | null; fr: number | null; rl: number | null; rr: number | null };
  insideC: number | null; outsideC: number | null; locked: boolean | null; lowBar?: number; highBar?: number;
}

function Tire({ x, y, value, anchor, low, high }: { x: number; y: number; value: number | null; anchor: "start" | "end"; low: number; high: number }) {
  const psi = value == null ? null : value * 14.5038;
  const bad = value != null && (value < low || value > high);
  return (
    <g>
      <rect x={anchor === "start" ? x - 7 : x - 7} y={y - 14} width={14} height={28} rx={5}
        fill={bad ? "var(--color-critical)" : "#3a3f46"} />
      <text x={anchor === "start" ? x + 14 : x - 14} y={y + 4} textAnchor={anchor}
        className="num" fontSize="12" fill={bad ? "#ff8a8a" : "var(--color-ink-2)"}>
        {psi == null ? "–" : `${psi.toFixed(0)}`}
      </text>
    </g>
  );
}

export function CarDiagram({ tpms, insideC, outsideC, locked, lowBar = 2.6, highBar = 3.5 }: Props) {
  return (
    <svg viewBox="0 0 220 132" className="w-full max-w-[220px]" role="img"
      aria-label={`Tire pressures psi: front left ${tpms.fl ?? "unknown"}, front right ${tpms.fr ?? "unknown"}, rear left ${tpms.rl ?? "unknown"}, rear right ${tpms.rr ?? "unknown"}`}>
      <defs>
        <linearGradient id="body" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#2b3036" /><stop offset="0.5" stopColor="#3b4149" /><stop offset="1" stopColor="#2b3036" />
        </linearGradient>
      </defs>
      {/* top-down body, nose to the right */}
      <path d="M52 40 C60 26 88 22 118 22 L150 23 C176 25 190 40 194 58 L194 74 C190 92 176 107 150 109 L118 110 C88 110 60 106 52 92 C46 80 46 52 52 40 Z"
        fill="url(#body)" stroke="rgba(255,255,255,0.14)" />
      <path d="M92 34 L140 34 C152 36 160 48 162 66 C160 84 152 96 140 98 L92 98 C84 90 82 76 82 66 C82 56 84 42 92 34 Z" fill="#0f1114" opacity="0.85" />
      <text x="122" y="70" textAnchor="middle" fontSize="15" fontWeight="600" fill="var(--color-ink)">{fmtTemp(insideC)}</text>
      <text x="122" y="86" textAnchor="middle" fontSize="9" fill="var(--color-ink-3)">cabin</text>
      <Tire x={78} y={22} value={tpms.rl} anchor="end" low={lowBar} high={highBar} />
      <Tire x={172} y={22} value={tpms.fl} anchor="start" low={lowBar} high={highBar} />
      <Tire x={78} y={110} value={tpms.rr} anchor="end" low={lowBar} high={highBar} />
      <Tire x={172} y={110} value={tpms.fr} anchor="start" low={lowBar} high={highBar} />
      <g transform="translate(8 58)">
        <text fontSize="9" fill="var(--color-ink-3)">outside</text>
        <text y="16" fontSize="14" fontWeight="600" fill="var(--color-ink-2)">{fmtTemp(outsideC)}</text>
      </g>
      {locked != null && (
        <g transform="translate(200 60)" aria-label={locked ? "Locked" : "Unlocked"}>
          <rect x="-2" y="4" width="14" height="11" rx="2" fill={locked ? "var(--color-ink-2)" : "var(--color-warning)"} />
          <path d={locked ? "M1 5 V1 a4 4 0 0 1 8 0 V5" : "M1 5 V1 a4 4 0 0 1 8 0"} fill="none"
            stroke={locked ? "var(--color-ink-2)" : "var(--color-warning)"} strokeWidth="2" />
        </g>
      )}
    </svg>
  );
}
