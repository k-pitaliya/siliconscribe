import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  resolve: {
    // netlistsvg imports elkjs' Node entry, which has an optional require('webworker-threads') the browser
    // bundler cannot resolve; the self-contained browser build of the same version has none.
    alias: [{ find: /^elkjs$/, replacement: 'elkjs/lib/elk.bundled.js' }],
  },
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
    strictPort: true, // fail loudly if 5173 is taken, instead of silently serving on 5174 while 5173 shows an old build
    proxy: {
      '/api': 'http://127.0.0.1:8000',   // the backend binds 127.0.0.1 only; "localhost" may resolve to ::1 first
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
  },
})
