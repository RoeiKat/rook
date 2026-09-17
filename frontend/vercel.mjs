const apiProxyTarget = process.env.API_PROXY_TARGET?.trim().replace(/\/+$/, "");

if (!apiProxyTarget) {
  throw new Error("API_PROXY_TARGET must contain the public backend origin");
}

export const config = {
  framework: "vite",
  rewrites: [
    { source: "/api/:path*", destination: `${apiProxyTarget}/api/:path*` },
    { source: "/health", destination: `${apiProxyTarget}/health` },
    { source: "/(.*)", destination: "/index.html" },
  ],
};
