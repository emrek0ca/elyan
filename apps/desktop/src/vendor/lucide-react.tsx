import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement> & {
  size?: number | string;
  strokeWidth?: number | string;
  absoluteStrokeWidth?: boolean;
  color?: string;
};

function createIcon(children: React.ReactNode) {
  return function Icon({
    size = 24,
    strokeWidth = 1.8,
    color = "currentColor",
    className,
    children: _children,
    absoluteStrokeWidth: _absoluteStrokeWidth,
    ...props
  }: IconProps) {
    return (
      <svg
        viewBox="0 0 24 24"
        width={size}
        height={size}
        fill="none"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
        className={className}
        aria-hidden="true"
        {...props}
      >
        {children}
      </svg>
    );
  };
}

export const AlertTriangle = createIcon(
  <>
    <path d="M12 4 20 19H4Z" />
    <path d="M12 9v4" />
    <path d="M12 17h.01" />
  </>,
);

export const ArrowRight = createIcon(
  <>
    <path d="M5 12h13" />
    <path d="m13 6 6 6-6 6" />
  </>,
);

export const ArrowUpRight = createIcon(
  <>
    <path d="M7 17 17 7" />
    <path d="M9 7h8v8" />
  </>,
);

export const Cable = createIcon(
  <>
    <path d="M9 7V6a3 3 0 0 1 6 0v1" />
    <path d="M8 7h8" />
    <path d="M8 7v4a4 4 0 0 0 8 0V7" />
    <path d="M12 15v5" />
    <path d="M10 20h4" />
  </>,
);

export const CheckCircle2 = createIcon(
  <>
    <circle cx="12" cy="12" r="8" />
    <path d="m9 12 2 2 4-4" />
  </>,
);

export const Clock3 = createIcon(
  <>
    <circle cx="12" cy="12" r="8" />
    <path d="M12 8v5h4" />
  </>,
);

export const Cloud = createIcon(
  <>
    <path d="M7 18h9a4 4 0 0 0 .7-7.94A5.5 5.5 0 0 0 6.04 9.5 3.5 3.5 0 0 0 7 18Z" />
  </>,
);

export const Coins = createIcon(
  <>
    <ellipse cx="12" cy="7" rx="6.5" ry="3.2" />
    <path d="M5.5 7v5c0 1.8 2.9 3.2 6.5 3.2s6.5-1.4 6.5-3.2V7" />
    <path d="M5.5 12v5c0 1.8 2.9 3.2 6.5 3.2s6.5-1.4 6.5-3.2v-5" />
  </>,
);

export const Command = createIcon(
  <>
    <path d="M8 8a2 2 0 1 1-4 0 2 2 0 0 1 4 0v8a2 2 0 1 1-4 0 2 2 0 0 1 2-2h8a2 2 0 1 1 0 4 2 2 0 0 1 0-4H8" />
    <path d="M16 8a2 2 0 1 0 4 0 2 2 0 0 0-2-2H10a2 2 0 1 0 0 4h6v8a2 2 0 1 0 4 0 2 2 0 0 0-4 0" />
  </>,
);

export const Cpu = createIcon(
  <>
    <rect x="7" y="7" width="10" height="10" rx="2" />
    <path d="M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 15h3M1 9h3M1 15h3" />
  </>,
);

export const CreditCard = createIcon(
  <>
    <rect x="3" y="6" width="18" height="12" rx="2" />
    <path d="M3 10h18" />
    <path d="M7 15h4" />
  </>,
);

export const Crown = createIcon(
  <>
    <path d="m4 18 2-9 6 5 6-5 2 9Z" />
    <path d="M4 18h16" />
    <path d="M6 9 4 6M12 8V4M18 9l2-3" />
  </>,
);

export const Download = createIcon(
  <>
    <path d="M12 4v10" />
    <path d="m8 10 4 4 4-4" />
    <path d="M5 19h14" />
  </>,
);

export const ExternalLink = createIcon(
  <>
    <path d="M14 5h5v5" />
    <path d="M10 14 19 5" />
    <path d="M19 14v4a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h4" />
  </>,
);

