import type { NextConfig } from "next";
import { requireEnv } from "./env";

const backendUrl = requireEnv("BACKEND_URL");

const nextConfig: NextConfig = {
  output: "standalone",
  experimental: {
    middlewareClientMaxBodySize: 100 * 1024 * 1024, // 100MB for PDF uploads
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },
  webpack: (config) => {
    // Handle canvas for react-pdf
    config.resolve.alias.canvas = false;
    return config;
  },
};

export default nextConfig;
