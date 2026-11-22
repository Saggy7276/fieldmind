/* global process */
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// GitHub Pages serves the site from https://<user>.github.io/fieldmind/,
// so production assets need that prefix. Local dev stays at "/".
export default defineConfig(({ command, isPreview }) => ({
  base: command === 'build' || isPreview ? (process.env.BASE_PATH || '/fieldmind/') : '/',
  plugins: [react()],
  // transformers.js ships its own WASM/ONNX loader; don't pre-bundle it in dev
  optimizeDeps: { exclude: ['@huggingface/transformers'] },
}))