export const Home = createIcon(
  <>
    <path d="m4 11 8-6 8 6" />
    <path d="M6 10v9h12v-9" />
  </>,
);

export const KeyRound = createIcon(
  <>
    <circle cx="8.5" cy="14.5" r="3.5" />
    <path d="M12 14.5h8" />
    <path d="M17 14.5v-2" />
    <path d="M19 14.5v-1.5" />
  </>,
);

export const Layers3 = createIcon(
  <>
    <path d="m12 4 8 4-8 4-8-4 8-4Z" />
    <path d="m4 12 8 4 8-4" />
    <path d="m4 16 8 4 8-4" />
  </>,
);

export const Mail = createIcon(
  <>
    <rect x="3" y="6" width="18" height="12" rx="2" />
    <path d="m4 8 8 6 8-6" />
  </>,
);

export const MailPlus = createIcon(
  <>
    <rect x="3" y="6" width="18" height="12" rx="2" />
    <path d="m4 8 8 6 8-6" />
    <path d="M18 3v4" />
    <path d="M16 5h4" />
  </>,
);

export const MessageSquare = createIcon(
  <>
    <path d="M5 7a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H11l-4 3v-3H7a2 2 0 0 1-2-2Z" />
  </>,
);

export const MessageSquareShare = createIcon(
  <>
    <path d="M5 7a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H11l-4 3v-3H7a2 2 0 0 1-2-2Z" />
    <path d="m13 9 4 3-4 3" />
    <path d="M10 12h7" />
  </>,
);

export const RefreshCw = createIcon(
  <>
    <path d="M20 6v5h-5" />
    <path d="M4 18v-5h5" />
    <path d="M18 11a6 6 0 0 0-10-4L5 11" />
    <path d="M6 13a6 6 0 0 0 10 4l3-4" />
  </>,
);

export const ScanQrCode = createIcon(
  <>
    <path d="M5 9V5h4" />
    <path d="M19 9V5h-4" />
    <path d="M5 15v4h4" />
    <path d="M19 15v4h-4" />
    <rect x="9" y="9" width="2.5" height="2.5" rx=".4" />
    <rect x="12.5" y="12.5" width="2.5" height="2.5" rx=".4" />
  </>,
);

export const Search = createIcon(
  <>
    <circle cx="11" cy="11" r="6" />
    <path d="m20 20-4.2-4.2" />
  </>,
);

export const ShieldAlert = createIcon(
  <>
    <path d="M12 4 6 6.5V12c0 4.2 2.4 6.9 6 8 3.6-1.1 6-3.8 6-8V6.5Z" />
    <path d="M12 8v4" />
    <path d="M12 15h.01" />
  </>,
);

export const ShieldCheck = createIcon(
  <>
    <path d="M12 4 6 6.5V12c0 4.2 2.4 6.9 6 8 3.6-1.1 6-3.8 6-8V6.5Z" />
    <path d="m9.5 12 1.8 1.8 3.2-3.2" />
  </>,
);

export const SlidersHorizontal = createIcon(
  <>
    <path d="M4 7h8" />
    <path d="M16 7h4" />
    <circle cx="14" cy="7" r="2" />
    <path d="M4 17h4" />
    <path d="M12 17h8" />
    <circle cx="10" cy="17" r="2" />
  </>,
);

export const Sparkles = createIcon(
  <>
    <path d="m12 4 1.5 4.5L18 10l-4.5 1.5L12 16l-1.5-4.5L6 10l4.5-1.5Z" />
    <path d="m5 3 .7 2.3L8 6l-2.3.7L5 9l-.7-2.3L2 6l2.3-.7Z" />
    <path d="m19 14 .9 2.6L22.5 18l-2.6.9L19 21.5l-.9-2.6L15.5 18l2.6-.9Z" />
  </>,
);

export const Ticket = createIcon(
  <>
    <path d="M4 8a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v2a2 2 0 0 0 0 4v2a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-2a2 2 0 0 0 0-4Z" />
    <path d="M9 8v8" />
  </>,
);

