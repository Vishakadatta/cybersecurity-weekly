import { defineConfig } from 'astro/config';
import tailwind from '@astrojs/tailwind';

export default defineConfig({
  site: 'https://vishakadatta.github.io',
  base: '/cybersecurity-weekly/',
  output: 'static',
  integrations: [tailwind()],
});
