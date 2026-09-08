import { useState } from "react";

// Replace frontend/public/rook.svg to update both placements. Keep the artwork intact.
export function RookLogo({ size = "rail" }: { size?: "rail" | "welcome" }) {
  const [missing, setMissing] = useState(false);
  return missing
    ? <span className={`rook-logo rook-logo-${size} logo-placeholder`}>Rook</span>
    : <img className={`rook-logo rook-logo-${size}`} src="/rook.svg" alt="Rook" onError={() => setMissing(true)} />;
}
