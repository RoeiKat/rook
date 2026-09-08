FROM node:22-alpine AS dependencies
WORKDIR /app
COPY package*.json ./
RUN npm install

# Used by docker compose during development: Vite, HMR, and original source files.
FROM dependencies AS development
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev"]

# Optional production image: docker build --target production ./frontend
FROM dependencies AS build
COPY . .
RUN npm run build

FROM nginx:1.27-alpine AS production
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
