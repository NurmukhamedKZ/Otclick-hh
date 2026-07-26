import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement> & { size?: number; sw?: number };

const Base = ({ size = 20, sw = 1.6, children, ...rest }: IconProps & { children: React.ReactNode }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth={sw}
    strokeLinecap="round"
    strokeLinejoin="round"
    {...rest}
  >
    {children}
  </svg>
);

export const IHome = (p: IconProps) => <Base {...p}><path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z" /></Base>;
export const IList = (p: IconProps) => <Base {...p}><path d="M8 6h13M8 12h13M8 18h13" /><circle cx="3.5" cy="6" r="1" /><circle cx="3.5" cy="12" r="1" /><circle cx="3.5" cy="18" r="1" /></Base>;
export const IFilter = (p: IconProps) => <Base {...p}><path d="M3 5h18l-7 8v6l-4 2v-8z" /></Base>;
export const IBell = (p: IconProps) => <Base {...p}><path d="M6 8a6 6 0 0 1 12 0v5l1.5 2.5h-15L6 13z" /><path d="M10 19a2 2 0 0 0 4 0" /></Base>;
export const IUser = (p: IconProps) => <Base {...p}><circle cx="12" cy="8" r="4" /><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6" /></Base>;
export const ISettings = (p: IconProps) => <Base {...p}><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" /></Base>;
export const ISearch = (p: IconProps) => <Base {...p}><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></Base>;
export const IPlay = (p: IconProps) => <Base {...p} fill="currentColor" stroke="none"><path d="M7 5v14l12-7z" /></Base>;
export const IPause = (p: IconProps) => <Base {...p} fill="currentColor" stroke="none"><rect x="6" y="5" width="4" height="14" rx="1" /><rect x="14" y="5" width="4" height="14" rx="1" /></Base>;
export const IRefresh = (p: IconProps) => <Base {...p}><path d="M3 12a9 9 0 0 1 15-6.7L21 8" /><path d="M21 3v5h-5" /><path d="M21 12a9 9 0 0 1-15 6.7L3 16" /><path d="M3 21v-5h5" /></Base>;
export const IPlus = (p: IconProps) => <Base {...p}><path d="M12 5v14M5 12h14" /></Base>;
export const IClose = (p: IconProps) => <Base {...p}><path d="M6 6l12 12M18 6l-6 12" /></Base>;
export const ICheck = (p: IconProps) => <Base {...p}><path d="m5 12 5 5 9-11" /></Base>;
export const IExternal = (p: IconProps) => <Base {...p}><path d="M14 5h5v5" /><path d="M19 5 10 14" /><path d="M19 13v6a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h6" /></Base>;
export const IArrow = (p: IconProps) => <Base {...p}><path d="M5 12h14M13 6l6 6-6 6" /></Base>;
export const IChevDown = (p: IconProps) => <Base {...p}><path d="m6 9 6 6 6-6" /></Base>;
export const IChevRight = (p: IconProps) => <Base {...p}><path d="m9 6 6 6-6 6" /></Base>;
export const ISpark = (p: IconProps) => <Base {...p}><path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6" /></Base>;
export const IShield = (p: IconProps) => <Base {...p}><path d="M12 3 4 6v6c0 5 4 8 8 9 4-1 8-4 8-9V6z" /><path d="m9 12 2 2 4-4" /></Base>;
export const IBolt = (p: IconProps) => <Base {...p}><path d="M13 2 3 14h7l-1 8 10-12h-7z" /></Base>;
export const IDoc = (p: IconProps) => <Base {...p}><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" /><path d="M14 3v6h6" /><path d="M8 13h8M8 17h6" /></Base>;
export const ILink = (p: IconProps) => <Base {...p}><path d="M10 14a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1" /><path d="M14 10a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1" /></Base>;
export const IPower = (p: IconProps) => <Base {...p}><path d="M18.4 6.6a9 9 0 1 1-12.8 0" /><path d="M12 2v10" /></Base>;
export const ITrash = (p: IconProps) => <Base {...p}><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" /></Base>;
export const IMail = (p: IconProps) => <Base {...p}><rect x="3" y="5" width="18" height="14" rx="2" /><path d="m3 7 9 6 9-6" /></Base>;
export const ILock = (p: IconProps) => <Base {...p}><rect x="4" y="11" width="16" height="10" rx="2" /><path d="M8 11V7a4 4 0 1 1 8 0v4" /></Base>;
export const IEye = (p: IconProps) => <Base {...p}><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" /></Base>;
export const ITelegram = (p: IconProps) => <Base {...p}><path d="m21 4-9 17-2.5-7.5L2 11z" /><path d="M21 4 9.5 13.5" /></Base>;
export const IChart = (p: IconProps) => <Base {...p}><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" /></Base>;
export const IMenu = (p: IconProps) => <Base {...p}><path d="M4 6h16M4 12h16M4 18h16" /></Base>;
export const ILogout = (p: IconProps) => <Base {...p}><path d="M15 4h4a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-4" /><path d="M10 17l-5-5 5-5" /><path d="M15 12H5" /></Base>;

export const ILogo = ({ size = 28 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 32 32" fill="none">
    <rect x="2" y="2" width="28" height="28" rx="9" fill="#1A1B1F" />
    <circle cx="12" cy="16" r="3.2" fill="#F5CB3D" />
    <circle cx="20" cy="16" r="3.2" fill="#E96B58" />
  </svg>
);
