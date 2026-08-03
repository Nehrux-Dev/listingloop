FROM node:22-alpine

ENV NODE_ENV=development

WORKDIR /app

# Install dependencies first so the layer is cached across source changes.
COPY package.json package-lock.json* ./
RUN npm install

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev"]
