import type { NextConfig } from 'next';

// Dayline's preview serves the app under BASE_PATH; empty when run elsewhere.
const basePath = process.env.BASE_PATH ?? '';
const api = process.env.API_URL ?? 'http://127.0.0.1:4000';

const nextConfig: NextConfig = {
  basePath,
  env: { NEXT_PUBLIC_BASE_PATH: basePath },
  // Dependencies are installed outside the project (in the sandbox image).
  turbopack: { root: '/' },
  // The browser only talks to Next; Next forwards /api/* to the Nest API.
  async rewrites() {
    return [{ source: '/api/:path*', destination: `${api}/:path*` }];
  },
};

export default nextConfig;
