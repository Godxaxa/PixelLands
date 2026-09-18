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
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import * as Haptics from "expo-haptics";
import * as ImagePicker from "expo-image-picker";

import { api, Media, Pixel, Transaction, uploadMedia } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { GalleryViewer, LoadingThumb, MediaThumb } from "@/src/components/Gallery";
import { CoverPicker, CoverView } from "@/src/components/Cover";
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
  const [externalLink, setExternalLink] = useState("");
  const [themeColor, setThemeColor] = useState(colors.brand);

  // Media gallery (Cloudinary-backed)
  const [media, setMedia] = useState<Media[]>([]);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [viewerIdx, setViewerIdx] = useState<number | null>(null);
  const [mediaMsg, setMediaMsg] = useState<string | null>(null);
  const [coverPickerOpen, setCoverPickerOpen] = useState(false);
  const [aiBusy, setAiBusy] = useState<"desc" | "cover" | null>(null);
  const [aiHint, setAiHint] = useState("");
  const [aiCoverPrompt, setAiCoverPrompt] = useState("");

  // marketplace
  const [listPriceInput, setListPriceInput] = useState("");
  const [marketBusy, setMarketBusy] = useState(false);

  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      setLoading(true);
      const [p, t, m] = await Promise.all([
        api.getPixel(id),
        api.pixelTransactions(id),
        api.listMedia(id),
      ]);
      setPixel(p);
      setName(p.name);
      setDescription(p.description || "");
      setExternalLink(p.external_link || "");
      setThemeColor(p.theme_color || colors.brand);
      setListPriceInput(p.listed_price ? String(p.listed_price) : String(p.price));
      setTxs(t);
      setMedia(m);
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
        external_link: externalLink,
        theme_color: themeColor,
      });
      setPixel(updated);
      setEditing(false);
    } catch (e: any) {
      setErr(e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const onPickCover = async (media_id: string | null) => {
    if (!pixel) return;
    try {
      const updated = await api.updatePixel(pixel.pixel_id, {
        cover_media_id: media_id === null ? "" : media_id,
      });
      setPixel(updated);
      setCoverPickerOpen(false);
    } catch (e: any) {
      setMediaMsg(e?.message || "Falha ao trocar capa");
    }
  };

  const generateDescription = async () => {
    if (!pixel) return;
    try {
      setAiBusy("desc");
      const r = await api.aiPixelDescription(pixel.pixel_id, aiHint, name);
      setDescription(r.description);
      Haptics.selectionAsync().catch(() => {});
    } catch (e: any) {
      setErr(e?.message || "Falha na IA");
    } finally {
      setAiBusy(null);
    }
  };

  const generateCover = async () => {
    if (!pixel) return;
    if (!aiCoverPrompt.trim()) return;
    try {
      setAiBusy("cover");
      setMediaMsg(null);
      const updated = await api.aiCover(pixel.pixel_id, aiCoverPrompt.trim());
      setPixel(updated);
      const m = await api.listMedia(pixel.pixel_id);
      setMedia(m);
      setAiCoverPrompt("");
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
      setMediaMsg("Capa gerada por IA ✨");
      setTimeout(() => setMediaMsg(null), 3000);
    } catch (e: any) {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error).catch(() => {});
      setMediaMsg(e?.message || "Falha ao gerar capa");
    } finally {
      setAiBusy(null);
    }
  };

  const pickAndUpload = async (kind: "image" | "video") => {
    if (!pixel) return;
    if (media.length >= 20) {
      setMediaMsg("Limite atingido (20 arquivos)");
      return;
    }
    try {
      const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!perm.granted) {
        setMediaMsg("Permissão de galeria negada");
        return;
      }
      const res = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: kind === "video" ? ["videos"] : ["images"],
        allowsEditing: false,
        quality: 1,
        videoMaxDuration: 300,
      });
      if (res.canceled) return;
      const asset = res.assets[0];
      const fallbackName =
        asset.fileName ||
        `upload_${Date.now()}.${(asset.mimeType || (kind === "video" ? "video/mp4" : "image/jpeg")).split("/")[1] || (kind === "video" ? "mp4" : "jpg")}`;
      setUploadProgress(0);
      setMediaMsg(null);
      const uploaded = await uploadMedia(
        pixel.pixel_id,
        {
          uri: asset.uri,
          name: fallbackName,
          type: asset.mimeType || (kind === "video" ? "video/mp4" : "image/jpeg"),
          file: (asset as any).file, // web
        },
        (pct) => setUploadProgress(pct),
      );
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
      setMedia((prev) => [uploaded, ...prev]);
      setMediaMsg("Upload concluído ✓");
      setTimeout(() => setMediaMsg(null), 2500);
    } catch (e: any) {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error).catch(() => {});
      setMediaMsg(e?.message || "Falha no upload");
    } finally {
      setUploadProgress(null);
    }
  };

  const removeMedia = async (m: Media) => {
    if (!pixel) return;
    try {
      await api.deleteMedia(pixel.pixel_id, m.media_id);
      setMedia((prev) => prev.filter((x) => x.media_id !== m.media_id));
    } catch (e: any) {
      setMediaMsg(e?.message || "Falha ao excluir");
    }
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
          <CoverView pixel={pixel} style={styles.cover} />
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
            <>
              <Pressable
                testID="edit-btn"
                style={[styles.iconBtn, { top: insets.top + spacing.sm, right: spacing.lg }]}
                onPress={() => setEditing((v) => !v)}
              >
                <Ionicons name={editing ? "close" : "pencil"} size={18} color={colors.onSurface} />
              </Pressable>
              <Pressable
                testID="change-cover-btn"
                style={[styles.coverEditBtn, { top: insets.top + spacing.sm + 46, right: spacing.lg }]}
                onPress={() => setCoverPickerOpen(true)}
              >
                <Ionicons name="images" size={14} color={colors.onSurface} />
                <Text style={styles.coverEditText}>Trocar capa</Text>
              </Pressable>
            </>
          ) : null}
          <View style={styles.coverInfo}>
            <Text style={[styles.coord, { color: colors.gold }]} testID="pixel-coord">
              UNIVERSO #{pixel.number}
            </Text>
            <Text style={styles.title} numberOfLines={2} testID="pixel-title">{pixel.name}</Text>
          </View>
        </View>

        <View style={{ padding: spacing.lg, gap: spacing.md }}>
          <View style={styles.row}>
            <Text style={styles.rowLabel}>Fundador</Text>
            <Text style={styles.rowValue} testID="pixel-owner">
              {pixel.owner_name || "Sem dono"}
            </Text>
          </View>
          <View style={styles.row}>
            <Text style={styles.rowLabel}>Preço de mint</Text>
            <Text style={styles.rowValue}>
              <Ionicons name="diamond" size={14} color={accent} /> {pixel.price}
            </Text>
          </View>
          {pixel.purchased_at ? (
            <View style={styles.row}>
              <Text style={styles.rowLabel}>Criado em</Text>
              <Text style={styles.rowValue}>
                {new Date(pixel.purchased_at).toLocaleString("pt-BR")}
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

          {/* Media Gallery */}
          <View style={styles.galleryHeader}>
            <Text style={styles.sectionLabel}>GALERIA DE MÍDIA</Text>
            <Text style={styles.galleryCount}>{media.length}/20</Text>
          </View>
          {isOwner ? (
            <View style={styles.galleryActions}>
              <Pressable
                testID="add-photo-btn"
                style={[styles.mediaBtn, { borderColor: accent }, uploadProgress !== null && { opacity: 0.5 }]}
                onPress={() => pickAndUpload("image")}
                disabled={uploadProgress !== null}
              >
                <Ionicons name="image" size={16} color={accent} />
                <Text style={[styles.mediaBtnText, { color: accent }]}>Adicionar Foto</Text>
              </Pressable>
              <Pressable
                testID="add-video-btn"
                style={[styles.mediaBtn, { borderColor: accent }, uploadProgress !== null && { opacity: 0.5 }]}
                onPress={() => pickAndUpload("video")}
                disabled={uploadProgress !== null}
              >
                <Ionicons name="videocam" size={16} color={accent} />
                <Text style={[styles.mediaBtnText, { color: accent }]}>Adicionar Vídeo</Text>
              </Pressable>
            </View>
          ) : null}
          {mediaMsg ? (
            <Text style={styles.mediaMsg} testID="media-msg">
              {mediaMsg}
            </Text>
          ) : null}
          {media.length === 0 && uploadProgress === null ? (
            <Text style={styles.empty}>Nenhuma mídia ainda</Text>
          ) : (
            <FlatList
              horizontal
              data={media}
              keyExtractor={(m) => m.media_id}
              showsHorizontalScrollIndicator={false}
              contentContainerStyle={{ gap: spacing.sm }}
              ListHeaderComponent={
                uploadProgress !== null ? (
                  <View style={{ marginRight: spacing.sm }}>
                    <LoadingThumb progress={uploadProgress} />
                  </View>
                ) : null
              }
              renderItem={({ item, index }) => (
                <MediaThumb
                  media={item}
                  onPress={() => setViewerIdx(index)}
                  onDelete={() => removeMedia(item)}
                  editable={!!isOwner}
                />
              )}
            />
          )}

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
                placeholder="Nome do universo"
                placeholderTextColor={colors.onSurfaceTertiary}
              />
              <TextInput
                testID="edit-description"
                style={[styles.input, { minHeight: 100, textAlignVertical: "top" }]}
                value={description}
                onChangeText={setDescription}
                placeholder="Descreva seu universo"
                placeholderTextColor={colors.onSurfaceTertiary}
                multiline
              />
              <View style={styles.aiRow}>
                <TextInput
                  testID="ai-hint-input"
                  style={[styles.input, { flex: 1 }]}
                  value={aiHint}
                  onChangeText={setAiHint}
                  placeholder="Dica de estilo (opcional)"
                  placeholderTextColor={colors.onSurfaceTertiary}
                />
                <Pressable
                  testID="ai-desc-btn"
                  style={[styles.aiBtn, aiBusy === "desc" && { opacity: 0.6 }]}
                  onPress={generateDescription}
                  disabled={aiBusy !== null}
                >
                  {aiBusy === "desc" ? (
                    <ActivityIndicator color={colors.onBrand} />
                  ) : (
                    <>
                      <Ionicons name="sparkles" size={14} color={colors.onBrand} />
                      <Text style={styles.aiBtnText}>IA</Text>
                    </>
                  )}
                </Pressable>
              </View>

              <Text style={styles.subLabel}>Gerar capa com IA</Text>
              <View style={styles.aiRow}>
                <TextInput
                  testID="ai-cover-input"
                  style={[styles.input, { flex: 1 }]}
                  value={aiCoverPrompt}
                  onChangeText={setAiCoverPrompt}
                  placeholder="Ex.: nebulosa violeta ao amanhecer"
                  placeholderTextColor={colors.onSurfaceTertiary}
                />
                <Pressable
                  testID="ai-cover-btn"
                  style={[styles.aiBtn, aiBusy === "cover" && { opacity: 0.6 }]}
                  onPress={generateCover}
                  disabled={aiBusy !== null || !aiCoverPrompt.trim()}
                >
                  {aiBusy === "cover" ? (
                    <ActivityIndicator color={colors.onBrand} />
                  ) : (
                    <>
                      <Ionicons name="sparkles" size={14} color={colors.onBrand} />
                      <Text style={styles.aiBtnText}>Gerar</Text>
                    </>
                  )}
                </Pressable>
              </View>
              <TextInput
                testID="edit-external-link"
                style={styles.input}
                value={externalLink}
                onChangeText={setExternalLink}
                placeholder="Link externo (https://...)"
                placeholderTextColor={colors.onSurfaceTertiary}
                autoCapitalize="none"
                keyboardType="url"
              />

              <Text style={styles.subLabel}>Cor do tema da página</Text>
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

      {viewerIdx !== null ? (
        <GalleryViewer
          visible
          media={media}
          startIndex={viewerIdx}
          onClose={() => setViewerIdx(null)}
        />
      ) : null}

      <CoverPicker
        visible={coverPickerOpen}
        media={media}
        selectedId={pixel.cover_media_id}
        onSelect={onPickCover}
        onClose={() => setCoverPickerOpen(false)}
      />
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
  coverEditBtn: {
    position: "absolute",
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: spacing.sm,
    paddingVertical: 6,
    borderRadius: radius.pill,
    backgroundColor: colors.surfaceSecondary + "DD",
    borderColor: colors.border,
    borderWidth: 1,
  },
  coverEditText: {
    color: colors.onSurface,
    fontSize: 11,
    letterSpacing: 0.5,
    fontWeight: "600",
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
  galleryHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginTop: spacing.sm,
  },
  galleryCount: { color: colors.onSurfaceTertiary, fontSize: 11, letterSpacing: 1 },
  galleryActions: { flexDirection: "row", gap: spacing.sm },
  mediaBtn: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.xs,
    borderWidth: 1,
    paddingVertical: spacing.md,
    borderRadius: radius.pill,
    backgroundColor: colors.surfaceSecondary,
  },
  mediaBtnText: { fontSize: 13, fontWeight: "600", letterSpacing: 0.5 },
  mediaMsg: { color: colors.onSurfaceSecondary, fontSize: 12, fontStyle: "italic" },
  empty: { color: colors.onSurfaceTertiary, fontSize: 12, fontStyle: "italic" },
  aiRow: { flexDirection: "row", gap: spacing.sm, alignItems: "center" },
  aiBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: colors.gold,
    paddingHorizontal: spacing.md,
    paddingVertical: 10,
    borderRadius: radius.pill,
    minWidth: 64,
    justifyContent: "center",
  },
  aiBtnText: { color: colors.onBrand, fontSize: 12, fontWeight: "700", letterSpacing: 1 },
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
