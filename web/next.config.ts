import type { NextConfig } from "next";

// Proxy /api/* to the Python (AXON) backend so the browser never hits CORS.
const AXON_API = process.env.AXON_API ?? "http://127.0.0.1:8765";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${AXON_API}/:path*` }];
  },
};

export default nextConfig;
