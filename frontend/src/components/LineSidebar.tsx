import { useRef, useState, type PointerEvent } from "react";

export interface LineSidebarProps {
  items: string[];
  activeIndex?: number;
  defaultActive?: number;
  onItemClick?: (index: number, label: string) => void;
  accentColor?: string;
  textColor?: string;
  markerColor?: string;
  showIndex?: boolean;
  showMarker?: boolean;
  /** Distância (px) em que um item reage ao ponteiro. */
  proximityRadius?: number;
  /** Deslocamento horizontal máximo (px) do rótulo em direção ao ponteiro. */
  maxShift?: number;
  falloff?: "smooth" | "linear";
  /** Comprimento da linha-marcador (px). */
  markerLength?: number;
  /** Espaço (px) entre a linha e o rótulo. */
  markerGap?: number;
  /** Escala da linha quando o item está perto do ponteiro ou ativo. */
  tickScale?: number;
  scaleTick?: boolean;
  /** Espaço (px) entre itens. */
  itemGap?: number;
  /** Tamanho da fonte em rem. */
  fontSize?: number;
  /** Duração (ms) da transição de deslocamento e escala. */
  smoothing?: number;
  className?: string;
}

function weight(distance: number, radius: number, falloff: "smooth" | "linear"): number {
  if (distance >= radius) return 0;
  const t = 1 - distance / radius;
  return falloff === "smooth" ? (1 - Math.cos(t * Math.PI)) / 2 : t;
}

export default function LineSidebar({
  items,
  activeIndex,
  defaultActive = 0,
  onItemClick,
  accentColor = "#A855F7",
  textColor = "#c4c4c4",
  markerColor = "#6c6c6c",
  showIndex = true,
  showMarker = true,
  proximityRadius = 100,
  maxShift = 30,
  falloff = "smooth",
  markerLength = 60,
  markerGap = 0,
  tickScale = 0.5,
  scaleTick = true,
  itemGap = 20,
  fontSize = 1.1,
  smoothing = 100,
  className = "",
}: LineSidebarProps) {
  const [internalActive, setInternalActive] = useState(defaultActive);
  const [pointerY, setPointerY] = useState<number | null>(null);
  const [pointerInside, setPointerInside] = useState(false);
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const active = activeIndex ?? internalActive;

  const onMove = (e: PointerEvent<HTMLDivElement>) => {
    setPointerY(e.clientY);
    setPointerInside(true);
  };

  const onLeave = () => {
    setPointerInside(false);
    setPointerY(null);
  };

  const transition = `transform ${smoothing}ms ease-out, width ${smoothing}ms ease-out, background-color ${smoothing}ms ease-out`;

  return (
    <div
      className={`flex flex-col ${className}`}
      style={{ gap: itemGap }}
      onPointerMove={onMove}
      onPointerLeave={onLeave}
      role="navigation"
    >
      {items.map((label, i) => {
        const el = itemRefs.current[i];
        let w = 0;
        if (pointerInside && pointerY !== null && el) {
          const rect = el.getBoundingClientRect();
          const center = rect.top + rect.height / 2;
          w = weight(Math.abs(pointerY - center), proximityRadius, falloff);
        }
        const isActive = i === active;
        const emphasis = Math.max(w, isActive ? 1 : 0);
        const shift = maxShift * w;
        const lineScale = scaleTick ? 1 + (tickScale - 0.5) * emphasis + emphasis * 0.5 : 1;
        const color = isActive ? accentColor : textColor;

        return (
          <button
            key={label}
            ref={(node) => {
              itemRefs.current[i] = node;
            }}
            type="button"
            aria-current={isActive ? "page" : undefined}
            onClick={() => {
              setInternalActive(i);
              onItemClick?.(i, label);
            }}
            className="flex w-full items-center gap-3 bg-transparent text-left outline-none"
            style={{
              transform: `translateX(${shift}px)`,
              transition,
              color,
              fontSize: `${fontSize}rem`,
            }}
          >
            {showIndex && (
              <span className="w-6 font-mono text-[0.7em] tabular-nums opacity-70">{String(i + 1).padStart(2, "0")}</span>
            )}
            {showMarker && (
              <span
                aria-hidden="true"
                className="block h-px shrink-0 origin-left rounded-full"
                style={{
                  width: markerLength,
                  marginRight: markerGap,
                  backgroundColor: isActive ? accentColor : markerColor,
                  transform: `scaleX(${lineScale})`,
                  transition,
                }}
              />
            )}
            <span className="truncate font-medium">{label}</span>
          </button>
        );
      })}
    </div>
  );
}
