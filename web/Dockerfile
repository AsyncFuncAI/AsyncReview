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
COPY --from=build /app/dist /usr/share/nginx/html
# We will copy a custom nginx config to handle SPA routing and API proxying
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
