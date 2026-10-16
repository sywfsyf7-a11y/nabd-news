/** Build-only Tailwind config. The browser receives the compiled CSS, never the Play CDN runtime. */
module.exports = {
  content: ["./templates/**/*.html"],
  safelist: ["hidden", "animate-spin"],
  theme: {
    extend: {
      colors: {
        ink: "#111827",
        paper: "#F7F7F5",
        pulse: "#E53945",
        muted: "#64748B",
      },
      boxShadow: {
        soft: "0 16px 45px rgba(15, 23, 42, 0.07)",
      },
    },
  },
  plugins: [],
};
