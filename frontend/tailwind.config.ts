import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        border: "#34414C",
        base: {
          bg: "#101820",        // main background
          sidebar: "#121C25",   // sidebar
          card: "#18232D",      // card background
          panel: "#202E39",     // secondary panel
          border: "#34414C",
        },
        teal: {
          DEFAULT: "#16B8A6",
          soft: "rgba(22, 184, 166, 0.12)",
        },
        info: "#60A5FA",
        ok: "#22C55E",
        warn: "#F59E0B",
        danger: "#EF4444",
        fg: {
          DEFAULT: "#E5E7EB",
          muted: "#94A3B8",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
      borderColor: {
        DEFAULT: "#34414C",
      },
    },
  },
  plugins: [],
} satisfies Config;
