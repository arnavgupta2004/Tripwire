/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: ["class", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        ink: { DEFAULT: "var(--ink)", soft: "var(--ink-soft)", faint: "var(--ink-faint)" },
        surface: { DEFAULT: "var(--surface)", raised: "var(--surface-raised)", sunken: "var(--surface-sunken)" },
        line: "var(--line)",
        brand: { DEFAULT: "var(--brand)", soft: "var(--brand-soft)" },
        trusted: "var(--trusted)", untrusted: "var(--untrusted)", private: "var(--private)", danger: "var(--danger)",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["'JetBrains Mono'", "ui-monospace", "monospace"],
      },
      boxShadow: { card: "0 1px 2px rgba(16,24,40,0.04), 0 1px 3px rgba(16,24,40,0.08)",
                   drawer: "-8px 0 24px rgba(16,24,40,0.12)" },
      keyframes: {
        pulseRed: { "0%,100%": { opacity: "1" }, "50%": { opacity: "0.35" } },
        slideIn: { from: { transform: "translateX(100%)" }, to: { transform: "translateX(0)" } },
        riseIn: { from: { opacity: "0", transform: "translateY(6px)" }, to: { opacity: "1", transform: "translateY(0)" } },
      },
      animation: { pulseRed: "pulseRed 0.9s ease-in-out 3", slideIn: "slideIn 0.2s ease-out",
                   riseIn: "riseIn 0.22s ease-out" },
    },
  },
  plugins: [],
};
