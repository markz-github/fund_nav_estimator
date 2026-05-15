FROM node:22-alpine AS build

WORKDIR /app

ARG VITE_APP_BASE_PATH=/fund-nav-estimator/
ARG VITE_API_BASE_URL
ENV VITE_APP_BASE_PATH=${VITE_APP_BASE_PATH}
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build
