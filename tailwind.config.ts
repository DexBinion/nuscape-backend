import type { Config } from 'tailwindcss'

export default {
  darkMode: 'class',
  content: [
    './index.html',
    './src/**/*.{ts,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        base: {
          bg: '#0B0D12', // page background
          card: '#111319', // card background
          stroke: '#1B202A', // subtle borders
          text: '#E5E7EB', // primary text
          mute: '#9CA3AF', // secondary text
          accent: '#7C3AED' // purple accent
        }
      },
      borderRadius: {
        'xl': '1rem',
        '2xl': '1.25rem'
      },
      boxShadow: {
        soft: '0 6px 24px rgba(0,0,0,0.35)'
      }
    }
  },
  plugins: [require('@tailwindcss/forms')],
} satisfies Config

