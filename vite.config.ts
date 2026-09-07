import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    watch: {
      // The WhatsApp bridge keeps a live Chrome profile under
      // whatsapp/.sessions/. Windows holds an exclusive lock on files like
      // Default/Network/Cookies, so the dev server dies with
      // `EBUSY: resource busy or locked, watch ...` the moment it tries to
      // watch them. Nothing under these paths is a frontend source anyway.
      ignored: ['**/whatsapp/**', '**/backend/**'],
    },
  },
})
