import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Dimensions,
  Modal,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
  ScrollView,
} from "react-native";
import { GestureDetector, Gesture } from "react-native-gesture-handler";
import Animated, {
  runOnJS,
  useAnimatedStyle,
  useSharedValue,
  withSpring,
  withTiming,
  withSequence,
} from "react-native-reanimated";
import * as Haptics from "expo-haptics";
import { Ionicons } from "@expo/vector-icons";
import { Image } from "expo-image";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, Pixel } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { StarField } from "@/src/components/StarField";
import { CoverView } from "@/src/components/Cover";
import { colors, radius, spacing } from "@/src/theme";

const GRID = 20;
const { width: SCREEN_W, height: SCREEN_H } = Dimensions.get("window");
const BASE_BOARD = Math.min(SCREEN_W, 500) - spacing.xl * 2;
const CELL = BASE_BOARD / GRID;

type Status = "available" | "owned" | "mine" | "listed" | "mine-listed";

  function statusColor(s: Status) {
    if (s === "mine-listed") return colors.gold;
    if (s === "mine") return colors.brand;
    if (s === "listed") return colors.gold;
    if (s === "owned") return "#3A3F47";
    return "#11252C";
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
  // Post-buy celebration + wizard
  const [celebrate, setCelebrate] = useState<Pixel | null>(null);
  const [wizard, setWizard] = useState<Pixel | null>(null);
  const sweep = useSharedValue(0);

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
      setSelected(null);
      await refresh();
      // Trigger celebration animation + wizard
      setCelebrate(updated);
      sweep.value = 0;
      sweep.value = withSequence(
        withTiming(1, { duration: 900 }),
        withTiming(0, { duration: 1 }),
      );
      setTimeout(() => {
        setCelebrate(null);
        setWizard(updated);
      }, 1400);
    } catch (e: any) {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error).catch(() => {});
      setErr(e?.message || "Falha na compra");
    } finally {
      setBuying(false);
    }
  }, [selected, refresh, sweep]);

  const sweepStyle = useAnimatedStyle(() => ({
    opacity: sweep.value > 0 && sweep.value < 1 ? 1 : 0,
    transform: [{ translateX: -SCREEN_W + sweep.value * SCREEN_W * 2 }],
  }));

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
      const isMine = p.owner_id === user?.user_id;
      const isListed = !!p.listed_price;
      const status: Status = isMine
        ? isListed
          ? "mine-listed"
          : "mine"
        : p.owner_id
        ? isListed
          ? "listed"
          : "owned"
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
                status === "mine" || status === "mine-listed"
                  ? colors.brand
                  : status === "listed"
                  ? "#FF9F1C"
                  : "#0A0D12",
            },
          ]}
        />
      );
    });
  }, [pixels, user?.user_id, openSelected]);

  const available = pixels.filter((p) => !p.owner_id).length;
  const listed = pixels.filter((p) => !!p.listed_price).length;
  const sold = pixels.length - available;

  return (
    <View style={styles.container} testID="map-screen">
      {/* Cosmic background */}
      <View pointerEvents="none" style={StyleSheet.absoluteFill}>
        <StarField width={SCREEN_W} height={SCREEN_H} starCount={90} seed={42} />
      </View>
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
          <Text style={styles.legendText}>{available}</Text>
        </View>
        <View style={styles.legendChip}>
          <View style={[styles.legendDot, { backgroundColor: "#3A3F47" }]} />
          <Text style={styles.legendText}>{sold} criados</Text>
        </View>
        <View style={styles.legendChip}>
          <View style={[styles.legendDot, { backgroundColor: colors.gold }]} />
          <Text style={styles.legendText}>{listed} à venda</Text>
        </View>
        <View style={styles.legendChip}>
          <View style={[styles.legendDot, { backgroundColor: colors.brand }]} />
          <Text style={styles.legendText}>{user?.pixels_owned || 0} seus</Text>
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
        <Pressable
          testID="leaderboard-link-btn"
          style={styles.adminBtn}
          onPress={() => router.push("/leaderboard")}
        >
          <Ionicons name="trophy" size={16} color={colors.brand} />
          <Text style={styles.adminBtnText}>Top</Text>
        </Pressable>
        {user?.is_admin ? (
          <Pressable
            testID="admin-link-btn"
            style={styles.adminBtn}
            onPress={() => router.push("/admin")}
          >
            <Ionicons name="construct" size={16} color={colors.brand} />
            <Text style={styles.adminBtnText}>Admin</Text>
          </Pressable>
        ) : null}
        <Text style={styles.hint} numberOfLines={1}>Tap · Pinch · Pan</Text>
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
              <CoverView pixel={selected} style={styles.sheetCover} />
              <View style={{ padding: spacing.lg, gap: spacing.sm }}>
                <Text style={[styles.sheetCoord, { color: colors.gold }]}>
                  UNIVERSO #{selected.number}
                </Text>
                <Text style={styles.sheetTitle}>{selected.name}</Text>
                <Text style={styles.sheetCoord}>
                  X {selected.x} · Y {selected.y}
                </Text>
                <Text style={styles.sheetDesc}>{selected.description}</Text>

                <View style={styles.row}>
                  <Text style={styles.rowLabel}>{selected.owner_id ? "Fundador" : "Status"}</Text>
                  <Text style={styles.rowValue}>
                    {selected.owner_name || "Disponível"}
                  </Text>
                </View>
                <View style={styles.row}>
                  <Text style={styles.rowLabel}>
                    {selected.listed_price ? "Revenda" : "Preço"}
                  </Text>
                  <Text style={styles.rowValue}>
                    <Ionicons name="diamond" size={14} color={selected.listed_price ? colors.gold : colors.brand} />{" "}
                    {selected.listed_price || selected.price}
                  </Text>
                </View>
                {selected.purchased_at ? (
                  <View style={styles.row}>
                    <Text style={styles.rowLabel}>Criado em</Text>
                    <Text style={styles.rowValue}>
                      {new Date(selected.purchased_at).toLocaleDateString("pt-BR")}
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
                        Comprar Universo · {selected.price}
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
                    <Text style={styles.secondaryBtnText}>
                      {selected.listed_price && selected.owner_id !== user?.user_id
                        ? `Comprar · ${selected.listed_price} coins`
                        : "Visitar Universo"}
                    </Text>
                  </Pressable>
                )}
              </View>
            </ScrollView>
          </View>
        </View>
      ) : null}
      {/* Celebration sweep — light beam across screen after a successful buy */}
      {celebrate ? (
        <View pointerEvents="none" style={[StyleSheet.absoluteFill, { alignItems: "center", justifyContent: "center", zIndex: 8 }]}>
          <Animated.View
            style={[
              {
                position: "absolute",
                width: 80,
                height: SCREEN_H,
                backgroundColor: colors.gold,
                opacity: 0.4,
              },
              sweepStyle,
            ]}
          />
          <View style={styles.celebrateCard}>
            <Text style={styles.celebrateEmoji}>🌌</Text>
            <Text style={styles.celebrateTitle}>Parabéns!</Text>
            <Text style={styles.celebrateBody}>
              Você acaba de fundar um novo universo.{"\n"}Agora este espaço faz parte do Multiverso PixelLand.
            </Text>
          </View>
        </View>
      ) : null}

      {/* Post-buy wizard: name + cover + description */}
      {wizard ? (
        <WizardModal
          pixel={wizard}
          onClose={() => setWizard(null)}
          onSaved={(p) => {
            setPixels((prev) => prev.map((x) => (x.pixel_id === p.pixel_id ? p : x)));
            setWizard(null);
          }}
        />
      ) : null}
    </View>
  );
}

