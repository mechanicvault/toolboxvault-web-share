# Build the React app, then serve the static files with nginx.
FROM node:20-slim AS build
WORKDIR /app
# Copy BOTH package files first so npm ci installs exactly the locked
# dependency tree (npm install would re-resolve ranges on every build).
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
# The nginx image envsubst's *.template files in /etc/nginx/templates/
# on startup, filling ${APP_DOMAIN} / ${FILES_DOMAIN} from the environment.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
