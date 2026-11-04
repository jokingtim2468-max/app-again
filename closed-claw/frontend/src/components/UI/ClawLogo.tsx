export default function ClawLogo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-label="Closed Claw">
      <path d="M8 26 C4 18 6 8 14 5" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" />
      <path d="M13 27 C10 19 12 10 19 7" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" />
      <path d="M18 27 C17 20 19 13 25 11" stroke="var(--accent-2)" strokeWidth="2" strokeLinecap="round" />
      <path d="M7 26 H21" stroke="var(--line-2)" strokeWidth="2" strokeLinecap="round" />
      <circle cx="24" cy="21" r="2.5" stroke="var(--accent-2)" strokeWidth="1.5" />
    </svg>
  );
}
