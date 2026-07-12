# Production build for the Vite frontend.
#
# WHY THIS EXISTS: Vite inlines every `VITE_*` variable into the JS bundle at
# BUILD TIME (they are literal strings in the output, never read from a `.env`
# at runtime). A hosted static build therefore cannot "read the server's .env" —
# the API URL must be supplied when `vite build` runs, via the build args below.
# `.env` files are excluded from the image (see .dockerignore) so a developer's
# local `frontend/.env` can never leak into a production build.
#
# On Railway (Dockerfile build), declared ARGs are populated from the service's
# variables automatically — set VITE_API_BASE_URL (and VITE_STORE_KEY) there.
#   Local build example:
#   docker build -t madhats-frontend \
#     --build-arg VITE_API_BASE_URL=https://your-backend.example.com \
#     --build-arg VITE_STORE_KEY=mh_pk_yourstore ./frontend

# ---- Build stage ----------------------------------------------------------
FROM node:20-slim AS build
WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .

# Build-time configuration. Defaults mirror the app's own code fallbacks so an
# un-configured build behaves like local dev rather than pointing nowhere.
ARG VITE_API_BASE_URL=http://localhost:8000
ARG VITE_STORE_KEY=
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV VITE_STORE_KEY=$VITE_STORE_KEY

RUN npm run build

# ---- Runtime stage --------------------------------------------------------
# Serve the static bundle. `serve -s` provides SPA history fallback so deep
# links (e.g. /admin/hat-types/:id) resolve to index.html.
FROM node:20-slim AS runtime
WORKDIR /app

RUN npm install -g serve@14

COPY --from=build /app/dist ./dist

# Railway (and most PaaS) inject the listening port via $PORT.
ENV PORT=4173
EXPOSE 4173
CMD ["sh", "-c", "serve -s dist -l tcp://0.0.0.0:${PORT:-4173}"]
