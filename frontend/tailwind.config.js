/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: { extend: { colors: {
    white: "var(--white)", black: "var(--black)", accent: "var(--accent)", secondary: "var(--secondary)",
  } } },
  plugins: [],
};
