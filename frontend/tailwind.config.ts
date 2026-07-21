import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./app/**/*.{js,ts,jsx,tsx,mdx}', './lib/**/*.{js,ts,jsx,tsx,mdx}'],
  theme: {
    extend: {
      colors: {
        ink: '#111827',
        muted: '#667085',
        line: '#e6eaf0',
        cloud: '#f6f8fb',
        brand: '#0f7bff',
        aqua: '#12b7b5',
      },
      boxShadow: {
        card: '0 24px 80px rgba(15, 23, 42, 0.08)',
        soft: '0 14px 44px rgba(15, 23, 42, 0.06)',
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
};

export default config;
