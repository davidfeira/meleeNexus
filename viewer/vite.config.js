import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  // Use relative base path for Electron compatibility
  base: './',
  server: {
    port: 3000,
    open: false, // Don't auto-open browser in Electron mode
    proxy: {
      // Proxy /api requests to Flask backend
      '/api': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true
      },
      // Proxy /storage requests to Flask backend (single source of truth)
      '/storage': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true
      },
      // Proxy /vanilla requests to Flask backend for vanilla assets
      '/vanilla': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true
      }
    },
    fs: {
      // Allow serving files from the parent directory
      allow: ['..']
    }
  },
  build: {
    outDir: 'dist',
    // Generate sourcemaps for easier debugging
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks: undefined
      }
    }
  },
  resolve: {
    alias: {
      '@storage': path.resolve(__dirname, '../storage')
    }
  },
  publicDir: 'public'
})
