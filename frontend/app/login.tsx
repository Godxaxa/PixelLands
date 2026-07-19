import { useState } from "react";
import {
  ActivityIndicator,
  Dimensions,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { useAuth } from "@/src/context/AuthContext";
import { StarField } from "@/src/components/StarField";
import { colors, radius, spacing } from "@/src/theme";

const { width: SCREEN_W, height: SCREEN_H } = Dimensions.get("window");

function StarFieldWrap() {
  return <StarField width={SCREEN_W} height={SCREEN_H} starCount={70} seed={11} />;
}

export default function LoginScreen() {
  const { loginWithGoogle, loginAsAdmin } = useAuth();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [showAdmin, setShowAdmin] = useState(false);
  const [email, setEmail] = useState("admin@pixelland.com");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const onGoogle = async () => {
    try {
      setError(null);
      setBusy(true);
      await loginWithGoogle();
      router.replace("/map");
    } catch (e: any) {
      setError(e?.message || "Login failed");
    } finally {
      setBusy(false);
    }
  };

  const onAdmin = async () => {
    try {
      setError(null);
      setBusy(true);
      await loginAsAdmin(email.trim(), password);
      router.replace("/map");
    } catch (e: any) {
      setError(e?.message || "Invalid credentials");
    } finally {
      setBusy(false);
    }
  };

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
      testID="login-screen"
    >
      <View style={styles.glow} />
      <View style={StyleSheet.absoluteFill}>
        <StarFieldWrap />
      </View>
      <View style={styles.content}>
        <Text style={styles.brand} testID="brand-title">PIXEL<Text style={{ color: colors.brand }}>LAND</Text></Text>
        <Text style={styles.tagline}>Funde seu universo no Multiverso.</Text>

        {!showAdmin ? (
          <>
            <Pressable
              testID="google-login-button"
              style={({ pressed }) => [styles.googleBtn, pressed && { opacity: 0.8 }]}
              onPress={onGoogle}
              disabled={busy}
            >
              {busy ? (
                <ActivityIndicator color={colors.onSurface} />
              ) : (
                <>
                  <Ionicons name="logo-google" size={20} color={colors.onSurface} />
                  <Text style={styles.googleBtnText}>Continue with Google</Text>
                </>
              )}
            </Pressable>
            <Pressable testID="show-admin-link" onPress={() => setShowAdmin(true)}>
              <Text style={styles.adminLink}>Admin sign-in</Text>
            </Pressable>
          </>
        ) : (
          <View style={styles.adminForm}>
            <TextInput
              testID="admin-email-input"
              style={styles.input}
              value={email}
              onChangeText={setEmail}
              placeholder="admin@pixelland.com"
              placeholderTextColor={colors.onSurfaceTertiary}
              autoCapitalize="none"
              keyboardType="email-address"
            />
            <TextInput
              testID="admin-password-input"
              style={styles.input}
              value={password}
              onChangeText={setPassword}
              placeholder="Password"
              placeholderTextColor={colors.onSurfaceTertiary}
              secureTextEntry
            />
            <Pressable
              testID="admin-login-button"
              style={({ pressed }) => [styles.primaryBtn, pressed && { opacity: 0.8 }]}
              onPress={onAdmin}
              disabled={busy}
            >
              {busy ? (
                <ActivityIndicator color={colors.onBrand} />
              ) : (
                <Text style={styles.primaryBtnText}>Entrar</Text>
              )}
            </Pressable>
            <Pressable testID="back-to-google-link" onPress={() => setShowAdmin(false)}>
              <Text style={styles.adminLink}>Voltar para Google</Text>
            </Pressable>
          </View>
        )}

        {error ? (
          <Text style={styles.error} testID="login-error">{error}</Text>
        ) : null}
      </View>

      <Text style={styles.footer}>MVP 1.0 · Pixel Coins · Sem pagamentos reais</Text>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.surface,
    paddingHorizontal: spacing.xl,
    justifyContent: "center",
  },
  glow: {
    position: "absolute",
    top: -100,
    left: -100,
    width: 400,
    height: 400,
    borderRadius: 200,
    backgroundColor: colors.brandTertiary,
    opacity: 0.6,
  },
  content: {
    alignItems: "center",
  },
  brand: {
    fontSize: 48,
    fontWeight: "800",
    letterSpacing: 4,
    color: colors.onSurface,
  },
  tagline: {
    color: colors.onSurfaceSecondary,
    fontSize: 14,
    marginTop: spacing.sm,
    marginBottom: spacing.xxl,
    letterSpacing: 1,
  },
  googleBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.md,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    paddingVertical: spacing.lg,
    paddingHorizontal: spacing.xl,
    borderRadius: radius.pill,
    width: "100%",
  },
  googleBtnText: {
    color: colors.onSurface,
    fontWeight: "600",
    fontSize: 16,
  },
  adminLink: {
    color: colors.brand,
    marginTop: spacing.xl,
    fontSize: 13,
    letterSpacing: 1,
  },
  adminForm: { width: "100%", gap: spacing.md },
  input: {
    backgroundColor: colors.surfaceSecondary,
    borderColor: colors.border,
    borderWidth: 1,
    color: colors.onSurface,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderRadius: radius.md,
    fontSize: 16,
  },
  primaryBtn: {
    backgroundColor: colors.brand,
    paddingVertical: spacing.lg,
    borderRadius: radius.pill,
    alignItems: "center",
    marginTop: spacing.sm,
  },
  primaryBtnText: {
    color: colors.onBrand,
    fontWeight: "700",
    fontSize: 16,
    letterSpacing: 1,
  },
  error: {
    color: colors.error,
    marginTop: spacing.lg,
    textAlign: "center",
  },
  footer: {
    position: "absolute",
    bottom: spacing.xl,
    alignSelf: "center",
    color: colors.onSurfaceTertiary,
    fontSize: 11,
    letterSpacing: 1,
  },
});
