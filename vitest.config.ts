import path from 'node:path';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  resolve: {
    alias: {
      '@renderer': path.resolve(__dirname, 'src/renderer'),
      '@shared': path.resolve(__dirname, 'src/shared'),
      '@preload': path.resolve(__dirname, 'src/preload'),
      '@main': path.resolve(__dirname, 'src/main'),
    },
  },
  test: {
    environment: 'jsdom',
    include: ['tests/electron/**/*.test.ts', 'tests/electron/**/*.test.tsx'],
    setupFiles: ['tests/electron/setup.ts'],
  },
});
