"use client";

import { motion, MotionConfig } from "motion/react";

export const EASE_OUT = [0.22, 1, 0.36, 1] as const;

/** Global motion defaults: short, ease-out, and off when the user prefers reduced motion. */
export function MotionProvider({ children }: { children: React.ReactNode }) {
  return (
    <MotionConfig reducedMotion="user" transition={{ duration: 0.22, ease: EASE_OUT }}>
      {children}
    </MotionConfig>
  );
}

export function PageFade({ children }: { children: React.ReactNode }) {
  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.24, ease: EASE_OUT }}>
      {children}
    </motion.div>
  );
}
