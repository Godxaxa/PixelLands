# PixelLand — MVP 1.0

## Overview
Mobile-first Expo app where each user can claim a **Pixel** (a unique 20×20 grid square) representing a digital territory ("universe"). MVP uses fictional **Pixel Coins** — no real payments.

## Stack
- **Frontend**: Expo SDK 54 + Expo Router (stack navigation), React Native Reanimated + Gesture Handler for the zoom/pan map, expo-image for cover art, expo-secure-store for session token, expo-haptics for tactile feedback.
- **Backend**: FastAPI + Motor (async MongoDB), bcrypt for admin password, httpx for Emergent Google OAuth verification.

## Core Features
- **Auth**: Emergent-managed Google OAuth (consumer login) **and** a dedicated admin sign-in (email + password).
- **Map**: 20×20 grid (400 pixels) with pinch-zoom, pan, three-state coloring (available / sold / yours), bottom sheet with cover, owner, price, purchase date and a one-tap Buy CTA.
- **Profile**: avatar, name, coin balance, pixels owned, gallery of owned territories.
- **Pixel Page**: full detail view with edit capability for the owner (name / description / cover image).
- **Admin Panel**: users tab (edit name, coins, admin flag) and pixels tab (edit name, description, cover, price, assign owner / clear ownership).

## Economy
- New Google users start with **1000 Pixel Coins**.
- Pixel prices are randomly seeded from `[5, 10, 20, 30, 40, 50, 100]` (seed=42 so the grid is deterministic).
- Admin user has 99 999 coins to dogfood the buy flow.

## API Surface (`/api`)
| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| POST | `/auth/session` | — | Exchange Emergent session_token for an app session |
| POST | `/auth/admin-login` | — | Email + password admin login |
| GET | `/auth/me` | bearer | Current user |
| POST | `/auth/logout` | bearer | Revoke session |
| GET | `/pixels` | — | Full 400-pixel grid |
| GET | `/pixels/{id}` | — | Single pixel |
| POST | `/pixels/{id}/buy` | bearer | Atomic buy (race-safe via conditional update) |
| PATCH | `/pixels/{id}` | bearer (owner) | Update name/description/cover |
| GET | `/profile/pixels` | bearer | Pixels owned by current user |
| GET | `/admin/users` | admin | List users (no password hashes) |
| PATCH | `/admin/users/{id}` | admin | Edit user |
| PATCH | `/admin/pixels/{id}` | admin | Edit any pixel, reassign owner |
| POST | `/admin/pixels/seed` | admin | Re-seed missing pixels |

## Credentials
- Admin: `admin@pixelland.com` / `Apollo2122@×+>×>adm00140`

## Design
Dark-First Utility palette. Background `#0F1115`, accent electric cyan `#00E5FF`. Minimal, command-center aesthetic.

## Tests
21/21 backend pytest tests passing.
