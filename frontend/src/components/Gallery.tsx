import { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Dimensions,
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

import { Media } from "@/src/api/client";
import { colors, radius, spacing } from "@/src/theme";

const { width: SCREEN_W, height: SCREEN_H } = Dimensions.get("window");

type Props = {
  visible: boolean;
  media: Media[];
  startIndex: number;
  onClose: () => void;
};

/**
 * Fullscreen swipeable pager. Supports images and videos.
 * Uses expo-video (expo-av deprecated) with native controls.
 */
export function GalleryViewer({ visible, media, startIndex, onClose }: Props) {
  const insets = useSafeAreaInsets();
  const [index, setIndex] = useState(startIndex);
  const listRef = useRef<FlatList<Media>>(null);

  useEffect(() => {
    if (visible) {
      setIndex(startIndex);
      // Force scroll to startIndex after mount
      requestAnimationFrame(() => {
        listRef.current?.scrollToIndex({ index: startIndex, animated: false });
      });
    }
  }, [visible, startIndex]);

  return (
    <Modal visible={visible} animationType="fade" transparent onRequestClose={onClose}>
      <View style={styles.root} testID="gallery-viewer">
        <FlatList
          ref={listRef}
          data={media}
          horizontal
          pagingEnabled
          showsHorizontalScrollIndicator={false}
          keyExtractor={(m) => m.media_id}
          getItemLayout={(_, i) => ({ length: SCREEN_W, offset: SCREEN_W * i, index: i })}
          onScroll={(e) => {
            const i = Math.round(e.nativeEvent.contentOffset.x / SCREEN_W);
            if (i !== index) setIndex(i);
          }}
          initialScrollIndex={startIndex}
          renderItem={({ item, index: i }) => (
            <View style={{ width: SCREEN_W, height: SCREEN_H, alignItems: "center", justifyContent: "center" }}>
              {item.kind === "video" ? (
                <VideoPage uri={item.url} isCurrent={i === index} />
              ) : (
                <Image
                  source={{ uri: item.url }}
                  style={{ width: SCREEN_W, height: SCREEN_H * 0.8 }}
                  contentFit="contain"
                />
              )}
            </View>
          )}
        />
        <Pressable
          testID="gallery-close"
          style={[styles.close, { top: insets.top + spacing.sm }]}
          onPress={onClose}
        >
          <Ionicons name="close" size={24} color={colors.onSurface} />
        </Pressable>
        <View style={[styles.footer, { bottom: insets.bottom + spacing.sm }]}>
          <Text style={styles.counter}>
            {index + 1} / {media.length}
          </Text>
        </View>
      </View>
    </Modal>
  );
}

function VideoPage({ uri, isCurrent }: { uri: string; isCurrent: boolean }) {
  const player = useVideoPlayer(uri, (p) => {
    p.loop = false;
    p.muted = false;
  });

  useEffect(() => {
    if (isCurrent) {
      player.play();
    } else {
      player.pause();
    }
  }, [isCurrent, player]);

  return (
    <VideoView
      player={player}
      style={{ width: SCREEN_W, height: SCREEN_H * 0.9 }}
      contentFit="contain"
      allowsFullscreen
      allowsPictureInPicture={false}
      nativeControls
    />
  );
}

type ThumbProps = {
  media: Media;
  onPress: () => void;
  onDelete?: () => void;
  editable: boolean;
};

/** Square thumbnail with video play badge + optional delete button. */
export function MediaThumb({ media, onPress, onDelete, editable }: ThumbProps) {
  return (
    <Pressable
      testID={`media-thumb-${media.media_id}`}
      style={styles.thumb}
      onPress={onPress}
    >
      <Image source={{ uri: media.thumbnail_url }} style={styles.thumbImg} contentFit="cover" />
      {media.kind === "video" ? (
        <View style={styles.playBadge}>
          <Ionicons name="play" size={20} color="#fff" />
        </View>
      ) : null}
      {media.duration ? (
        <View style={styles.durationBadge}>
          <Text style={styles.durationText}>
            {formatDuration(media.duration)}
          </Text>
        </View>
      ) : null}
      {editable && onDelete ? (
        <Pressable
          testID={`media-delete-${media.media_id}`}
          style={styles.deleteBadge}
          onPress={(e) => {
            e.stopPropagation?.();
            onDelete();
          }}
        >
          <Ionicons name="close" size={14} color="#fff" />
        </Pressable>
      ) : null}
    </Pressable>
  );
}

export function LoadingThumb({ progress }: { progress: number }) {
  return (
    <View style={styles.thumb} testID="media-uploading">
      <View style={[styles.thumbImg, styles.uploadingBg]}>
        <ActivityIndicator color={colors.brand} />
        <View style={styles.progressBar}>
          <View style={[styles.progressFill, { width: `${Math.min(100, Math.max(0, progress * 100))}%` }]} />
        </View>
        <Text style={styles.progressText}>{Math.round(progress * 100)}%</Text>
      </View>
    </View>
  );
}

function formatDuration(sec: number) {
  const s = Math.round(sec);
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${r.toString().padStart(2, "0")}`;
}

const THUMB = 110;

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#000" },
  close: {
    position: "absolute",
    right: spacing.lg,
    width: 40,
    height: 40,
    borderRadius: radius.pill,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "rgba(20,20,20,0.7)",
  },
  footer: { position: "absolute", left: 0, right: 0, alignItems: "center" },
  counter: {
    color: colors.onSurface,
    backgroundColor: "rgba(20,20,20,0.7)",
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
    borderRadius: radius.pill,
    fontSize: 12,
    letterSpacing: 1,
  },
  thumb: {
    width: THUMB,
    height: THUMB,
    borderRadius: radius.md,
    overflow: "hidden",
    backgroundColor: colors.surfaceTertiary,
  },
  thumbImg: { width: "100%", height: "100%" },
  uploadingBg: {
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.surface,
    gap: spacing.sm,
  },
  playBadge: {
    position: "absolute",
    top: "50%",
    left: "50%",
    marginTop: -20,
    marginLeft: -20,
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: "rgba(0,0,0,0.55)",
    borderWidth: 2,
    borderColor: "#fff",
    alignItems: "center",
    justifyContent: "center",
  },
  durationBadge: {
    position: "absolute",
    bottom: 6,
    right: 6,
    backgroundColor: "rgba(0,0,0,0.7)",
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
  },
  durationText: { color: "#fff", fontSize: 10, fontWeight: "600" },
  deleteBadge: {
    position: "absolute",
    top: 4,
    right: 4,
    width: 22,
    height: 22,
    borderRadius: 11,
    backgroundColor: "rgba(0,0,0,0.75)",
    alignItems: "center",
    justifyContent: "center",
  },
  progressBar: {
    width: "80%",
    height: 4,
    backgroundColor: colors.borderStrong,
    borderRadius: 2,
    overflow: "hidden",
  },
  progressFill: { height: "100%", backgroundColor: colors.brand },
  progressText: { color: colors.onSurfaceSecondary, fontSize: 11 },
});
