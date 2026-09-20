import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  async rewrites() {
    return [
      {
        source: "/dsh-proxy/:path*",
        destination: "http://127.0.0.1:8010/api/dsh-proxy/:path*",
      },
    ];
  },
};

export default nextConfig;
