/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0d0f12",
        panel: "#171a1f",
        panel2: "#1f242b",
        border: "#2a313a",
        muted: "#8a93a3",
      },
    },
  },
  plugins: [],
};
