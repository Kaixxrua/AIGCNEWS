/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{vue,js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      /* 注意：下列自定义族为 plain var()——禁止对 paper/surface/ink/accent/rule/border
         使用 /alpha 透明度修饰符（Tailwind v3 无法解析 var() 颜色，会静默丢弃声明）。
         需要透明度时用 stone 或 card 色族（RGB 三元组，支持透明度修饰）。 */
      colors: {
        paper: {
          DEFAULT: 'var(--paper)',
          raised: 'var(--paper-raised)',
          muted: 'var(--paper-muted)',
        },
        surface: {
          DEFAULT: 'var(--paper-raised)',
          subtle: 'var(--paper)',
          muted: 'var(--paper-muted)',
        },
        border: {
          DEFAULT: 'var(--rule)',
          strong: 'var(--rule-strong)',
        },
        rule: {
          DEFAULT: 'var(--rule)',
          strong: 'var(--rule-strong)',
        },
        ink: {
          DEFAULT: 'var(--ink)',
          secondary: 'var(--ink-secondary)',
          muted: 'var(--ink-muted)',
          faint: 'var(--ink-faint)',
          solid: 'var(--ink-solid)',
          'solid-hover': 'var(--ink-solid-hover)',
          'on-solid': 'var(--ink-on-solid)',
        },
        accent: {
          DEFAULT: 'var(--acid)',
          soft: 'var(--acid-soft)',
          hover: 'var(--acid-strong)',
          ink: 'var(--acid-ink)',
        },
        /* 毛玻璃卡片色（RGB 三元组，支持 bg-card/70 等透明度修饰） */
        card: 'rgb(var(--card-rgb) / <alpha-value>)',
        /* stone 阶改由 CSS 变量驱动（深浅主题各自定义，浅色 = 原 stone 阶逐像素等价） */
        stone: {
          50: 'rgb(var(--stone-50-rgb) / <alpha-value>)',
          100: 'rgb(var(--stone-100-rgb) / <alpha-value>)',
          200: 'rgb(var(--stone-200-rgb) / <alpha-value>)',
          300: 'rgb(var(--stone-300-rgb) / <alpha-value>)',
          400: 'rgb(var(--stone-400-rgb) / <alpha-value>)',
          500: 'rgb(var(--stone-500-rgb) / <alpha-value>)',
          600: 'rgb(var(--stone-600-rgb) / <alpha-value>)',
          700: 'rgb(var(--stone-700-rgb) / <alpha-value>)',
          800: 'rgb(var(--stone-800-rgb) / <alpha-value>)',
          900: 'rgb(var(--stone-900-rgb) / <alpha-value>)',
          950: 'rgb(var(--stone-950-rgb) / <alpha-value>)',
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
        control: '0.5rem',
        module: '0.75rem',
        '2xl': '0.75rem',
        '3xl': '1rem',
        '4xl': '1.25rem',
      },
      boxShadow: {
        card: '1px 1px 0 rgba(21,21,18,0.08)',
        'card-md': '2px 2px 0 rgba(21,21,18,0.12)',
        'card-lg': '4px 4px 0 #151512',
        'inner-sm': 'inset 0 0 0 1px rgba(21,21,18,0.06)',
        'glow-sm': '2px 2px 0 rgba(21,21,18,0.10)',
        'glow-md': '3px 3px 0 rgba(21,21,18,0.14)',
        'glow-lg': '5px 5px 0 #d8f14b',
      },
      fontFamily: {
        sans: ['"DM Sans"', '"PingFang SC"', '"Microsoft YaHei"', 'system-ui', 'sans-serif'],
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
