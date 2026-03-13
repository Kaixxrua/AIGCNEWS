/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{vue,js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        surface: {
          DEFAULT: '#ffffff',
          subtle: '#fafaf9',  /* stone-50 */
          muted: '#f5f5f4',   /* stone-100 */
        },
        border: {
          DEFAULT: '#e7e5e4', /* stone-200 */
          strong: '#d6d3d1',  /* stone-300 */
        },
        ink: {
          DEFAULT: '#1c1917', /* stone-900 */
          secondary: '#57534e', /* stone-600 */
          muted: '#78716c',     /* stone-500 */
          faint: '#a8a29e',     /* stone-400 */
        },
        accent: {
          DEFAULT: '#44403c', /* stone-700 */
          hover: '#57534e',   /* stone-600 */
        },
        brand: {
          green: '#22c55e',
          purple: '#a855f7',
          blue: '#3b82f6',
          amber: '#f59e0b',
          rose: '#f43f5e',
          teal: '#14b8a6',
          sky: '#38bdf8',
          lime: '#84cc16',
        },
      },
      borderRadius: {
        '2xl': '1rem',
        '3xl': '1.25rem',
        '4xl': '1.5rem',
      },
      boxShadow: {
        card: '0 1px 3px 0 rgba(0,0,0,0.03), 0 1px 2px -1px rgba(0,0,0,0.02)',
        'card-md': '0 2px 12px 0 rgba(0,0,0,0.03)',
        'card-lg': '0 4px 20px 0 rgba(0,0,0,0.05)',
        'inner-sm': 'inset 0 1px 2px rgba(0,0,0,0.03)',
      },
      fontFamily: {
        sans: ['"Inter"', '"PingFang SC"', '"Helvetica Neue"', 'Arial', 'sans-serif'],
        serif: ['"Playfair Display"', 'Georgia', '"Times New Roman"', 'serif'],
        mono: ['"JetBrains Mono"', '"Fira Code"', 'monospace'],
      },
      fontSize: {
        '2xs': ['0.65rem', { lineHeight: '1rem' }],
      },
      backdropBlur: {
        xs: '2px',
      },
      animation: {
        'fade-in': 'fadeIn 0.2s ease-out',
        'slide-up': 'slideUp 0.25s ease-out',
        'pulse-dot': 'pulseDot 2s ease-in-out infinite',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%': { opacity: '0', transform: 'translateY(8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        pulseDot: {
          '0%, 100%': { transform: 'scale(1)', opacity: '1' },
          '50%': { transform: 'scale(1.4)', opacity: '0.6' },
        },
      },
    },
  },
  plugins: [],
}
