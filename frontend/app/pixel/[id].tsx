import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
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

import { api, Pixel } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing } from "@/src/theme";

export default function PixelDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { user } = useAuth();
  const insets = useSafeAreaInsets();
  const [pixel, setPixel] = useState<Pixel | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [cover, setCover] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      setLoading(true);
      const p = await api.getPixel(id);
      setPixel(p);
      setName(p.name);
      setDescription(p.description || "");
      setCover(p.cover_image || "");
    } catch (e: any) {
      setErr(e?.message || "Failed");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  const isOwner = pixel?.owner_id === user?.user_id;

  const onSave = async () => {
    if (!pixel) return;
    try {
      setSaving(true);
      setErr(null);
      const updated = await api.updatePixel(pixel.pixel_id, {
        name,
        description,
        cover_image: cover,
      });
      setPixel(updated);
      setEditing(false);
    } catch (e: any) {
      setErr(e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  if (loading || !pixel) {
    return (
      <View style={styles.center} testID="pixel-loading">
        <ActivityIndicator color={colors.brand} />
      </View>
    );
  }

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
      testID="pixel-detail-screen"
    >
      <ScrollView contentContainerStyle={{ paddingBottom: insets.bottom + spacing.xl }}>
        <View style={styles.coverWrap}>
          <Image source={{ uri: pixel.cover_image }} style={styles.cover} contentFit="cover" />
          <View style={styles.coverScrim} />
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
              <Ionicons
                name={editing ? "close" : "pencil"}
                size={18}
                color={colors.onSurface}
              />
            </Pressable>
          ) : null}
          <View style={styles.coverInfo}>
            <Text style={styles.coord} testID="pixel-coord">X {pixel.x} · Y {pixel.y}</Text>
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
            <Text style={styles.rowLabel}>Price</Text>
            <Text style={styles.rowValue}>
              <Ionicons name="diamond" size={14} color={colors.brand} /> {pixel.price}
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

          <Text style={styles.sectionLabel}>DESCRIPTION</Text>
          <Text style={styles.desc}>{pixel.description}</Text>

          {editing && isOwner ? (
            <View style={{ gap: spacing.md, marginTop: spacing.md }}>
              <Text style={styles.sectionLabel}>EDIT</Text>
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
              {err ? <Text style={styles.error}>{err}</Text> : null}
              <Pressable
                testID="save-btn"
                style={styles.primaryBtn}
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
  coverScrim: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: "rgba(15,17,21,0.55)",
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
  coord: { color: colors.brand, fontSize: 12, letterSpacing: 2 },
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
  sectionLabel: { color: colors.onSurfaceTertiary, fontSize: 11, letterSpacing: 2 },
  desc: { color: colors.onSurfaceSecondary, fontSize: 14, lineHeight: 22 },
  input: {
    backgroundColor: colors.surfaceSecondary,
    borderColor: colors.border,
    borderWidth: 1,
    color: colors.onSurface,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderRadius: radius.md,
    fontSize: 15,
  },
  primaryBtn: {
    backgroundColor: colors.brand,
    paddingVertical: spacing.lg,
    borderRadius: radius.pill,
    alignItems: "center",
  },
  primaryBtnText: { color: colors.onBrand, fontWeight: "700", letterSpacing: 1 },
  error: { color: colors.error },
});
