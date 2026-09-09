export function RookLogo({ size = "rail" }: { size?: "rail" | "welcome" | "menu" }) {
  return <span className={`rook-logo rook-logo-${size}`} role="img" aria-label="Rook" />;
}
