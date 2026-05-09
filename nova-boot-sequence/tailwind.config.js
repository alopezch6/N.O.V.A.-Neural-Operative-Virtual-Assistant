/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        nova: {
          bg:     "#04000f",
          cyan:   "#22d3ee",
          violet: "#a855f7",
          bright: "#c084fc",
          pink:   "#e879f9",
          green:  "#4ade80",
          orange: "#fb923c",
        },
      },
      fontFamily: {
        orbitron: ["Orbitron", "sans-serif"],
        mono:     ["Share Tech Mono", "monospace"],
      },
    },
  },
  plugins: [],
};
