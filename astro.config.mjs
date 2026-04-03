import { defineConfig } from 'astro/config';
import tailwind from '@astrojs/tailwind';

export default defineConfig({
  site: 'https://vishakadatta.github.io',
  base: '/cybersecurity-weekly',
  integrations: [tailwind()],
  output: 'static',
});
