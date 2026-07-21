import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  KeyboardAvoidingView,
  Linking,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { Image } from "expo-image";
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import * as Haptics from "expo-haptics";

import { api, Pixel, Transaction } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing } from "@/src/theme";

const THEMES = ["#00E5FF", "#FF6B6B", "#FFD93D", "#6BCB77", "#A66CFF", "#FF9F1C"];

export default function PixelDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { user, refresh } = useAuth();
  const insets = useSafeAreaInsets();
  const [pixel, setPixel] = useState<Pixel | null>(null);
  const [txs, setTxs] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);

  // editable fields
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [cover, setCover] = useState("");
  const [externalLink, setExternalLink] = useState("");
  const [themeColor, setThemeColor] = useState(colors.brand);
  const [galleryInput, setGalleryInput] = useState("");
  const [gallery, setGallery] = useState<string[]>([]);

  // marketplace
  const [listPriceInput, setListPriceInput] = useState("");
  const [marketBusy, setMarketBusy] = useState(false);

  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      setLoading(true);
      const [p, t] = await Promise.all([api.getPixel(id), api.pixelTransactions(id)]);
      setPixel(p);
      setName(p.name);
      setDescription(p.description || "");
      setCover(p.cover_image || "");
      setExternalLink(p.external_link || "");
      setThemeColor(p.theme_color || colors.brand);
      setGallery(p.gallery || []);
      setListPriceInput(p.listed_price ? String(p.listed_price) : String(p.price));
      setTxs(t);
    } catch (e: any) {
      setErr(e?.message || "Failed");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  const isOwner = pixel?.owner_id === user?.user_id;
  const accent = themeColor || colors.brand;

  const onSave = async () => {
    if (!pixel) return;
    try {
      setSaving(true);
      setErr(null);
      const updated = await api.updatePixel(pixel.pixel_id, {
        name,
        description,
        cover_image: cover,
        external_link: externalLink,
        theme_color: themeColor,
        gallery,
      });
      setPixel(updated);
      setEditing(false);
    } catch (e: any) {
      setErr(e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const addToGallery = () => {
    const url = galleryInput.trim();
    if (!url) return;
    setGallery((g) => [...g, url]);
    setGalleryInput("");
  };
  const removeFromGallery = (idx: number) => {
    setGallery((g) => g.filter((_, i) => i !== idx));
  };

  const onList = async () => {
    if (!pixel) return;
    const price = parseInt(listPriceInput, 10);
    if (!price || price <= 0) {
      setErr("Enter a valid price");
      return;
    }
    try {
      setMarketBusy(true);
      setErr(null);
      const updated = await api.listForSale(pixel.pixel_id, price);
      setPixel(updated);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
    } catch (e: any) {
      setErr(e?.message || "List failed");
    } finally {
      setMarketBusy(false);
    }
  };

  const onUnlist = async () => {
    if (!pixel) return;
    try {
      setMarketBusy(true);
      const updated = await api.unlist(pixel.pixel_id);
      setPixel(updated);
    } catch (e: any) {
      setErr(e?.message || "Unlist failed");
    } finally {
      setMarketBusy(false);
    }
  };

  const onBuyResale = async () => {
    if (!pixel) return;
    try {
      setMarketBusy(true);
      setErr(null);
      const updated = await api.buyResale(pixel.pixel_id);
      setPixel(updated);
      const t = await api.pixelTransactions(pixel.pixel_id);
      setTxs(t);
      await refresh();
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
    } catch (e: any) {
      setErr(e?.message || "Buy failed");
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error).catch(() => {});
    } finally {
      setMarketBusy(false);
    }
  };

  if (loading || !pixel) {
    return (
      <View style={styles.center} testID="pixel-loading">
        <ActivityIndicator color={colors.brand} />
      </View>
    );
  }

  const fee = pixel.listed_price ? Math.floor(pixel.listed_price * 0.1) : 0;

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
      testID="pixel-detail-screen"
    >
      <ScrollView contentContainerStyle={{ paddingBottom: insets.bottom + spacing.xl }}>
        <View style={styles.coverWrap}>
          <Image source={{ uri: pixel.cover_image }} style={styles.cover} contentFit="cover" />
          <View style={[styles.coverScrim, { backgroundColor: `${accent}33` }]} />
          <View style={styles.coverScrimDark} />
          <Pressable
            testID="back-btn"
            style={[styles.iconBtn, { top: insets.top + spacing.sm, left: spacing.lg }]}
            onPress={() => router.back()}
          >
            <Ionicons name="chevron-back" size={20} color={colors.onSurface} />
          </Pressable>
          {isOwner ? (
            <Pressable
              testID="edit-btn"
              style={[styles.iconBtn, { top: insets.top + spacing.sm, right: spacing.lg }]}
              onPress={() => setEditing((v) => !v)}
            >
              <Ionicons name={editing ? "close" : "pencil"} size={18} color={colors.onSurface} />
            </Pressable>
          ) : null}
          <View style={styles.coverInfo}>
            <Text style={[styles.coord, { color: accent }]} testID="pixel-coord">
              X {pixel.x} · Y {pixel.y}
            </Text>
            <Text style={styles.title} numberOfLines={2} testID="pixel-title">{pixel.name}</Text>
          </View>
        </View>

        <View style={{ padding: spacing.lg, gap: spacing.md }}>
          <View style={styles.row}>
            <Text style={styles.rowLabel}>Owner</Text>
            <Text style={styles.rowValue} testID="pixel-owner">
              {pixel.owner_name || "Unclaimed"}
            </Text>
          </View>
          <View style={styles.row}>
            <Text style={styles.rowLabel}>Mint Price</Text>
            <Text style={styles.rowValue}>
              <Ionicons name="diamond" size={14} color={accent} /> {pixel.price}
            </Text>
          </View>
          {pixel.purchased_at ? (
            <View style={styles.row}>
              <Text style={styles.rowLabel}>Purchased</Text>
              <Text style={styles.rowValue}>
                {new Date(pixel.purchased_at).toLocaleString()}
              </Text>
            </View>
          ) : null}

          {pixel.external_link ? (
            <Pressable
              testID="external-link-btn"
              style={[styles.linkBox, { borderColor: accent }]}
              onPress={() => {
                const u = String(pixel.external_link || "").trim();
                if (/^https?:\/\//i.test(u)) {
                  Linking.openURL(u).catch(() => {});
                }
              }}
            >
              <Ionicons name="link" size={16} color={accent} />
              <Text style={[styles.linkText, { color: accent }]} numberOfLines={1}>
                {pixel.external_link}
              </Text>
            </Pressable>
          ) : null}

          {pixel.description ? (
            <>
              <Text style={styles.sectionLabel}>DESCRIPTION</Text>
              <Text style={styles.desc}>{pixel.description}</Text>
            </>
          ) : null}

          {/* Gallery */}
          {gallery.length > 0 || editing ? (
            <>
              <Text style={styles.sectionLabel}>GALLERY</Text>
              <FlatList
                horizontal
                data={gallery}
                keyExtractor={(u, i) => `${u}-${i}`}
                showsHorizontalScrollIndicator={false}
                contentContainerStyle={{ gap: spacing.sm }}
                ListEmptyComponent={
                  <Text style={styles.empty}>No images yet</Text>
                }
                renderItem={({ item, index }) => (
                  <View style={styles.galleryItem}>
                    <Image source={{ uri: item }} style={styles.galleryImg} contentFit="cover" />
                    {editing ? (
                      <Pressable
                        testID={`gallery-remove-${index}`}
                        style={styles.galleryRemove}
                        onPress={() => removeFromGallery(index)}
                      >
                        <Ionicons name="close" size={14} color={colors.onSurface} />
                      </Pressable>
                    ) : null}
                  </View>
                )}
              />
            </>
          ) : null}

          {/* Marketplace — non-owner sees buy button if listed */}
          {!isOwner && pixel.listed_price && pixel.owner_id ? (
            <View style={[styles.marketCard, { borderColor: accent }]} testID="market-resale-card">
              <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
                <Ionicons name="storefront" size={18} color={accent} />
                <Text style={styles.marketTitle}>For sale on the secondary market</Text>
              </View>
              <Text style={styles.marketPrice}>
                <Ionicons name="diamond" size={18} color={accent} /> {pixel.listed_price}
              </Text>
              <Text style={styles.marketHint}>
                Seller receives {pixel.listed_price - fee} · 10% market fee
              </Text>
              <Pressable
                testID="buy-resale-btn"
                style={[styles.primaryBtn, { backgroundColor: accent }, marketBusy && { opacity: 0.6 }]}
                onPress={onBuyResale}
                disabled={marketBusy}
              >
                {marketBusy ? (
                  <ActivityIndicator color={colors.onBrand} />
                ) : (
                  <Text style={styles.primaryBtnText}>Buy for {pixel.listed_price} coins</Text>
                )}
              </Pressable>
            </View>
          ) : null}

          {/* Marketplace — owner controls */}
          {isOwner ? (
            <View style={styles.marketCard} testID="market-owner-card">
              <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
                <Ionicons name="pricetag" size={16} color={accent} />
                <Text style={styles.marketTitle}>
                  {pixel.listed_price ? "Listed for resale" : "Sell on marketplace"}
                </Text>
              </View>
              {pixel.listed_price ? (
                <>
                  <Text style={styles.marketPrice}>
                    <Ionicons name="diamond" size={16} color={accent} /> {pixel.listed_price}
                  </Text>
                  <Text style={styles.marketHint}>
                    You&apos;d receive {pixel.listed_price - fee} after 10% fee
                  </Text>
                  <Pressable
                    testID="unlist-btn"
                    style={[styles.secondaryBtn, { borderColor: accent }]}
                    onPress={onUnlist}
                    disabled={marketBusy}
                  >
                    <Text style={[styles.secondaryBtnText, { color: accent }]}>
                      {marketBusy ? "..." : "Remove from market"}
                    </Text>
                  </Pressable>
                </>
              ) : (
                <>
                  <TextInput
                    testID="list-price-input"
                    style={styles.input}
                    keyboardType="numeric"
                    value={listPriceInput}
                    onChangeText={setListPriceInput}
                    placeholder="Asking price"
                    placeholderTextColor={colors.onSurfaceTertiary}
                  />
                  <Pressable
                    testID="list-btn"
                    style={[styles.primaryBtn, { backgroundColor: accent }, marketBusy && { opacity: 0.6 }]}
                    onPress={onList}
                    disabled={marketBusy}
                  >
                    {marketBusy ? (
                      <ActivityIndicator color={colors.onBrand} />
                    ) : (
                      <Text style={styles.primaryBtnText}>List for sale</Text>
                    )}
                  </Pressable>
                </>
              )}
            </View>
          ) : null}

          {/* Edit panel */}
          {editing && isOwner ? (
            <View style={styles.editPanel} testID="edit-panel">
              <Text style={styles.sectionLabel}>CUSTOMIZE TERRITORY</Text>
              <TextInput
                testID="edit-name"
                style={styles.input}
                value={name}
                onChangeText={setName}
                placeholder="Land name"
                placeholderTextColor={colors.onSurfaceTertiary}
              />
              <TextInput
                testID="edit-description"
                style={[styles.input, { minHeight: 100, textAlignVertical: "top" }]}
                value={description}
                onChangeText={setDescription}
                placeholder="Describe your universe"
                placeholderTextColor={colors.onSurfaceTertiary}
                multiline
              />
              <TextInput
                testID="edit-cover"
                style={styles.input}
                value={cover}
                onChangeText={setCover}
                placeholder="Cover image URL"
                placeholderTextColor={colors.onSurfaceTertiary}
                autoCapitalize="none"
              />
              <TextInput
                testID="edit-external-link"
                style={styles.input}
                value={externalLink}
                onChangeText={setExternalLink}
                placeholder="External link (https://...)"
                placeholderTextColor={colors.onSurfaceTertiary}
                autoCapitalize="none"
                keyboardType="url"
              />

              <Text style={styles.subLabel}>Page theme color</Text>
              <View style={styles.themeRow}>
                {THEMES.map((t) => (
                  <Pressable
                    key={t}
                    testID={`theme-${t}`}
                    onPress={() => setThemeColor(t)}
                    style={[
                      styles.themeChip,
                      { backgroundColor: t },
                      themeColor === t && styles.themeChipActive,
                    ]}
                  />
                ))}
              </View>

              <Text style={styles.subLabel}>Add image to gallery</Text>
              <View style={{ flexDirection: "row", gap: spacing.sm }}>
                <TextInput
                  testID="gallery-input"
                  style={[styles.input, { flex: 1 }]}
                  value={galleryInput}
                  onChangeText={setGalleryInput}
                  placeholder="Image URL"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  autoCapitalize="none"
                />
                <Pressable
                  testID="gallery-add"
                  style={[styles.addBtn, { backgroundColor: accent }]}
                  onPress={addToGallery}
                >
                  <Ionicons name="add" size={20} color={colors.onBrand} />
                </Pressable>
              </View>

              {err ? <Text style={styles.error}>{err}</Text> : null}
              <Pressable
                testID="save-btn"
                style={[styles.primaryBtn, { backgroundColor: accent }]}
                onPress={onSave}
                disabled={saving}
              >
                {saving ? (
                  <ActivityIndicator color={colors.onBrand} />
                ) : (
                  <Text style={styles.primaryBtnText}>Save Changes</Text>
                )}
              </Pressable>
            </View>
          ) : null}

          {/* Transaction History */}
          <Text style={styles.sectionLabel}>HISTÓRICO DE TRANSAÇÕES</Text>
          {txs.length === 0 ? (
            <Text style={styles.empty}>Nenhuma transação ainda</Text>
          ) : (
            <View style={{ gap: spacing.sm }}>
              {txs.map((t) => (
                <View key={t.tx_id} style={styles.txRow} testID={`tx-${t.tx_id}`}>
                  <View
                    style={[
                      styles.txKind,
                      { backgroundColor: t.kind === "resale" ? `${accent}33` : colors.surfaceTertiary },
                    ]}
                  >
                    <Text style={[styles.txKindText, t.kind === "resale" && { color: accent }]}>
                      {t.kind === "resale" ? "RESALE" : "MINT"}
                    </Text>
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.txBuyer} numberOfLines={1}>
                      {t.seller_name ? `${t.seller_name} → ` : ""}{t.buyer_name}
                    </Text>
                    <Text style={styles.txTime}>{new Date(t.timestamp).toLocaleString()}</Text>
                  </View>
                  <Text style={styles.txPrice}>
                    <Ionicons name="diamond" size={12} color={accent} /> {t.price}
                  </Text>
                </View>
              ))}
            </View>
          )}

          {err && !editing ? <Text style={styles.error}>{err}</Text> : null}
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface },
  coverWrap: { height: 280, backgroundColor: "#000" },
  cover: { ...StyleSheet.absoluteFillObject },
  coverScrim: { ...StyleSheet.absoluteFillObject },
  coverScrimDark: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: "rgba(15,17,21,0.45)",
  },
  iconBtn: {
    position: "absolute",
    width: 38,
    height: 38,
    borderRadius: radius.pill,
    backgroundColor: colors.surfaceSecondary + "DD",
    borderColor: colors.border,
    borderWidth: 1,
    alignItems: "center",
    justifyContent: "center",
  },
  coverInfo: { position: "absolute", bottom: spacing.lg, left: spacing.lg, right: spacing.lg },
  coord: { fontSize: 12, letterSpacing: 2 },
  title: { color: colors.onSurface, fontSize: 28, fontWeight: "800", marginTop: spacing.xs },
  row: {
    flexDirection: "row",
    justifyContent: "space-between",
    paddingVertical: spacing.md,
    borderBottomColor: colors.divider,
    borderBottomWidth: 1,
  },
  rowLabel: { color: colors.onSurfaceTertiary, fontSize: 12, letterSpacing: 1, textTransform: "uppercase" },
  rowValue: { color: colors.onSurface, fontSize: 14, fontWeight: "600" },
  sectionLabel: { color: colors.onSurfaceTertiary, fontSize: 11, letterSpacing: 2, marginTop: spacing.sm },
  subLabel: { color: colors.onSurfaceSecondary, fontSize: 12, letterSpacing: 1, marginTop: spacing.sm },
  desc: { color: colors.onSurfaceSecondary, fontSize: 14, lineHeight: 22 },
  linkBox: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    borderWidth: 1,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    backgroundColor: colors.surfaceSecondary,
  },
  linkText: { fontSize: 13, flex: 1 },
  marketCard: {
    backgroundColor: colors.surfaceSecondary,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.lg,
    padding: spacing.lg,
    gap: spacing.sm,
  },
  marketTitle: { color: colors.onSurface, fontSize: 14, fontWeight: "600" },
  marketPrice: { color: colors.onSurface, fontSize: 26, fontWeight: "800", letterSpacing: 1 },
  marketHint: { color: colors.onSurfaceTertiary, fontSize: 12 },
  primaryBtn: {
    backgroundColor: colors.brand,
    paddingVertical: spacing.md,
    borderRadius: radius.pill,
    alignItems: "center",
    marginTop: spacing.sm,
  },
  primaryBtnText: { color: colors.onBrand, fontWeight: "700", letterSpacing: 1 },
  secondaryBtn: {
    borderColor: colors.brand,
    borderWidth: 1,
    paddingVertical: spacing.md,
    borderRadius: radius.pill,
    alignItems: "center",
    marginTop: spacing.sm,
  },
  secondaryBtnText: { fontWeight: "700", letterSpacing: 1 },
  editPanel: {
    backgroundColor: colors.surfaceSecondary,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.lg,
    padding: spacing.lg,
    gap: spacing.md,
  },
  input: {
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
    color: colors.onSurface,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderRadius: radius.md,
    fontSize: 15,
  },
  themeRow: { flexDirection: "row", gap: spacing.sm, flexWrap: "wrap" },
  themeChip: {
    width: 36,
    height: 36,
    borderRadius: radius.pill,
    borderWidth: 2,
    borderColor: "transparent",
  },
  themeChipActive: { borderColor: colors.onSurface },
  addBtn: {
    width: 48,
    height: 48,
    borderRadius: radius.md,
    alignItems: "center",
    justifyContent: "center",
  },
  galleryItem: {
    width: 120,
    height: 90,
    borderRadius: radius.md,
    overflow: "hidden",
    backgroundColor: colors.surfaceTertiary,
  },
  galleryImg: { width: "100%", height: "100%" },
  galleryRemove: {
    position: "absolute",
    top: 4,
    right: 4,
    width: 22,
    height: 22,
    borderRadius: 11,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "rgba(0,0,0,0.75)",
  },
  empty: { color: colors.onSurfaceTertiary, fontSize: 12, fontStyle: "italic" },
  txRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceSecondary,
    borderColor: colors.border,
    borderWidth: 1,
  },
  txKind: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: radius.sm,
  },
  txKindText: { color: colors.onSurfaceSecondary, fontSize: 10, fontWeight: "800", letterSpacing: 1 },
  txBuyer: { color: colors.onSurface, fontSize: 13, fontWeight: "500" },
  txTime: { color: colors.onSurfaceTertiary, fontSize: 11, marginTop: 2 },
  txPrice: { color: colors.onSurface, fontSize: 13, fontWeight: "700" },
  error: { color: colors.error },
});
