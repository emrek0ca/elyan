FROM node:22-bookworm-slim

WORKDIR /app

# gcc + C standard headers for C NLP core
RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc libc6-dev \
 && rm -rf /var/lib/apt/lists/*

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build && npm prune --omit=dev

# Compile the C NLP daemon
RUN mkdir -p bin \
 && gcc -O2 -Wall -o bin/elyan_nlp src/native/elyan_nlp.c -lm

EXPOSE 4000

CMD ["node", "dist/index.js"]
