import { useEffect, useState, type CSSProperties } from "react";

export function RookLogo({ size = "rail" }: { size?: "rail" | "menu" }) {
  return <span className={`rook-logo rook-logo-${size}`} role="img" aria-label="Rook" />;
}

interface WelcomeRookLogoProps {
  spinDurationMs: number;
  spinIntervalMs: number;
  hoverDurationMs: number;
  reducedMotion: boolean;
}

export function WelcomeRookLogo({ spinDurationMs, spinIntervalMs, hoverDurationMs, reducedMotion }: WelcomeRookLogoProps) {
  const [spinning, setSpinning] = useState(false);

  useEffect(() => {
    if (reducedMotion) {
      setSpinning(false);
      return;
    }
    let stopTimer: number | undefined;
    let nextTimer: number | undefined;
    const beginSpin = () => {
      setSpinning(true);
      stopTimer = window.setTimeout(() => {
        setSpinning(false);
        nextTimer = window.setTimeout(beginSpin, spinIntervalMs);
      }, spinDurationMs);
    };
    nextTimer = window.setTimeout(beginSpin, spinIntervalMs);
    return () => {
      window.clearTimeout(stopTimer);
      window.clearTimeout(nextTimer);
    };
  }, [reducedMotion, spinDurationMs, spinIntervalMs]);

  const timing = {
    "--rook-spin-duration": `${spinDurationMs}ms`,
    "--rook-hover-duration": `${hoverDurationMs}ms`,
  } as CSSProperties;

  return <div className={`welcome-rook-logo ${reducedMotion ? "is-static" : ""}`} style={timing} role="img" aria-label="Rook">
    <span className="welcome-logo-mark" aria-hidden="true">
      <span className={`welcome-logo-orbit ${spinning ? "is-spinning" : ""}`} />
      <span className="welcome-logo-dot" />
    </span>
    <span className="welcome-logo-wordmark" aria-hidden="true" />
  </div>;
}
