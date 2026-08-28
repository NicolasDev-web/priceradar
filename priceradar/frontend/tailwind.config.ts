import type { Config } from 'tailwindcss'

const config: Config = {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        mrv: {
          // Brand primário
          green: '#0B5A42',
          'green-light': '#0D6B4F',
          'green-dark': '#083D2D',
          orange: '#F39200',
          'orange-light': '#F5A623',
          'orange-dark': '#D97F00',
          // Superfícies dark
          base: '#070F0B',        // fundo principal — preto com toque verde profundo
          surface: '#0D1F17',     // cards, painéis
          'surface-2': '#142B1E', // hover, borda elevada
          'surface-3': '#1C3828', // hover mais pronunciado
          border: '#1A3D2C',      // bordas e separadores
          'border-bright': '#2A5940', // bordas em foco
          // Texto sobre dark
          text: '#DFF0E8',        // texto principal (off-white com toque verde frio)
          'text-muted': '#6B9E88', // labels secundários
          'text-dim': '#3D6B55',  // texto de baixa hierarquia
          // Semânticos de preço
          'price-low': '#34D399',     // abaixo da média — verde esmeralda
          'price-mid': '#F39200',     // na média — laranja MRV
          'price-high': '#F87171',    // acima da média — vermelho suave
          // Acento técnico — cyan frio para dados numéricos
          'data-cyan': '#22D3EE',
          'data-cyan-dim': '#164E63',
          // Legacy
          gray: '#F5F5F5',
          'gray-dark': '#333333',
          'gray-mid': '#888888',
          'gray-border': '#E0E0E0',
        },
      },
      fontFamily: {
        sans: ['Space Grotesk', 'system-ui', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'Consolas', 'monospace'],
        data: ['"IBM Plex Mono"', 'Consolas', 'monospace'],
      },
      borderRadius: {
        card: '6px',
        panel: '8px',
        sm: '4px',
      },
      boxShadow: {
        card: '0 1px 4px rgba(0,0,0,0.5), 0 0 0 1px rgba(26,61,44,0.4)',
        'card-hover': '0 4px 20px rgba(0,0,0,0.6), 0 0 0 1px rgba(11,90,66,0.6)',
        'card-green': '0 0 0 1px rgba(52,211,153,0.25), 0 4px 20px rgba(52,211,153,0.05)',
        'card-red': '0 0 0 1px rgba(248,113,113,0.25), 0 4px 20px rgba(248,113,113,0.05)',
        kpi: '0 2px 8px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.03)',
        'kpi-hero': '0 4px 24px rgba(11,90,66,0.3), inset 0 1px 0 rgba(255,255,255,0.06)',
        glow: '0 0 20px rgba(11,90,66,0.4)',
      },
      backgroundImage: {
        'mrv-gradient': 'linear-gradient(135deg, #0B5A42 0%, #1a7a5c 60%, #F39200 100%)',
        'mrv-gradient-subtle': 'linear-gradient(135deg, #0B5A42 0%, #0D6B4F 100%)',
        'surface-gradient': 'linear-gradient(180deg, #0D1F17 0%, #0A1810 100%)',
        'scanline': 'repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(11,90,66,0.04) 2px, rgba(11,90,66,0.04) 4px)',
        'dot-grid': 'radial-gradient(circle, rgba(11,90,66,0.25) 1px, transparent 1px)',
      },
      backgroundSize: {
        'dot-grid': '20px 20px',
      },
      animation: {
        'pulse-subtle': 'pulse 2.5s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'scan': 'scan 2s ease-in-out infinite',
        'blink': 'blink 1.2s step-end infinite',
        'slide-in': 'slideIn 0.2s ease-out',
        'fade-up': 'fadeUp 0.3s ease-out',
      },
      keyframes: {
        scan: {
          '0%, 100%': { opacity: '0.4' },
          '50%': { opacity: '1' },
        },
        blink: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0' },
        },
        slideIn: {
          from: { opacity: '0', transform: 'translateX(-8px)' },
          to: { opacity: '1', transform: 'translateX(0)' },
        },
        fadeUp: {
          from: { opacity: '0', transform: 'translateY(6px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
      },
    },
  },
  plugins: [],
}

export default config
