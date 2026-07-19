import { useMemo } from "react";
import { StyleSheet, View } from "react-native";

import { colors } from "@/src/theme";

type Star = { left: number; top: number; size: number; opacity: number };

function seeded(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 0xffffffff;
  };
}

/**
 * Lightweight cosmic backdrop: deep gradient + scattered static stars + 3 nebula blobs.
 * Pure RN, no SVG/Canvas — perf-friendly on the 20x20 grid screen.
 */
export function StarField({
  width,
  height,
  starCount = 80,
  seed = 7,
}: {
  width: number;
  height: number;
  starCount?: number;
  seed?: number;
}) {
  const stars = useMemo<Star[]>(() => {
    const rng = seeded(seed);
    return Array.from({ length: starCount }, () => ({
      left: rng() * width,
      top: rng() * height,
      size: rng() * 2 + 0.6,
      opacity: rng() * 0.7 + 0.25,
    }));
  }, [width, height, starCount, seed]);

  return (
    <View pointerEvents="none" style={[StyleSheet.absoluteFill, { width, height, overflow: "hidden" }]}>
      <View style={[styles.nebula, styles.nebulaBlue, { left: width * 0.1, top: height * 0.15 }]} />
      <View style={[styles.nebula, styles.nebulaGold, { left: width * 0.55, top: height * 0.55 }]} />
      <View style={[styles.nebula, styles.nebulaMagenta, { left: width * 0.7, top: height * 0.1 }]} />
      {stars.map((s, i) => (
        <View
          key={i}
          style={{
            position: "absolute",
            left: s.left,
            top: s.top,
            width: s.size,
            height: s.size,
            borderRadius: s.size / 2,
            backgroundColor: i % 9 === 0 ? colors.gold : "#FFFFFF",
            opacity: s.opacity,
          }}
        />
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  nebula: {
    position: "absolute",
    width: 260,
    height: 260,
    borderRadius: 200,
    opacity: 0.18,
  },
  nebulaBlue: { backgroundColor: "#00E5FF" },
  nebulaGold: { backgroundColor: "#FFD700" },
  nebulaMagenta: { backgroundColor: "#A66CFF" },
});
