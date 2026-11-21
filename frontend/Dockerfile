# Build the React app, then serve the static files with nginx.
# Base images are pinned to an exact version + digest, the same way
# PostgreSQL is pinned in docker-compose.yml, so a routine deploy can
# never silently pick up a different Node or nginx. To move up: point
# the tag at the new version and replace the digest with that tag's
# current index digest.
FROM node:20.20.2-slim@sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0 AS build
WORKDIR /app
# Copy BOTH package files first so npm ci installs exactly the locked
# dependency tree (npm install would re-resolve ranges on every build).
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.31-alpine@sha256:0563c36f94a6d3ec3584161b77859f740f7e20b4853f52c796a864ce6908e8ea
# The nginx image envsubst's *.template files in /etc/nginx/templates/
# on startup, filling ${APP_DOMAIN} / ${FILES_DOMAIN} from the environment.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY security-headers.conf.template /etc/nginx/templates/security-headers.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
