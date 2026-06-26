import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Dimensions,
  Pressable,
  StyleSheet,
  Text,
  View,
  ScrollView,
} from "react-native";
import { GestureDetector, Gesture } from "react-native-gesture-handler";
import Animated, {
  runOnJS,
  useAnimatedStyle,
  useSharedValue,
  withSpring,
} from "react-native-reanimated";
import * as Haptics from "expo-haptics";
import { Ionicons } from "@expo/vector-icons";
import { Image } from "expo-image";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, Pixel } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing } from "@/src/theme";

const GRID = 20;
const { width: SCREEN_W } = Dimensions.get("window");
const BASE_BOARD = Math.min(SCREEN_W, 500) - spacing.xl * 2;
const CELL = BASE_BOARD / GRID;

type Status = "available" | "owned" | "mine";

function statusColor(s: Status) {
  if (s === "mine") return colors.brand;
  if (s === "owned") return "#3A3F47";
  return "#11252C"; // subtle teal for available
}

export default function MapScreen() {
  const { user, logout, refresh } = useAuth();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const [pixels, setPixels] = useState<Pixel[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Pixel | null>(null);
  const [buying, setBuying] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const scale = useSharedValue(1);
  const savedScale = useSharedValue(1);
  const tx = useSharedValue(0);
  const ty = useSharedValue(0);
  const savedTx = useSharedValue(0);
  const savedTy = useSharedValue(0);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const list = await api.listPixels();
      setPixels(list);
    } catch (e: any) {
      setErr(e?.message || "Failed to load pixels");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const pinch = Gesture.Pinch()
    .onStart(() => {
      savedScale.value = scale.value;
    })
    .onUpdate((e) => {
      const next = savedScale.value * e.scale;
      scale.value = Math.min(4, Math.max(1, next));
    });

  const pan = Gesture.Pan()
    .minDistance(8)
    .onStart(() => {
      savedTx.value = tx.value;
      savedTy.value = ty.value;
    })
    .onUpdate((e) => {
      tx.value = savedTx.value + e.translationX;
      ty.value = savedTy.value + e.translationY;
    })
    .onEnd(() => {
      const max = (BASE_BOARD * (scale.value - 1)) / 2;
      tx.value = withSpring(Math.max(-max, Math.min(max, tx.value)));
      ty.value = withSpring(Math.max(-max, Math.min(max, ty.value)));
    });

  const composed = Gesture.Simultaneous(pinch, pan);

  const boardStyle = useAnimatedStyle(() => ({
    transform: [
      { translateX: tx.value },
      { translateY: ty.value },
      { scale: scale.value },
    ],
  }));

  const openSelected = useCallback(
    (p: Pixel) => {
      Haptics.selectionAsync().catch(() => {});
      setSelected(p);
    },
    [],
  );

  const onBuy = useCallback(async () => {
    if (!selected) return;
    try {
      setBuying(true);
      setErr(null);
      const updated = await api.buyPixel(selected.pixel_id);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
      setPixels((prev) =>
        prev.map((p) => (p.pixel_id === updated.pixel_id ? updated : p)),
      );
      setSelected(updated);
      await refresh();
    } catch (e: any) {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error).catch(() => {});
      setErr(e?.message || "Buy failed");
    } finally {
      setBuying(false);
    }
  }, [selected, refresh]);

  const zoomIn = () => {
    scale.value = Math.min(4, scale.value + 0.4);
  };
  const zoomOut = () => {
    scale.value = Math.max(1, scale.value - 0.4);
  };
  const zoomReset = () => {
    scale.value = withSpring(1);
    tx.value = withSpring(0);
    ty.value = withSpring(0);
  };

  const renderedGrid = useMemo(() => {
    if (pixels.length === 0) return null;
    return pixels.map((p) => {
      const status: Status =
        p.owner_id === user?.user_id
          ? "mine"
          : p.owner_id
          ? "owned"
          : "available";
      return (
        <Pressable
          key={p.pixel_id}
          testID={`pixel-${p.pixel_id}`}
          onPress={() => {
            // runOnJS shim not needed since this is a regular Pressable
            runOnJS(openSelected)(p);
          }}
          style={[
            styles.cell,
            {
              width: CELL,
              height: CELL,
              left: p.x * CELL,
              top: p.y * CELL,
              backgroundColor: statusColor(status),
              borderColor:
                status === "mine" ? colors.brand : "#0A0D12",
            },
          ]}
        />
      );
    });
  }, [pixels, user?.user_id, openSelected]);

  const available = pixels.filter((p) => !p.owner_id).length;
  const sold = pixels.length - available;

  return (
    <View style={styles.container} testID="map-screen">
      {/* HUD top */}
      <View style={[styles.hudTop, { paddingTop: insets.top + spacing.sm }]}>
        <Pressable
          testID="profile-pill"
          style={styles.pill}
          onPress={() => router.push("/profile")}
        >
          {user?.picture ? (
            <Image source={{ uri: user.picture }} style={styles.avatar} />
          ) : (
            <View style={[styles.avatar, styles.avatarFallback]}>
              <Ionicons name="person" size={14} color={colors.onSurface} />
            </View>
          )}
          <Text style={styles.pillText} numberOfLines={1}>
            {user?.name?.split(" ")[0] || "You"}
          </Text>
          <View style={styles.dot} />
          <Text style={styles.pillTextStrong}>{user?.pixels_owned ?? 0}</Text>
        </Pressable>

        <View style={styles.pill} testID="coin-pill">
          <Ionicons name="diamond" size={14} color={colors.brand} />
          <Text style={styles.pillTextStrong}>{user?.coins ?? 0}</Text>
        </View>
      </View>

      {/* Board */}
      <View style={styles.boardWrap}>
        {loading ? (
          <ActivityIndicator color={colors.brand} />
        ) : (
          <GestureDetector gesture={composed}>
            <Animated.View
              style={[
                {
                  width: BASE_BOARD,
                  height: BASE_BOARD,
                  backgroundColor: "#0A0D12",
                  borderColor: colors.border,
                  borderWidth: 1,
                  borderRadius: radius.md,
                  overflow: "hidden",
                },
                boardStyle,
              ]}
              testID="pixel-board"
            >
              {renderedGrid}
            </Animated.View>
          </GestureDetector>
        )}
      </View>

      {/* Legend + counters */}
      <View style={styles.legendRow}>
        <View style={styles.legendChip}>
          <View style={[styles.legendDot, { backgroundColor: "#11252C" }]} />
          <Text style={styles.legendText}>{available} available</Text>
        </View>
        <View style={styles.legendChip}>
          <View style={[styles.legendDot, { backgroundColor: "#3A3F47" }]} />
          <Text style={styles.legendText}>{sold} sold</Text>
        </View>
        <View style={styles.legendChip}>
          <View style={[styles.legendDot, { backgroundColor: colors.brand }]} />
          <Text style={styles.legendText}>{user?.pixels_owned || 0} yours</Text>
        </View>
      </View>

      {/* Zoom controls */}
      <View style={styles.zoomCol}>
        <Pressable testID="zoom-in" style={styles.zoomBtn} onPress={zoomIn}>
          <Ionicons name="add" size={20} color={colors.onSurface} />
        </Pressable>
        <Pressable testID="zoom-out" style={styles.zoomBtn} onPress={zoomOut}>
          <Ionicons name="remove" size={20} color={colors.onSurface} />
        </Pressable>
        <Pressable testID="zoom-reset" style={styles.zoomBtn} onPress={zoomReset}>
          <Ionicons name="locate" size={18} color={colors.onSurface} />
        </Pressable>
      </View>

      {/* Bottom action bar */}
      <View style={[styles.actionBar, { paddingBottom: insets.bottom + spacing.sm }]}>
        {user?.is_admin ? (
          <Pressable
            testID="admin-link-btn"
            style={styles.adminBtn}
            onPress={() => router.push("/admin")}
          >
            <Ionicons name="construct" size={16} color={colors.brand} />
            <Text style={styles.adminBtnText}>Admin</Text>
          </Pressable>
        ) : (
          <View style={{ width: 80 }} />
        )}
        <Text style={styles.hint}>Tap a pixel · Pinch to zoom · Drag to pan</Text>
        <Pressable testID="logout-btn" style={styles.adminBtn} onPress={logout}>
          <Ionicons name="log-out-outline" size={16} color={colors.onSurfaceSecondary} />
        </Pressable>
      </View>

      {/* Detail sheet (simple modal-style, non-blocking using overlay only on sheet) */}
      {selected ? (
        <View style={styles.sheetWrap} pointerEvents="box-none">
          <Pressable
            style={styles.sheetDismiss}
            onPress={() => setSelected(null)}
            testID="sheet-dismiss"
          />
          <View style={[styles.sheet, { paddingBottom: insets.bottom + spacing.lg }]}>
            <View style={styles.sheetHandle} />
            <ScrollView showsVerticalScrollIndicator={false}>
              <Image
                source={{ uri: selected.cover_image }}
                style={styles.sheetCover}
                contentFit="cover"
              />
              <View style={{ padding: spacing.lg, gap: spacing.sm }}>
                <Text style={styles.sheetTitle}>{selected.name}</Text>
                <Text style={styles.sheetCoord}>
                  X {selected.x} · Y {selected.y}
                </Text>
                <Text style={styles.sheetDesc}>{selected.description}</Text>

                <View style={styles.row}>
                  <Text style={styles.rowLabel}>Owner</Text>
                  <Text style={styles.rowValue}>
                    {selected.owner_name || "Unclaimed"}
                  </Text>
                </View>
                <View style={styles.row}>
                  <Text style={styles.rowLabel}>Price</Text>
                  <Text style={styles.rowValue}>
                    <Ionicons name="diamond" size={14} color={colors.brand} />{" "}
                    {selected.price}
                  </Text>
                </View>
                {selected.purchased_at ? (
                  <View style={styles.row}>
                    <Text style={styles.rowLabel}>Purchased</Text>
                    <Text style={styles.rowValue}>
                      {new Date(selected.purchased_at).toLocaleDateString()}
                    </Text>
                  </View>
                ) : null}

                {err ? <Text style={styles.error}>{err}</Text> : null}

                {!selected.owner_id ? (
                  <Pressable
                    testID="buy-pixel-button"
                    style={({ pressed }) => [
                      styles.buyBtn,
                      pressed && { opacity: 0.85 },
                      buying && { opacity: 0.6 },
                    ]}
                    disabled={buying}
                    onPress={onBuy}
                  >
                    {buying ? (
                      <ActivityIndicator color={colors.onBrand} />
                    ) : (
                      <Text style={styles.buyBtnText}>
                        Buy for {selected.price} coins
                      </Text>
                    )}
                  </Pressable>
                ) : (
                  <Pressable
                    testID="view-pixel-page"
                    style={styles.secondaryBtn}
                    onPress={() => {
                      const id = selected.pixel_id;
                      setSelected(null);
                      router.push(`/pixel/${id}`);
                    }}
                  >
                    <Text style={styles.secondaryBtnText}>View pixel page</Text>
                  </Pressable>
                )}
              </View>
            </ScrollView>
          </View>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  hudTop: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    flexDirection: "row",
    justifyContent: "space-between",
    paddingHorizontal: spacing.lg,
    zIndex: 5,
    gap: spacing.sm,
  },
  pill: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    backgroundColor: colors.surfaceSecondary + "EE",
    borderColor: colors.border,
    borderWidth: 1,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: radius.pill,
    maxWidth: 200,
  },
  avatar: { width: 22, height: 22, borderRadius: 11, backgroundColor: colors.surfaceTertiary },
  avatarFallback: { alignItems: "center", justifyContent: "center" },
  pillText: { color: colors.onSurface, fontSize: 13, fontWeight: "500" },
  pillTextStrong: { color: colors.onSurface, fontSize: 13, fontWeight: "700" },
  dot: { width: 3, height: 3, borderRadius: 2, backgroundColor: colors.onSurfaceTertiary },
  boardWrap: { flex: 1, alignItems: "center", justifyContent: "center", paddingHorizontal: spacing.xl },
  cell: {
    position: "absolute",
    borderWidth: 0.5,
  },
  legendRow: {
    position: "absolute",
    bottom: 88,
    left: 0,
    right: 0,
    flexDirection: "row",
    justifyContent: "center",
    gap: spacing.sm,
  },
  legendChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    backgroundColor: colors.surfaceSecondary,
    borderColor: colors.border,
    borderWidth: 1,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
    borderRadius: radius.pill,
  },
  legendDot: { width: 8, height: 8, borderRadius: 4 },
  legendText: { color: colors.onSurfaceSecondary, fontSize: 11, letterSpacing: 0.5 },
  zoomCol: {
    position: "absolute",
    right: spacing.lg,
    top: "40%",
    gap: spacing.sm,
  },
  zoomBtn: {
    width: 40,
    height: 40,
    borderRadius: radius.pill,
    backgroundColor: colors.surfaceSecondary,
    borderColor: colors.border,
    borderWidth: 1,
    alignItems: "center",
    justifyContent: "center",
  },
  actionBar: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.sm,
  },
  adminBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: radius.pill,
    backgroundColor: colors.surfaceSecondary,
    borderColor: colors.border,
    borderWidth: 1,
  },
  adminBtnText: { color: colors.brand, fontSize: 12, fontWeight: "600", letterSpacing: 1 },
  hint: { color: colors.onSurfaceTertiary, fontSize: 11, letterSpacing: 0.5 },
  sheetWrap: { ...StyleSheet.absoluteFillObject, justifyContent: "flex-end" },
  sheetDismiss: { ...StyleSheet.absoluteFillObject, backgroundColor: "#00000099" },
  sheet: {
    backgroundColor: colors.surfaceSecondary,
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    maxHeight: "75%",
    borderTopColor: colors.border,
    borderTopWidth: 1,
  },
  sheetHandle: {
    alignSelf: "center",
    width: 40,
    height: 4,
    backgroundColor: colors.borderStrong,
    borderRadius: 2,
    marginTop: spacing.sm,
  },
  sheetCover: { width: "100%", height: 160, backgroundColor: "#000" },
  sheetTitle: { color: colors.onSurface, fontSize: 22, fontWeight: "700" },
  sheetCoord: { color: colors.brand, fontSize: 12, letterSpacing: 2 },
  sheetDesc: { color: colors.onSurfaceSecondary, fontSize: 14, lineHeight: 20, marginVertical: spacing.sm },
  row: {
    flexDirection: "row",
    justifyContent: "space-between",
    paddingVertical: spacing.sm,
    borderBottomColor: colors.divider,
    borderBottomWidth: 1,
  },
  rowLabel: { color: colors.onSurfaceTertiary, fontSize: 13, letterSpacing: 0.5, textTransform: "uppercase" },
  rowValue: { color: colors.onSurface, fontSize: 14, fontWeight: "600" },
  buyBtn: {
    backgroundColor: colors.brand,
    paddingVertical: spacing.lg,
    borderRadius: radius.pill,
    alignItems: "center",
    marginTop: spacing.lg,
  },
  buyBtnText: { color: colors.onBrand, fontWeight: "700", fontSize: 15, letterSpacing: 1 },
  secondaryBtn: {
    borderColor: colors.brand,
    borderWidth: 1,
    paddingVertical: spacing.lg,
    borderRadius: radius.pill,
    alignItems: "center",
    marginTop: spacing.lg,
  },
  secondaryBtnText: { color: colors.brand, fontWeight: "700", fontSize: 15, letterSpacing: 1 },
  error: { color: colors.error, marginTop: spacing.sm },
});
