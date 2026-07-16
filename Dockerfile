FROM node:22-bookworm-slim

WORKDIR /app

# gcc + C standard headers for C NLP core
RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc libc6-dev \
 && rm -rf /var/lib/apt/lists/*

COPY package.json package-lock.json ./
RUN npm ci

# Keep semantic understanding off the request critical path. The multilingual
# e5 model is prepared once while the image is built; production workers then
# fail fast to the existing safe fallback if that immutable artifact is ever
# missing instead of downloading hundreds of MB during a user's first turn.
ENV ELYAN_SEMANTIC_MODEL_CACHE_DIR=/app/.semantic-model-cache
ENV ELYAN_SEMANTIC_MODEL_REVISION=761b726dd34fb83930e26aab4e9ac3899aa1fa78
RUN node --input-type=module -e "import { env, pipeline } from '@huggingface/transformers'; env.cacheDir = process.env.ELYAN_SEMANTIC_MODEL_CACHE_DIR; const extractor = await pipeline('feature-extraction', 'Xenova/multilingual-e5-small', { device: 'cpu', dtype: 'q8', revision: process.env.ELYAN_SEMANTIC_MODEL_REVISION }); await extractor('passage: Elyan semantic capability readiness', { pooling: 'mean', normalize: true });"
ENV ELYAN_SEMANTIC_MODEL_LOCAL_ONLY=true

COPY . .
RUN npm run build \
 && npm prune --omit=dev \
 && test -s /app/.semantic-model-cache/Xenova/multilingual-e5-small/761b726dd34fb83930e26aab4e9ac3899aa1fa78/onnx/model_quantized.onnx

# Compile the C NLP daemon
RUN mkdir -p bin \
 && gcc -O2 -Wall -o bin/elyan_nlp src/native/elyan_nlp.c -lm

EXPOSE 4000

CMD ["node", "dist/index.js"]
