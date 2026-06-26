# PixelLand — MVP 1.0 + Marketplace Iteration

## Overview
Mobile-first Expo app where each user can claim a **Pixel** (a unique 20×20 grid square) representing a digital territory ("universe"). MVP uses fictional **Pixel Coins** — no real payments.

## Stack
- **Frontend**: Expo SDK 54 + Expo Router (stack navigation), React Native Reanimated + Gesture Handler for the zoom/pan map, expo-image for cover art, expo-secure-store for session token, expo-haptics for tactile feedback.
- **Backend**: FastAPI + Motor (async MongoDB), bcrypt for admin password, httpx for Emergent Google OAuth verification.

## Core Features
- **Auth**: Emergent-managed Google OAuth (consumer login) **and** a dedicated admin sign-in (email + password).
- **Map**: 20×20 grid (400 pixels) with pinch-zoom, pan, multi-state coloring (available / sold / for-sale / yours / yours-listed), bottom sheet with cover, owner, price (or resale price), purchase date and a one-tap Buy CTA.
- **Profile**: avatar, name, coin balance, pixels owned, gallery of owned territories, link to leaderboard.
- **Pixel Page** (theme-colored): name / owner / cover / description / purchase date, **external link**, **image gallery**, **theme color picker**, **transaction history**, marketplace controls (list / unlist / buy resale).
- **Admin Panel**: users tab (edit name, coins, admin flag) and pixels tab (edit name, description, cover, price, assign owner / clear ownership).
- **Marketplace (secondary)**: any owner can list their pixel for a custom price; anyone else can buy at that price; **10% market fee** is taken from the seller (seller receives 90%, the 10% is burned for now → ready for future revenue split / coin top-up funnel).
- **Transactions**: every purchase (primary mint and resale) records a transaction with buyer / seller / price / fee / proceeds / timestamp.
- **Leaderboard**: top 50 landlords ranked by pixels owned, then total coins spent. Gold / silver / bronze medals.

## Economy
- New Google users start with **1000 Pixel Coins**.
- Pixel prices are randomly seeded from `[5, 10, 20, 30, 40, 50, 100]` (seed=42 so the grid is deterministic).
- Admin user has 99 999 coins to dogfood the buy flow.
- Resale fee: **10%** (`floor(price * 0.1)`).

## API Surface (`/api`)
| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| POST | `/auth/session` | — | Exchange Emergent session_token for an app session |
| POST | `/auth/admin-login` | — | Email + password admin login |
| GET | `/auth/me` | bearer | Current user |
| POST | `/auth/logout` | bearer | Revoke session |
| GET | `/pixels` | — | Full 400-pixel grid (with listed_price, gallery, theme_color) |
| GET | `/pixels/{id}` | — | Single pixel |
| POST | `/pixels/{id}/buy` | bearer | Primary buy (race-safe) |
| PATCH | `/pixels/{id}` | bearer (owner) | Update name/description/cover/gallery/external_link/theme_color |
| POST | `/pixels/{id}/list` | bearer (owner) | List for resale at `{price}` |
| DELETE | `/pixels/{id}/list` | bearer (owner) | Cancel listing |
| POST | `/pixels/{id}/buy-resale` | bearer | Buy from marketplace (10% fee) |
| GET | `/pixels/{id}/transactions` | — | History per pixel (primary + resale) |
| GET | `/listings` | — | All pixels currently listed for resale |
| GET | `/leaderboard` | — | Top 50 landlords |
| GET | `/profile/pixels` | bearer | Pixels owned by current user |
| GET | `/admin/users` | admin | List users (no password hashes) |
| PATCH | `/admin/users/{id}` | admin | Edit user |
| PATCH | `/admin/pixels/{id}` | admin | Edit any pixel, reassign owner |
| POST | `/admin/pixels/seed` | admin | Re-seed missing pixels |

## Credentials
- Admin: `admin@pixelland.com` / `Apollo2122@×+>×>adm00140`

## Design
Dark-First Utility palette. Background `#0F1115`, accent electric cyan `#00E5FF`. Owner-customizable per-pixel theme color overrides accent on the pixel page (cover scrim, links, buttons).

## Tests
- Iteration 1: 21/21 backend pytest tests passing.
- Iteration 2: 14/14 new marketplace + leaderboard + personalization tests passing.
