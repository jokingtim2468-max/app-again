/** Apollo "A" rocket emblem: open-legged A with an arrowhead rocket launching between the legs. */
export default function AppLogo({ size = 26, color = 'currentColor', title = 'Apollo Trading' }: { size?: number; color?: string; title?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 100 104" role="img" aria-label={title} fill={color}>
      <path d="M50 4 L96 100 H72 L50 52 L28 100 H4 Z" />
      <path d="M50 66 L60 92 L50 85 L40 92 Z" />
    </svg>
  );
}
