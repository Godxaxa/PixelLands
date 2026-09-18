import { useEffect } from "react";
import {
  FlatList,
  Modal,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { Image } from "expo-image";
import { Ionicons } from "@expo/vector-icons";
import { VideoView, useVideoPlayer } from "expo-video";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Media, Pixel } from "@/src/api/client";
import { colors, radius, spacing } from "@/src/theme";

/**
 * Renders a pixel's cover as either an image or a muted-looping video.
 * Fills its parent container.
 */
export function CoverView({
  pixel,
  style,
}: {
  pixel: Pixel;
  style?: any;
}) {
  const isVideo = pixel.cover_type === "video" && !!pixel.cover_video;
  if (isVideo) {
    return <CoverVideo uri={pixel.cover_video as string} style={style} />;
  }
  return (
    <Image
      source={{ uri: pixel.cover_image }}
      style={style}
      contentFit="cover"
      testID="cover-image"
    />
  );
}

function CoverVideo({ uri, style }: { uri: string; style?: any }) {
  const player = useVideoPlayer(uri, (p) => {
    p.loop = true;
    p.muted = true;
    p.play();
  });
  return (
    <VideoView
      player={player}
      style={style}
      contentFit="cover"
      nativeControls={false}
      testID="cover-video"
    />
  );
}

/**
 * Modal that lets the owner pick one of the uploaded media items to be the cover.
 * Also exposes "Remover capa" to reset to default.
 */
export function CoverPicker({
  visible,
  media,
  selectedId,
  onSelect,
  onClose,
}: {
  visible: boolean;
  media: Media[];
  selectedId?: string | null;
  onSelect: (media_id: string | null) => void;
  onClose: () => void;
}) {
  const insets = useSafeAreaInsets();

  useEffect(() => {
    // no-op; kept for future analytics hooks
  }, [visible]);

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <View style={styles.modalWrap}>
        <Pressable style={styles.backdrop} onPress={onClose} />
        <View style={[styles.sheet, { paddingBottom: insets.bottom + spacing.lg }]}>
          <View style={styles.handle} />
          <View style={styles.headerRow}>
            <Text style={styles.title}>Escolher capa</Text>
            <Pressable testID="cover-picker-close" onPress={onClose} style={styles.closeBtn}>
              <Ionicons name="close" size={20} color={colors.onSurface} />
            </Pressable>
          </View>
          <Text style={styles.sub}>
            Selecione uma foto ou vídeo já enviado. Vídeos rodam em loop sem áudio.
          </Text>

          {media.length === 0 ? (
            <View style={styles.emptyBox} testID="cover-picker-empty">
              <Ionicons name="images-outline" size={40} color={colors.onSurfaceTertiary} />
              <Text style={styles.emptyText}>
                Envie fotos ou vídeos primeiro na Galeria de Mídia
              </Text>
            </View>
          ) : (
            <FlatList
              data={media}
              keyExtractor={(m) => m.media_id}
              numColumns={3}
              contentContainerStyle={{ paddingVertical: spacing.md, gap: spacing.sm }}
              columnWrapperStyle={{ gap: spacing.sm }}
              renderItem={({ item }) => {
                const isSelected = item.media_id === selectedId;
                return (
                  <Pressable
                    testID={`cover-option-${item.media_id}`}
                    style={[
                      styles.cell,
                      isSelected && { borderColor: colors.brand, borderWidth: 2 },
                    ]}
                    onPress={() => onSelect(item.media_id)}
                  >
                    <Image
                      source={{ uri: item.thumbnail_url }}
                      style={styles.cellImg}
                      contentFit="cover"
                    />
                    {item.kind === "video" ? (
                      <View style={styles.videoBadge}>
                        <Ionicons name="play" size={14} color="#fff" />
                      </View>
                    ) : null}
                    {isSelected ? (
                      <View style={styles.selectedBadge}>
                        <Ionicons name="checkmark" size={14} color={colors.onBrand} />
                      </View>
                    ) : null}
                  </Pressable>
                );
              }}
            />
          )}

          <Pressable
            testID="cover-remove-btn"
            style={styles.resetBtn}
            onPress={() => onSelect(null)}
          >
            <Ionicons name="refresh" size={16} color={colors.onSurfaceSecondary} />
            <Text style={styles.resetText}>Voltar para capa padrão</Text>
          </Pressable>
        </View>
      </View>
    </Modal>
  );
}

const CELL = 100;

const styles = StyleSheet.create({
  modalWrap: { flex: 1, justifyContent: "flex-end" },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "#000000AA" },
  sheet: {
    backgroundColor: colors.surfaceSecondary,
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    padding: spacing.lg,
    maxHeight: "80%",
    borderTopColor: colors.border,
    borderTopWidth: 1,
  },
  handle: {
    alignSelf: "center",
    width: 40,
    height: 4,
    backgroundColor: colors.borderStrong,
    borderRadius: 2,
    marginBottom: spacing.md,
  },
  headerRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  title: { color: colors.onSurface, fontSize: 18, fontWeight: "700" },
  sub: { color: colors.onSurfaceSecondary, fontSize: 12, marginTop: 4 },
  closeBtn: {
    width: 32,
    height: 32,
    borderRadius: 16,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.surface,
  },
  cell: {
    width: CELL,
    height: CELL,
    borderRadius: radius.md,
    overflow: "hidden",
    backgroundColor: colors.surfaceTertiary,
    borderWidth: 1,
    borderColor: colors.border,
  },
  cellImg: { width: "100%", height: "100%" },
  videoBadge: {
    position: "absolute",
    top: 4,
    left: 4,
    backgroundColor: "rgba(0,0,0,0.6)",
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
  },
  selectedBadge: {
    position: "absolute",
    bottom: 4,
    right: 4,
    width: 22,
    height: 22,
    borderRadius: 11,
    backgroundColor: colors.brand,
    alignItems: "center",
    justifyContent: "center",
  },
  resetBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.sm,
    paddingVertical: spacing.md,
    marginTop: spacing.sm,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.border,
  },
  resetText: { color: colors.onSurfaceSecondary, fontSize: 13 },
  emptyBox: {
    alignItems: "center",
    padding: spacing.xxl,
    gap: spacing.sm,
  },
  emptyText: {
    color: colors.onSurfaceSecondary,
    fontSize: 13,
    textAlign: "center",
  },
});
