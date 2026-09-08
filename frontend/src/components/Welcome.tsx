import { useEffect, useState } from "react";
import { RookLogo } from "./RookLogo";

export const WELCOME = {
  sentences: ["What do you want to know about Roei?", "Looking for a business inquiry?", "How may I help you today?"],
  typeMs: 65, pauseMs: 2300, deleteMs: 30, betweenMs: 350,
};

export function Welcome() {
  const [reducedMotion, setReducedMotion] = useState(() => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false);
  const [frame, setFrame] = useState({ sentence: 0, count: 0, deleting: false });
  useEffect(() => {
    const preference = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    const update = () => setReducedMotion(preference?.matches ?? false);
    preference?.addEventListener("change", update);
    return () => preference?.removeEventListener("change", update);
  }, []);
  useEffect(() => {
    if (reducedMotion) return;
    const text = WELCOME.sentences[frame.sentence];
    const delay = frame.deleting ? WELCOME.deleteMs : frame.count === text.length ? WELCOME.pauseMs : frame.count === 0 ? WELCOME.betweenMs : WELCOME.typeMs;
    const timer = window.setTimeout(() => setFrame((current) => {
      if (!current.deleting && current.count === text.length) return { ...current, deleting: true };
      if (current.deleting && current.count === 0) return { sentence: (current.sentence + 1) % WELCOME.sentences.length, count: 0, deleting: false };
      return { ...current, count: current.count + (current.deleting ? -1 : 1) };
    }), delay);
    return () => window.clearTimeout(timer);
  }, [frame, reducedMotion]);
  return <div className="welcome-heading">
    <RookLogo size="welcome" />
    <h1 className="welcome-title">
      <span className="sr-only">{WELCOME.sentences[0]}</span>
      {WELCOME.sentences.map((sentence) => <span key={sentence} className="welcome-sizer" aria-hidden="true">{sentence}</span>)}
      <span className="welcome-typed" aria-hidden="true">
        {reducedMotion ? WELCOME.sentences[0] : WELCOME.sentences[frame.sentence].slice(0, frame.count)}
        {!reducedMotion && <span className="typing-cursor" />}
      </span>
    </h1>
  </div>;
}
