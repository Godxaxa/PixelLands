import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { Image } from "expo-image";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, LeaderboardEntry } from "@/src/api/client";
import { colors, radius, spacing } from "@/src/theme";

const MEDAL = ["#FFD700", "#C0C0C0", "#CD7F32"];

export default function Leaderboard() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const [entries, setEntries] = useState<LeaderboardEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const list = await api.leaderboard();
      setEntries(list);
    } catch {
      setEntries([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <View style={[styles.container, { paddingTop: insets.top }]} testID="leaderboard-screen">
      <View style={styles.header}>
        <Pressable testID="leaderboard-back" onPress={() => router.back()} style={styles.iconBtn}>
          <Ionicons name="chevron-back" size={20} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.title}>LEADERBOARD</Text>
        <View style={{ width: 36 }} />
      </View>

      <Text style={styles.subtitle}>Biggest landlords of PixelLand</Text>

      {loading ? (
        <ActivityIndicator color={colors.brand} style={{ marginTop: spacing.xl }} />
      ) : (
        <FlatList
          data={entries}
          keyExtractor={(e) => e.user_id}
          contentContainerStyle={{ padding: spacing.lg, gap: spacing.sm, paddingBottom: insets.bottom + spacing.xl }}
          refreshControl={
            <RefreshControl
              tintColor={colors.brand}
              refreshing={refreshing}
              onRefresh={() => { setRefreshing(true); load(); }}
            />
          }
          ListEmptyComponent={
            <View style={styles.empty}>
              <Ionicons name="trophy-outline" size={48} color={colors.onSurfaceTertiary} />
              <Text style={styles.emptyText}>No landlords yet</Text>
            </View>
          }
          renderItem={({ item, index }) => {
            const isTop = index < 3;
            return (
              <View
                testID={`leader-${item.user_id}`}
                style={[styles.row, isTop && { borderColor: MEDAL[index] }]}
              >
                <View style={[styles.rank, isTop && { backgroundColor: MEDAL[index] }]}>
                  <Text style={[styles.rankText, isTop && { color: colors.onBrand }]}>
                    {index + 1}
                  </Text>
                </View>
                {item.picture ? (
                  <Image source={{ uri: item.picture }} style={styles.avatar} />
                ) : (
                  <View style={[styles.avatar, styles.avatarFallback]}>
                    <Ionicons name="person" size={18} color={colors.onSurface} />
                  </View>
                )}
                <View style={{ flex: 1 }}>
                  <Text style={styles.name} numberOfLines={1}>
                    {item.name}{item.is_admin ? <Text style={{ color: colors.brand }}> · admin</Text> : null}
                  </Text>
                  <Text style={styles.sub}>
                    {item.pixels_owned} pixels · {item.total_spent} coins spent
                  </Text>
                </View>
                <View style={styles.metric}>
                  <Text style={styles.metricNum}>{item.pixels_owned}</Text>
                  <Text style={styles.metricLabel}>OWNED</Text>
                </View>
              </View>
            );
          }}
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
  title: { color: colors.brand, fontSize: 16, fontWeight: "800", letterSpacing: 4 },
  subtitle: {
    color: colors.onSurfaceTertiary,
    fontSize: 12,
    textAlign: "center",
    marginBottom: spacing.sm,
    letterSpacing: 1,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.surfaceSecondary,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.md,
    padding: spacing.md,
  },
  rank: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: colors.surfaceTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  rankText: { color: colors.onSurface, fontWeight: "800", fontSize: 14 },
  avatar: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.surfaceTertiary,
  },
  avatarFallback: { alignItems: "center", justifyContent: "center" },
  name: { color: colors.onSurface, fontSize: 14, fontWeight: "600" },
  sub: { color: colors.onSurfaceTertiary, fontSize: 12, marginTop: 2 },
  metric: { alignItems: "center" },
  metricNum: { color: colors.brand, fontSize: 18, fontWeight: "800" },
  metricLabel: { color: colors.onSurfaceTertiary, fontSize: 9, letterSpacing: 1 },
  empty: { alignItems: "center", marginTop: spacing.xxl, gap: spacing.sm },
  emptyText: { color: colors.onSurfaceSecondary, fontSize: 14 },
});
