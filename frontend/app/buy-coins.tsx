import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import * as WebBrowser from "expo-web-browser";
import * as Linking from "expo-linking";
import * as Haptics from "expo-haptics";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing } from "@/src/theme";

type Bundle = { bundle_id: string; coins: number; price_usd: string; label: string };

export default function BuyCoins() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { user, refresh } = useAuth();
  const [bundles, setBundles] = useState<Bundle[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const b = await api.listBundles();
      setBundles(b);
    } catch {}
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const purchase = async (bundle: Bundle) => {
    try {
      setBusy(bundle.bundle_id);
      setStatus(null);
      const order = await api.createOrder(bundle.bundle_id);
      const redirectUrl =
        Platform.OS === "web" && typeof window !== "undefined"
          ? window.location.origin + "/paypal-return"
          : Linking.createURL("paypal-return");

      if (Platform.OS === "web" && typeof window !== "undefined") {
        // On web we redirect the tab; user returns to buy-coins after PayPal
        window.location.href = order.approve_url;
        return;
      }
      const result = await WebBrowser.openAuthSessionAsync(order.approve_url, redirectUrl);
      // Regardless of the callback shape, attempt to capture — server is idempotent
      if (result.type !== "cancel" && result.type !== "dismiss") {
        setStatus("Confirmando pagamento...");
        const cap = await api.captureOrder(order.order_id);
        if (cap.credited) {
          Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
          setStatus(`+${cap.coins_added} coins creditados! Saldo: ${cap.new_balance}`);
          await refresh();
        } else {
          setStatus(`Status: ${cap.status}`);
        }
      } else {
        setStatus("Pagamento cancelado");
      }
    } catch (e: any) {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error).catch(() => {});
      setStatus(e?.message || "Falha no pagamento");
    } finally {
      setBusy(null);
    }
  };

  return (
    <View style={[styles.container, { paddingTop: insets.top }]} testID="buy-coins-screen">
      <View style={styles.header}>
        <Pressable testID="buy-back" onPress={() => router.back()} style={styles.iconBtn}>
          <Ionicons name="chevron-back" size={20} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.title}>COMPRAR COINS</Text>
        <View style={{ width: 36 }} />
      </View>

      <View style={styles.balance} testID="current-balance">
        <Ionicons name="diamond" size={18} color={colors.gold} />
        <Text style={styles.balanceNum}>{user?.coins ?? 0}</Text>
        <Text style={styles.balanceLabel}>Pixel Coins</Text>
      </View>

      <Text style={styles.subLabel}>
        Escolha um pacote — pagamento seguro via PayPal (sandbox)
      </Text>

      <FlatList
        data={bundles}
        keyExtractor={(b) => b.bundle_id}
        contentContainerStyle={{ padding: spacing.lg, gap: spacing.md, paddingBottom: insets.bottom + spacing.xl }}
        renderItem={({ item }) => {
          const isBusy = busy === item.bundle_id;
          return (
            <Pressable
              testID={`bundle-${item.bundle_id}`}
              style={({ pressed }) => [
                styles.bundleCard,
                pressed && { transform: [{ scale: 0.98 }] },
                isBusy && { opacity: 0.6 },
              ]}
              onPress={() => purchase(item)}
              disabled={!!busy}
            >
              <View style={{ flex: 1 }}>
                <Text style={styles.bundleLabel}>{item.label}</Text>
                <Text style={styles.bundleSub}>
                  {(item.coins / parseFloat(item.price_usd)).toFixed(0)} coins / US$
                </Text>
              </View>
              <View style={styles.bundlePrice}>
                {isBusy ? (
                  <ActivityIndicator color={colors.onBrand} />
                ) : (
                  <>
                    <Text style={styles.bundlePriceText}>US$ {item.price_usd}</Text>
                    <Ionicons name="arrow-forward" size={14} color={colors.onBrand} />
                  </>
                )}
              </View>
            </Pressable>
          );
        }}
      />

      {status ? <Text style={styles.status} testID="payment-status">{status}</Text> : null}
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
  title: { color: colors.gold, fontSize: 16, fontWeight: "800", letterSpacing: 4 },
  balance: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.sm,
    marginTop: spacing.md,
  },
  balanceNum: { color: colors.onSurface, fontSize: 28, fontWeight: "800", letterSpacing: 1 },
  balanceLabel: { color: colors.onSurfaceTertiary, fontSize: 11, letterSpacing: 1 },
  subLabel: {
    color: colors.onSurfaceSecondary,
    fontSize: 12,
    textAlign: "center",
    marginTop: spacing.sm,
    marginHorizontal: spacing.lg,
  },
  bundleCard: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: colors.surfaceSecondary,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.lg,
    padding: spacing.lg,
    gap: spacing.md,
  },
  bundleLabel: { color: colors.onSurface, fontSize: 15, fontWeight: "700" },
  bundleSub: { color: colors.onSurfaceTertiary, fontSize: 11, marginTop: 2 },
  bundlePrice: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
    backgroundColor: colors.brand,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: radius.pill,
  },
  bundlePriceText: { color: colors.onBrand, fontWeight: "700", fontSize: 13, letterSpacing: 0.5 },
  status: {
    color: colors.brand,
    textAlign: "center",
    padding: spacing.md,
  },
});
