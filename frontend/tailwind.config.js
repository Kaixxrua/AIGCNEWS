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
        /* ═══ 科技感色系 Token（暖科技 Glassmorphism 2.0） ═══ */
        tech: {
          primary: '#06b6d4',     /* cyan-500 — 主科技色 */
          'primary-light': '#67e8f9', /* cyan-300 */
          secondary: '#8b5cf6',   /* violet-500 — 辅助科技色 */
          'secondary-light': '#c4b5fd', /* violet-300 */
          glow: 'rgba(6, 182, 212, 0.15)', /* cyan 发光底色 */
        },
        /* ═══ 来源徽章分色 ═══ */
        source: {
          arxiv: '#3b82f6',       /* blue-500 */
          'arxiv-bg': 'rgba(59, 130, 246, 0.08)',
          github: '#64748b',      /* slate-500 */
          'github-bg': 'rgba(100, 116, 139, 0.08)',
          news: '#f59e0b',        /* amber-500 */
          'news-bg': 'rgba(245, 158, 11, 0.08)',
          neo4j: '#8b5cf6',       /* violet-500 */
          'neo4j-bg': 'rgba(139, 92, 246, 0.08)',
          milvus: '#06b6d4',      /* cyan-500 */
          'milvus-bg': 'rgba(6, 182, 212, 0.08)',
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
        /* 科技感发光阴影 */
        'glow-sm': '0 0 12px rgba(6, 182, 212, 0.08)',
        'glow-md': '0 0 24px rgba(6, 182, 212, 0.12)',
        'glow-lg': '0 0 40px rgba(6, 182, 212, 0.15)',
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
        'shimmer': 'shimmer 2s ease-in-out infinite',
        'progress-indeterminate': 'progressIndeterminate 1.5s ease-in-out infinite',
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
        shimmer: {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
        progressIndeterminate: {
          '0%': { transform: 'translateX(-100%)' },
          '50%': { transform: 'translateX(0%)' },
          '100%': { transform: 'translateX(100%)' },
        },
      },
    },
  },
  plugins: [],
}
