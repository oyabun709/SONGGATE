/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone", // required for the Docker multi-stage build
  reactStrictMode: true,
  experimental: {
    serverActions: {
      allowedOrigins: ["localhost:3000"],
    },
  },
};

module.exports = nextConfig;
