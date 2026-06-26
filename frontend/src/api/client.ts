import { storage } from "@/src/utils/storage";

const BASE = (process.env.EXPO_PUBLIC_BACKEND_URL ?? "").replace(/\/$/, "");
const TOKEN_KEY = "pixelland_session_token";

export type User = {
  user_id: string;
  email: string;
  name: string;
  picture?: string | null;
  coins: number;
  pixels_owned: number;
  is_admin: boolean;
};

export type Pixel = {
  pixel_id: string;
  x: number;
  y: number;
  price: number;
  name: string;
  description?: string;
  cover_image?: string;
  owner_id?: string | null;
  owner_name?: string | null;
  purchased_at?: string | null;
  gallery?: string[];
  external_link?: string | null;
  theme_color?: string | null;
  listed_price?: number | null;
};

export type Transaction = {
  tx_id: string;
  pixel_id: string;
  kind: "primary" | "resale";
  seller_id?: string | null;
  seller_name?: string | null;
  buyer_id: string;
  buyer_name: string;
  price: number;
  fee: number;
  seller_proceeds: number;
  timestamp: string;
};

export type LeaderboardEntry = {
  user_id: string;
  name: string;
  picture?: string | null;
  pixels_owned: number;
  total_spent: number;
  is_admin: boolean;
};

export async function getStoredToken(): Promise<string | null> {
  return (await storage.secureGet<string>(TOKEN_KEY, "")) || null;
}

export async function setStoredToken(token: string | null): Promise<void> {
  if (token) await storage.secureSet(TOKEN_KEY, token);
  else await storage.secureRemove(TOKEN_KEY);
}

async function request<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const token = await getStoredToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(opts.headers as Record<string, string> | undefined),
  };
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${BASE}/api${path}`, { ...opts, headers });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const j = await res.json();
      detail = j.detail || detail;
    } catch {}
    throw new Error(detail);
  }
  if (res.status === 204) return undefined as unknown as T;
  return (await res.json()) as T;
}

export const api = {
  // Auth
  googleSession: (session_token: string) =>
    request<{ session_token: string; user: User }>("/auth/session", {
      method: "POST",
      body: JSON.stringify({ session_token }),
    }),
  adminLogin: (email: string, password: string) =>
    request<{ session_token: string; user: User }>("/auth/admin-login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  me: () => request<User>("/auth/me"),
  logout: () => request<{ ok: boolean }>("/auth/logout", { method: "POST" }),

  // Pixels
  listPixels: () => request<Pixel[]>("/pixels"),
  getPixel: (id: string) => request<Pixel>(`/pixels/${id}`),
  buyPixel: (id: string) => request<Pixel>(`/pixels/${id}/buy`, { method: "POST" }),
  updatePixel: (
    id: string,
    body: Partial<
      Pick<
        Pixel,
        "name" | "description" | "cover_image" | "gallery" | "external_link" | "theme_color"
      >
    >,
  ) =>
    request<Pixel>(`/pixels/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  myPixels: () => request<Pixel[]>("/profile/pixels"),

  // Marketplace
  listForSale: (id: string, price: number) =>
    request<Pixel>(`/pixels/${id}/list`, {
      method: "POST",
      body: JSON.stringify({ price }),
    }),
  unlist: (id: string) => request<Pixel>(`/pixels/${id}/list`, { method: "DELETE" }),
  buyResale: (id: string) => request<Pixel>(`/pixels/${id}/buy-resale`, { method: "POST" }),
  pixelTransactions: (id: string) => request<Transaction[]>(`/pixels/${id}/transactions`),
  marketListings: () => request<Pixel[]>("/listings"),
  leaderboard: () => request<LeaderboardEntry[]>("/leaderboard"),

  // Admin
  adminUsers: () => request<User[]>("/admin/users"),
  adminUpdateUser: (
    user_id: string,
    body: { name?: string; coins?: number; is_admin?: boolean },
  ) =>
    request<User>(`/admin/users/${user_id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  adminUpdatePixel: (
    pixel_id: string,
    body: {
      name?: string;
      description?: string;
      cover_image?: string;
      price?: number;
      owner_id?: string;
    },
  ) =>
    request<Pixel>(`/admin/pixels/${pixel_id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
};
