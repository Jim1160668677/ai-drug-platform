/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: 'standalone',
  devIndicators: false,
  async rewrites() {
    const backendUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/:path*';
    return [
      {
        source: '/api/:path*',
        destination: backendUrl,
      },
    ];
  },
};

module.exports = nextConfig;
