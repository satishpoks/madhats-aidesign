# Production build for the Vite frontend.
#
# WHY THIS EXISTS: Vite inlines every `VITE_*` variable into the JS bundle at
# BUILD TIME (they are literal strings in the output, never read from a `.env`
# at runtime). A hosted static build therefore cannot "read the server's .env" —
# the API URL must be supplied when `vite build` runs, via the build args below.
# `.env` files are excluded from the image (see .dockerignore) so a developer's
# local `frontend/.env` can never leak into a production build.
#
# Pass the config as build args when building the image, e.g.:
#   docker build -t madhats-frontend \
#     --build-arg VITE_API_BASE_URL=http://madhats.getaiconsult.com.au:8000 \
#     --build-arg VITE_STORE_KEY=mh_pk_madhats_local ./frontend

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

# Serve on 5173 (the port this project's frontend has always used, so it drops
# straight into the existing docker-compose port mapping / reverse proxy).
EXPOSE 5173
CMD ["serve", "-s", "dist", "-l", "tcp://0.0.0.0:5173"]
