# Base stage
FROM node:20-alpine AS base
WORKDIR /app
COPY package*.json ./
RUN npm ci

# Development stage
FROM base AS dev
# Expose default Vite port
EXPOSE 5173
# Command to run dev server, binding to all interfaces
CMD ["npm", "run", "dev", "--", "--host"]

# Build stage
FROM base AS build
COPY . .
RUN npm run build

# Production stage
FROM nginx:alpine AS prod

# Copy build artifacts
COPY --from=build /app/dist /usr/share/nginx/html

# Copy custom nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Configure permissions for non-root user
# Nginx alpine image uses 'nginx' user (uid 101)
# We need to ensure it can write to cache/pid directories if they are used,
# though with standard config it might write to /var/run which is root owned.
# More commonly we just need to ensure it can read the static files (which it can)
# and bind to the port (which is now 8080).

# Update nginx.conf to use /tmp for pid/cache if strictly necessary,
# but usually just changing the port is enough for the main process
# if we don't need to write to system paths.
# However, standard nginx image tries to write to /var/cache/nginx and /var/run/nginx.pid
RUN chown -R nginx:nginx /var/cache/nginx && \
    chown -R nginx:nginx /var/log/nginx && \
    chown -R nginx:nginx /etc/nginx/conf.d && \
    touch /var/run/nginx.pid && \
    chown -R nginx:nginx /var/run/nginx.pid

# Switch to non-root user
USER nginx

EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