export const Trash2 = createIcon(
  <>
    <path d="M4 7h16" />
    <path d="M9 7V5h6v2" />
    <path d="M7 7l1 12h8l1-12" />
    <path d="M10 11v5M14 11v5" />
  </>,
);

export const UsersRound = createIcon(
  <>
    <circle cx="9" cy="9" r="3" />
    <circle cx="17" cy="10" r="2.5" />
    <path d="M4.5 18a4.5 4.5 0 0 1 9 0" />
    <path d="M14 18a3.5 3.5 0 0 1 6 0" />
  </>,
);

export const Wallet = createIcon(
  <>
    <path d="M5 8a2 2 0 0 1 2-2h10v12H7a2 2 0 0 1-2-2Z" />
    <path d="M17 9h2a2 2 0 0 1 2 2v3h-4Z" />
    <path d="M17 12h2" />
  </>,
);

export const Waypoints = createIcon(
  <>
    <circle cx="6" cy="18" r="2" />
    <circle cx="18" cy="6" r="2" />
    <circle cx="18" cy="18" r="2" />
    <path d="M7.5 16.5 16.5 7.5" />
    <path d="M8 18h8" />
  </>,
);

export const Mic = createIcon(
  <>
    <rect x="9" y="2" width="6" height="11" rx="3" />
    <path d="M19 11a7 7 0 0 1-14 0" />
    <line x1="12" y1="18" x2="12" y2="22" />
    <line x1="8" y1="22" x2="16" y2="22" />
  </>,
);

export const MicOff = createIcon(
  <>
    <line x1="2" y1="2" x2="22" y2="22" />
    <path d="M18.89 13.23A7.12 7.12 0 0 0 19 12v-2" />
    <path d="M5 10v2a7 7 0 0 0 12 5" />
    <path d="M15 9.34V5a3 3 0 0 0-5.68-1.33" />
    <path d="M9 9v3a3 3 0 0 0 5.12 2.12" />
    <line x1="12" y1="19" x2="12" y2="22" />
  </>,
);

export const Bot = createIcon(
  <>
    <rect x="3" y="11" width="18" height="11" rx="2" />
    <path d="M12 11V6" />
    <circle cx="12" cy="4" r="2" />
    <line x1="8" y1="16" x2="8" y2="16" strokeWidth="3" strokeLinecap="round" />
    <line x1="16" y1="16" x2="16" y2="16" strokeWidth="3" strokeLinecap="round" />
    <line x1="3" y1="15" x2="0" y2="15" />
    <line x1="21" y1="15" x2="24" y2="15" />
  </>,
);

export const Activity = createIcon(
  <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />,
);

export const Monitor = createIcon(
  <>
    <rect x="2" y="3" width="20" height="14" rx="2" />
    <line x1="8" y1="21" x2="16" y2="21" />
    <line x1="12" y1="17" x2="12" y2="21" />
  </>,
);

export const BellRing = createIcon(
  <>
    <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
    <path d="M13.73 21a2 2 0 0 1-3.46 0" />
    <path d="M2 8c0-2.2.7-4.3 2-6" />
    <path d="M22 8a10 10 0 0 0-2-6" />
  </>,
);

export const Zap = createIcon(
  <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />,
);

export const Layers = createIcon(
  <>
    <path d="m12 2 10 6.5-10 6.5L2 8.5Z" />
    <path d="m2 15 10 6.5 10-6.5" />
    <path d="m2 11.5 10 6.5 10-6.5" />
  </>,
);

export const ChevronDown = createIcon(
  <path d="m6 9 6 6 6-6" />,
);

export const ChevronRight = createIcon(
  <path d="m9 6 6 6-6 6" />,
);

export const Send = createIcon(
  <>
    <path d="m22 2-7 20-4-9-9-4Z" />
    <path d="M22 2 11 13" />
  </>,
);

export const User = createIcon(
  <>
    <circle cx="12" cy="8" r="4" />
    <path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" />
  </>,
);

export const X = createIcon(
  <>
    <path d="M18 6 6 18" />
    <path d="m6 6 12 12" />
  </>,
);

export const Check = createIcon(
  <path d="M20 6 9 17l-5-5" />,
);
