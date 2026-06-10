import { defineConfig } from 'astro/config';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  site: 'https://vishakadatta.github.io',
  base: '/cybersecurity-weekly/',
  output: 'static',
  vite: {
    plugins: [tailwindcss()],
  },
});
