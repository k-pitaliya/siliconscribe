import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        // Vendor code changes rarely; keeping it in its own files means a deploy of app code does
        // not make browsers re-download the editor, and no single chunk is over 500 kB.
        manualChunks(id: string) {
          if (!id.includes('node_modules')) return undefined
          if (id.includes('@codemirror') || id.includes('@lezer') || id.includes('@uiw') || id.includes('codemirror')) return 'editor'
          if (id.includes('react')) return 'react'
          return undefined
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
  },
})
