# Production build for the Vite frontend.
#
# WHY THIS IS ODD: Vite inlines every `VITE_*` variable into the JS bundle at
# BUILD TIME (they are literal strings in the output, never read from a `.env`
# at runtime), which would lock a built image to a single API URL — unusable for
# an image pushed to a registry and deployed to more than one environment.
#
# So the build bakes PLACEHOLDER SENTINELS, and `docker-entrypoint.sh` swaps
# them for real values from the container's environment at START time. The
# resulting image is environment-agnostic:
#
#   docker build -t madhats-frontend ./frontend          # no build args needed
#   docker run -e VITE_API_BASE_URL=https://api.madhats.getaiconsult.com.au \
#              -e VITE_STORE_KEY=mh_pk_madhats_local madhats-frontend
#
# `.env` files are excluded from the image (see .dockerignore) so a developer's
# local `frontend/.env` can never leak into a production build.

# ---- Build stage ----------------------------------------------------------
FROM node:20-slim AS build
WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .

# Placeholder sentinels, NOT real configuration. Vite inlines these literal
# strings into the bundle; docker-entrypoint.sh replaces them at container start.
#
# They are `ARG`s rather than hardcoded so a one-off image CAN still be pinned at
# build time if ever needed (`--build-arg VITE_API_BASE_URL=https://…`) — the
# entrypoint then finds no sentinel and substitutes nothing. Do not do this for
# images pushed to a registry: it silently reintroduces the single-environment
# lock-in this whole arrangement exists to remove.
#
# A real URL must never become the default here. An empty default is equally
# wrong: Vite would inline `""`, and the app's `?? 'http://localhost:8000'`
# fallback is nullish-only, so every call would hit a relative path on the static
# server and 404.
ARG VITE_API_BASE_URL=__RUNTIME_API_BASE_URL__
ARG VITE_STORE_KEY=__RUNTIME_STORE_KEY__
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV VITE_STORE_KEY=$VITE_STORE_KEY

RUN npm run build

# ---- Runtime stage --------------------------------------------------------
# Serve the static bundle. `serve -s` provides SPA history fallback so deep
# links (e.g. /admin/hat-types/:id) resolve to index.html.
FROM node:20-slim AS runtime
WORKDIR /app

RUN npm install -g serve@14

# The bundle is kept PRISTINE here and copied to ./dist by the entrypoint on
# every start. Serving this directory directly would serve the raw sentinels.
COPY --from=build /app/dist ./dist-template

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Serve on 5173 (the port this project's frontend has always used, so it drops
# straight into the existing docker-compose port mapping / reverse proxy).
EXPOSE 5173
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["serve", "-s", "dist", "-l", "tcp://0.0.0.0:5173"]
