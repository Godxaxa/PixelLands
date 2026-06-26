import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { Image } from "expo-image";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, Pixel } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing } from "@/src/theme";

export default function ProfileScreen() {
  const { user, logout } = useAuth();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const [mine, setMine] = useState<Pixel[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const list = await api.myPixels();
      setMine(list);
    } catch {
      setMine([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <View style={[styles.container, { paddingTop: insets.top }]} testID="profile-screen">
      <View style={styles.header}>
        <Pressable testID="back-btn" onPress={() => router.back()} style={styles.iconBtn}>
          <Ionicons name="chevron-back" size={20} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.headerTitle}>Profile</Text>
        <Pressable testID="profile-logout" onPress={logout} style={styles.iconBtn}>
          <Ionicons name="log-out-outline" size={20} color={colors.onSurface} />
        </Pressable>
      </View>

      <View style={styles.card}>
        {user?.picture ? (
          <Image source={{ uri: user.picture }} style={styles.avatar} />
        ) : (
          <View style={[styles.avatar, styles.avatarFallback]}>
            <Ionicons name="person" size={36} color={colors.onSurface} />
          </View>
        )}
        <Text style={styles.name} testID="profile-name">{user?.name || "Pixel Owner"}</Text>
        <Text style={styles.email}>{user?.email}</Text>

        <View style={styles.stats}>
          <View style={styles.statBox}>
            <Text style={styles.statNum} testID="stat-coins">{user?.coins ?? 0}</Text>
            <Text style={styles.statLabel}>Pixel Coins</Text>
          </View>
          <View style={styles.statBox}>
            <Text style={styles.statNum} testID="stat-pixels">{user?.pixels_owned ?? 0}</Text>
            <Text style={styles.statLabel}>Pixels</Text>
          </View>
        </View>
      </View>

      <Text style={styles.sectionLabel}>YOUR TERRITORIES</Text>

      {loading ? (
        <ActivityIndicator color={colors.brand} style={{ marginTop: spacing.xl }} />
      ) : mine.length === 0 ? (
        <View style={styles.empty} testID="empty-pixels">
          <Ionicons name="grid-outline" size={48} color={colors.onSurfaceTertiary} />
          <Text style={styles.emptyText}>No pixels owned yet</Text>
          <Pressable
            testID="goto-map-btn"
            style={styles.primaryBtn}
            onPress={() => router.push("/map")}
          >
            <Text style={styles.primaryBtnText}>Browse Map</Text>
          </Pressable>
        </View>
      ) : (
        <FlatList
          data={mine}
          keyExtractor={(p) => p.pixel_id}
          numColumns={2}
          contentContainerStyle={{ padding: spacing.lg, gap: spacing.md }}
          columnWrapperStyle={{ gap: spacing.md }}
          renderItem={({ item }) => (
            <Pressable
              testID={`my-pixel-${item.pixel_id}`}
              style={styles.gridItem}
              onPress={() => router.push(`/pixel/${item.pixel_id}`)}
            >
              <Image source={{ uri: item.cover_image }} style={styles.gridImg} />
              <View style={styles.gridInfo}>
                <Text style={styles.gridName} numberOfLines={1}>{item.name}</Text>
                <Text style={styles.gridCoord}>({item.x},{item.y})</Text>
              </View>
            </Pressable>
          )}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
  },
  iconBtn: {
    width: 36,
    height: 36,
    borderRadius: radius.pill,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.surfaceSecondary,
  },
  headerTitle: { color: colors.onSurface, fontSize: 16, fontWeight: "700", letterSpacing: 1 },
  card: {
    backgroundColor: colors.surfaceSecondary,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.lg,
    padding: spacing.xl,
    margin: spacing.lg,
    alignItems: "center",
    gap: spacing.sm,
  },
  avatar: {
    width: 80,
    height: 80,
    borderRadius: 40,
    backgroundColor: colors.surfaceTertiary,
    borderWidth: 2,
    borderColor: colors.brand,
  },
  avatarFallback: { alignItems: "center", justifyContent: "center" },
  name: { color: colors.onSurface, fontSize: 22, fontWeight: "700" },
  email: { color: colors.onSurfaceSecondary, fontSize: 13 },
  stats: { flexDirection: "row", gap: spacing.lg, marginTop: spacing.lg },
  statBox: {
    flex: 1,
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.md,
    padding: spacing.lg,
    alignItems: "center",
    gap: spacing.xs,
  },
  statNum: { color: colors.brand, fontSize: 28, fontWeight: "800" },
  statLabel: { color: colors.onSurfaceTertiary, fontSize: 11, letterSpacing: 1 },
  sectionLabel: {
    color: colors.onSurfaceTertiary,
    fontSize: 11,
    letterSpacing: 2,
    paddingHorizontal: spacing.lg,
    marginTop: spacing.sm,
  },
  empty: { alignItems: "center", marginTop: spacing.xxl, gap: spacing.md },
  emptyText: { color: colors.onSurfaceSecondary, fontSize: 14 },
  primaryBtn: {
    backgroundColor: colors.brand,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.xl,
    borderRadius: radius.pill,
    marginTop: spacing.md,
  },
  primaryBtnText: { color: colors.onBrand, fontWeight: "700", letterSpacing: 1 },
  gridItem: {
    flex: 1,
    backgroundColor: colors.surfaceSecondary,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.md,
    overflow: "hidden",
  },
  gridImg: { width: "100%", height: 100, backgroundColor: "#000" },
  gridInfo: { padding: spacing.sm },
  gridName: { color: colors.onSurface, fontSize: 13, fontWeight: "600" },
  gridCoord: { color: colors.brand, fontSize: 11, letterSpacing: 1 },
});
