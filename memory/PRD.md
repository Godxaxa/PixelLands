# PixelLand — Multiverse MVP

## Overview
Mobile-first Expo app onde cada usuário funda um **Universo** (Pixel) em uma grade 20×20 (400 espaços) do Multiverso PixelLand. Moeda fictícia (Pixel Coins). Sem pagamentos reais.

## Stack
- **Frontend**: Expo SDK 54, Expo Router (stack), Reanimated + gesture-handler, expo-image, expo-haptics, expo-secure-store.
- **Backend**: FastAPI + Motor (MongoDB async), bcrypt, httpx.

## Features
- **Auth**: Emergent Google OAuth + admin email/senha.
- **Mapa cósmico**: fundo com estrelas + nebulosas discretas; grade 20×20 com pan/pinch-zoom; 5 estados coloridos (disponível / criado / à venda / seu / seu-à-venda).
- **Sheet do universo**: `UNIVERSO #N`, status, preço, coordenadas, fundador, data — botão **Comprar Universo** / **Visitar Universo**.
- **Fluxo de compra**: saldo debitado + animação de luz dourada varrendo a tela + card "🌌 Parabéns! Você acaba de fundar um novo universo. Agora este espaço faz parte do Multiverso PixelLand." + wizard opcional (nome / capa / descrição).
- **Página do universo**: `UNIVERSO #N`, Fundador, Preço, Criado em, descrição, link externo, galeria, cor de tema (aplica accent), histórico de transações, marketplace (listar / vender / comprar-revenda com 10% fee).
- **Perfil**: avatar, nome, e-mail, coins, universos, **Data de entrada**, atalho leaderboard.
- **Leaderboard**: top 50 landlords com medalhas ouro/prata/bronze.
- **Admin**: tabs Users/Pixels + botão **Resetar Mapa** (limpa ownership, listings e personalizações).

## Design
- Dark-First Utility: `#0F1115` fundo, accent **ciano `#00E5FF`** + **dourado `#FFD700`** como segundo destaque (à-venda, medalhas, celebração).
- Estrelas + nebulosas discretas em cyan/gold/magenta reforçam a sensação de "observar o multiverso".
- UI 100% PT-BR.

## API Surface (`/api`)
Auth, pixels CRUD, buy primary, marketplace (list/unlist/buy-resale), transactions, listings, leaderboard, profile pixels, admin (users, pixels, **reset-map**).

## Credenciais
- Admin: `admin@pixelland.com` / `Apollo2122@×+>×>adm00140`
- Google user starts with 1000 coins. Admin com 99 999 coins.
- Preços: `[5, 10, 20, 30, 40, 50, 100]`. Fee marketplace: 10%.

## Tests
- Iter 1: 21/21 · Iter 2: 14/14 backend passando.
