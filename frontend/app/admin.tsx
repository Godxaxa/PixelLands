import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, Pixel, User } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing } from "@/src/theme";

type Tab = "users" | "pixels";

export default function AdminScreen() {
  const { user } = useAuth();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const [tab, setTab] = useState<Tab>("users");
  const [users, setUsers] = useState<User[]>([]);
  const [pixels, setPixels] = useState<Pixel[]>([]);
  const [loading, setLoading] = useState(true);

  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [editingPixel, setEditingPixel] = useState<Pixel | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [u, p] = await Promise.all([api.adminUsers(), api.listPixels()]);
      setUsers(u);
      setPixels(p);
    } catch (e) {
      console.warn(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!user?.is_admin) {
      router.replace("/map");
      return;
    }
    load();
  }, [user, load, router]);

  if (!user?.is_admin) return null;

  return (
    <View style={[styles.container, { paddingTop: insets.top }]} testID="admin-screen">
      <View style={styles.header}>
        <Pressable testID="admin-back" onPress={() => router.back()} style={styles.iconBtn}>
          <Ionicons name="chevron-back" size={20} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.headerTitle}>ADMIN</Text>
        <Pressable
          testID="reset-map-btn"
          onPress={async () => {
            try {
              await api.adminResetMap();
              await load();
            } catch {}
          }}
          style={[styles.iconBtn, { backgroundColor: colors.warning + "33" }]}
        >
          <Ionicons name="refresh" size={18} color={colors.warning} />
        </Pressable>
      </View>

      <View style={styles.tabs}>
        <Pressable
          testID="tab-users"
          style={[styles.tab, tab === "users" && styles.tabActive]}
          onPress={() => setTab("users")}
        >
          <Text style={[styles.tabText, tab === "users" && styles.tabTextActive]}>
            Users ({users.length})
          </Text>
        </Pressable>
        <Pressable
          testID="tab-pixels"
          style={[styles.tab, tab === "pixels" && styles.tabActive]}
          onPress={() => setTab("pixels")}
        >
          <Text style={[styles.tabText, tab === "pixels" && styles.tabTextActive]}>
            Pixels ({pixels.length})
          </Text>
        </Pressable>
      </View>

      {loading ? (
        <ActivityIndicator color={colors.brand} style={{ marginTop: spacing.xl }} />
      ) : tab === "users" ? (
        <FlatList
          data={users}
          keyExtractor={(u) => u.user_id}
          contentContainerStyle={{ padding: spacing.lg, gap: spacing.sm }}
          renderItem={({ item }) => (
            <Pressable
              testID={`admin-user-${item.user_id}`}
              style={styles.listRow}
              onPress={() => setEditingUser(item)}
            >
              <View style={{ flex: 1 }}>
                <Text style={styles.listTitle}>
                  {item.name} {item.is_admin ? <Text style={{ color: colors.brand }}>· admin</Text> : null}
                </Text>
                <Text style={styles.listSub}>{item.email}</Text>
              </View>
              <View style={styles.listMeta}>
                <Text style={styles.listMetaNum}>{item.coins}</Text>
                <Text style={styles.listMetaLabel}>coins</Text>
              </View>
              <View style={styles.listMeta}>
                <Text style={styles.listMetaNum}>{item.pixels_owned}</Text>
                <Text style={styles.listMetaLabel}>pixels</Text>
              </View>
            </Pressable>
          )}
        />
      ) : (
        <FlatList
          data={pixels}
          keyExtractor={(p) => p.pixel_id}
          contentContainerStyle={{ padding: spacing.lg, gap: spacing.sm }}
          renderItem={({ item }) => (
            <Pressable
              testID={`admin-pixel-${item.pixel_id}`}
              style={styles.listRow}
              onPress={() => setEditingPixel(item)}
            >
              <View style={{ flex: 1 }}>
                <Text style={styles.listTitle}>{item.name}</Text>
                <Text style={styles.listSub}>
                  ({item.x},{item.y}) · {item.owner_name || "Unclaimed"}
                </Text>
              </View>
              <View style={styles.listMeta}>
                <Text style={styles.listMetaNum}>{item.price}</Text>
                <Text style={styles.listMetaLabel}>price</Text>
              </View>
              <Ionicons name="chevron-forward" size={16} color={colors.onSurfaceTertiary} />
            </Pressable>
          )}
        />
      )}

      <UserEditModal
        user={editingUser}
        onClose={() => setEditingUser(null)}
        onSaved={(u) => {
          setUsers((list) => list.map((x) => (x.user_id === u.user_id ? u : x)));
          setEditingUser(null);
        }}
      />
      <PixelEditModal
        pixel={editingPixel}
        users={users}
        onClose={() => setEditingPixel(null)}
        onSaved={(p) => {
          setPixels((list) => list.map((x) => (x.pixel_id === p.pixel_id ? p : x)));
          setEditingPixel(null);
        }}
      />
    </View>
  );
}

