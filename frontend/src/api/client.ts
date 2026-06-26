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
    body: Partial<Pick<Pixel, "name" | "description" | "cover_image">>,
  ) =>
    request<Pixel>(`/pixels/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  myPixels: () => request<Pixel[]>("/profile/pixels"),

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