function WizardModal({
  pixel,
  onClose,
  onSaved,
}: {
  pixel: Pixel;
  onClose: () => void;
  onSaved: (p: Pixel) => void;
}) {
  const [name, setName] = useState(`Universo #${pixel.number}`);
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const onSave = async () => {
    try {
      setSaving(true);
      const updated = await api.updatePixel(pixel.pixel_id, {
        name: name.trim() || `Universo #${pixel.number}`,
        description,
      });
      onSaved(updated);
    } catch (e: any) {
      setErr(e?.message || "Falha ao salvar");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal visible animationType="slide" transparent onRequestClose={onClose}>
      <KeyboardAvoidingView
        style={styles.wizWrap}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <Pressable style={styles.wizBackdrop} onPress={onClose} />
        <View style={styles.wizSheet} testID="post-buy-wizard">
          <View style={styles.wizHandle} />
          <ScrollView contentContainerStyle={{ gap: spacing.md, paddingVertical: spacing.md }}>
            <Text style={styles.wizGold}>UNIVERSO #{pixel.number}</Text>
            <Text style={styles.wizTitle}>Personalize seu universo</Text>
            <Text style={styles.wizSub}>Dê uma identidade ao novo território. Você pode editar depois — inclusive escolher capa em foto ou vídeo na Galeria de Mídia.</Text>

            <Text style={styles.wizLabel}>Nome do Universo</Text>
            <TextInput
              testID="wiz-name"
              style={styles.wizInput}
              value={name}
              onChangeText={setName}
              placeholder="Ex.: Nebulosa Aurora"
              placeholderTextColor={colors.onSurfaceTertiary}
            />

            <Text style={styles.wizLabel}>Descrição</Text>
            <TextInput
              testID="wiz-desc"
              style={[styles.wizInput, { minHeight: 90, textAlignVertical: "top" }]}
              value={description}
              onChangeText={setDescription}
              placeholder="Conte a história do seu universo..."
              placeholderTextColor={colors.onSurfaceTertiary}
              multiline
            />

            {err ? <Text style={{ color: colors.error }}>{err}</Text> : null}
            <Pressable
              testID="wiz-save"
              style={[styles.wizPrimary, saving && { opacity: 0.6 }]}
              onPress={onSave}
              disabled={saving}
            >
              {saving ? (
                <ActivityIndicator color={colors.onBrand} />
              ) : (
                <Text style={styles.wizPrimaryText}>Salvar e continuar</Text>
              )}
            </Pressable>
            <Pressable testID="wiz-skip" onPress={onClose}>
              <Text style={styles.wizSkip}>Pular por enquanto</Text>
            </Pressable>
          </ScrollView>
        </View>
      </KeyboardAvoidingView>
    </Modal>
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
  // Celebration
  celebrateCard: {
    backgroundColor: colors.surfaceSecondary,
    borderColor: colors.gold,
    borderWidth: 1,
    borderRadius: radius.lg,
    padding: spacing.xl,
    marginHorizontal: spacing.xl,
    alignItems: "center",
    gap: spacing.sm,
  },
  celebrateEmoji: { fontSize: 56 },
  celebrateTitle: { color: colors.gold, fontSize: 22, fontWeight: "800", letterSpacing: 2 },
  celebrateBody: {
    color: colors.onSurfaceSecondary,
    fontSize: 13,
    textAlign: "center",
    lineHeight: 20,
  },
  // Wizard
  wizWrap: { flex: 1, justifyContent: "flex-end" },
  wizBackdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "#000000AA" },
  wizSheet: {
    backgroundColor: colors.surfaceSecondary,
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    padding: spacing.lg,
    maxHeight: "85%",
    borderTopColor: colors.gold,
    borderTopWidth: 1,
  },
  wizHandle: {
    alignSelf: "center",
    width: 40,
    height: 4,
    backgroundColor: colors.borderStrong,
    borderRadius: 2,
    marginBottom: spacing.sm,
  },
  wizGold: { color: colors.gold, fontSize: 11, letterSpacing: 3, fontWeight: "700" },
  wizTitle: { color: colors.onSurface, fontSize: 22, fontWeight: "800" },
  wizSub: { color: colors.onSurfaceSecondary, fontSize: 13, lineHeight: 18 },
  wizLabel: { color: colors.onSurfaceTertiary, fontSize: 11, letterSpacing: 2, marginTop: spacing.sm },
  wizInput: {
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
    color: colors.onSurface,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderRadius: radius.md,
    fontSize: 15,
  },
  wizPrimary: {
    backgroundColor: colors.brand,
    paddingVertical: spacing.lg,
    borderRadius: radius.pill,
    alignItems: "center",
    marginTop: spacing.lg,
  },
  wizPrimaryText: { color: colors.onBrand, fontWeight: "700", letterSpacing: 1 },
  wizSkip: {
    color: colors.onSurfaceTertiary,
    textAlign: "center",
    marginTop: spacing.md,
    fontSize: 13,
  },
});