function UserEditModal({
  user,
  onClose,
  onSaved,
}: {
  user: User | null;
  onClose: () => void;
  onSaved: (u: User) => void;
}) {
  const [name, setName] = useState("");
  const [coins, setCoins] = useState("");
  const [isAdmin, setIsAdmin] = useState(false);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (user) {
      setName(user.name);
      setCoins(String(user.coins));
      setIsAdmin(user.is_admin);
      setErr(null);
    }
  }, [user]);

  if (!user) return null;

  const onSave = async () => {
    try {
      setSaving(true);
      const updated = await api.adminUpdateUser(user.user_id, {
        name,
        coins: parseInt(coins, 10) || 0,
        is_admin: isAdmin,
      });
      onSaved(updated);
    } catch (e: any) {
      setErr(e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal visible animationType="slide" transparent onRequestClose={onClose}>
      <KeyboardAvoidingView
        style={styles.modalWrap}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <Pressable style={styles.modalBackdrop} onPress={onClose} />
        <View style={styles.modalSheet}>
          <Text style={styles.modalTitle}>Edit User</Text>
          <Text style={styles.modalSub}>{user.email}</Text>
          <ScrollView contentContainerStyle={{ gap: spacing.md, paddingVertical: spacing.md }}>
            <TextInput
              testID="user-edit-name"
              style={styles.input}
              value={name}
              onChangeText={setName}
              placeholder="Name"
              placeholderTextColor={colors.onSurfaceTertiary}
            />
            <TextInput
              testID="user-edit-coins"
              style={styles.input}
              value={coins}
              onChangeText={setCoins}
              placeholder="Coins"
              placeholderTextColor={colors.onSurfaceTertiary}
              keyboardType="numeric"
            />
            <Pressable
              testID="user-edit-admin-toggle"
              style={[styles.toggle, isAdmin && styles.toggleOn]}
              onPress={() => setIsAdmin((v) => !v)}
            >
              <Text style={[styles.toggleText, isAdmin && { color: colors.onBrand }]}>
                Admin: {isAdmin ? "YES" : "NO"}
              </Text>
            </Pressable>
            {err ? <Text style={styles.err}>{err}</Text> : null}
            <Pressable testID="user-edit-save" style={styles.saveBtn} onPress={onSave} disabled={saving}>
              {saving ? <ActivityIndicator color={colors.onBrand} /> : <Text style={styles.saveBtnText}>Save</Text>}
            </Pressable>
          </ScrollView>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

function PixelEditModal({
  pixel,
  users,
  onClose,
  onSaved,
}: {
  pixel: Pixel | null;
  users: User[];
  onClose: () => void;
  onSaved: (p: Pixel) => void;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [cover, setCover] = useState("");
  const [price, setPrice] = useState("");
  const [ownerId, setOwnerId] = useState<string>("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (pixel) {
      setName(pixel.name);
      setDescription(pixel.description || "");
      setCover(pixel.cover_image || "");
      setPrice(String(pixel.price));
      setOwnerId(pixel.owner_id || "");
      setErr(null);
    }
  }, [pixel]);

  if (!pixel) return null;

  const onSave = async () => {
    try {
      setSaving(true);
      const body: any = {
        name,
        description,
        cover_image: cover,
        price: parseInt(price, 10) || 0,
      };
      if (ownerId !== (pixel.owner_id || "")) body.owner_id = ownerId;
      const updated = await api.adminUpdatePixel(pixel.pixel_id, body);
      onSaved(updated);
    } catch (e: any) {
      setErr(e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal visible animationType="slide" transparent onRequestClose={onClose}>
      <KeyboardAvoidingView
        style={styles.modalWrap}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <Pressable style={styles.modalBackdrop} onPress={onClose} />
        <View style={styles.modalSheet}>
          <Text style={styles.modalTitle}>Edit Pixel</Text>
          <Text style={styles.modalSub}>({pixel.x},{pixel.y})</Text>
          <ScrollView contentContainerStyle={{ gap: spacing.md, paddingVertical: spacing.md }}>
            <TextInput
              testID="pixel-edit-name"
              style={styles.input}
              value={name}
              onChangeText={setName}
              placeholder="Name"
              placeholderTextColor={colors.onSurfaceTertiary}
            />
            <TextInput
              testID="pixel-edit-desc"
              style={[styles.input, { minHeight: 80, textAlignVertical: "top" }]}
              value={description}
              onChangeText={setDescription}
              placeholder="Description"
              placeholderTextColor={colors.onSurfaceTertiary}
              multiline
            />
            <TextInput
              testID="pixel-edit-cover"
              style={styles.input}
              value={cover}
              onChangeText={setCover}
              placeholder="Cover URL"
              placeholderTextColor={colors.onSurfaceTertiary}
              autoCapitalize="none"
            />
            <TextInput
              testID="pixel-edit-price"
              style={styles.input}
              value={price}
              onChangeText={setPrice}
              placeholder="Price"
              placeholderTextColor={colors.onSurfaceTertiary}
              keyboardType="numeric"
            />
            <Text style={styles.modalSub}>Owner</Text>
            <View style={styles.ownerList}>
              <Pressable
                testID="owner-none"
                style={[styles.ownerChip, ownerId === "" && styles.ownerChipActive]}
                onPress={() => setOwnerId("")}
              >
                <Text style={[styles.ownerChipText, ownerId === "" && { color: colors.onBrand }]}>None</Text>
              </Pressable>
              {users.map((u) => (
                <Pressable
                  key={u.user_id}
                  testID={`owner-${u.user_id}`}
                  style={[styles.ownerChip, ownerId === u.user_id && styles.ownerChipActive]}
                  onPress={() => setOwnerId(u.user_id)}
                >
                  <Text style={[styles.ownerChipText, ownerId === u.user_id && { color: colors.onBrand }]}>
                    {u.name || u.email}
                  </Text>
                </Pressable>
              ))}
            </View>
            {err ? <Text style={styles.err}>{err}</Text> : null}
            <Pressable testID="pixel-edit-save" style={styles.saveBtn} onPress={onSave} disabled={saving}>
              {saving ? <ActivityIndicator color={colors.onBrand} /> : <Text style={styles.saveBtnText}>Save</Text>}
            </Pressable>
          </ScrollView>
        </View>
      </KeyboardAvoidingView>
    </Modal>
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
  headerTitle: { color: colors.brand, fontSize: 16, fontWeight: "800", letterSpacing: 4 },
  tabs: {
    flexDirection: "row",
    marginHorizontal: spacing.lg,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.pill,
    padding: 4,
  },
  tab: {
    flex: 1,
    paddingVertical: spacing.sm,
    alignItems: "center",
    borderRadius: radius.pill,
  },
  tabActive: { backgroundColor: colors.brand },
  tabText: { color: colors.onSurfaceSecondary, fontWeight: "600", letterSpacing: 0.5 },
  tabTextActive: { color: colors.onBrand },
  listRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.surfaceSecondary,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.md,
    padding: spacing.md,
  },
  listTitle: { color: colors.onSurface, fontSize: 14, fontWeight: "600" },
  listSub: { color: colors.onSurfaceTertiary, fontSize: 12, marginTop: 2 },
  listMeta: { alignItems: "center" },
  listMetaNum: { color: colors.brand, fontSize: 14, fontWeight: "700" },
  listMetaLabel: { color: colors.onSurfaceTertiary, fontSize: 9, letterSpacing: 1 },

  modalWrap: { flex: 1, justifyContent: "flex-end" },
  modalBackdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "#000000AA" },
  modalSheet: {
    backgroundColor: colors.surfaceSecondary,
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    padding: spacing.lg,
    maxHeight: "85%",
    borderTopColor: colors.border,
    borderTopWidth: 1,
  },
  modalTitle: { color: colors.onSurface, fontSize: 18, fontWeight: "700" },
  modalSub: { color: colors.onSurfaceTertiary, fontSize: 12, marginTop: 2, letterSpacing: 1 },
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
  toggle: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.md,
    paddingVertical: spacing.md,
    alignItems: "center",
    backgroundColor: colors.surface,
  },
  toggleOn: { backgroundColor: colors.brand, borderColor: colors.brand },
  toggleText: { color: colors.onSurface, fontWeight: "600", letterSpacing: 1 },
  saveBtn: {
    backgroundColor: colors.brand,
    paddingVertical: spacing.lg,
    borderRadius: radius.pill,
    alignItems: "center",
  },
  saveBtnText: { color: colors.onBrand, fontWeight: "700", letterSpacing: 1 },
  err: { color: colors.error },
  ownerList: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  ownerChip: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: radius.pill,
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
  },
  ownerChipActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  ownerChipText: { color: colors.onSurface, fontSize: 12 },
});
