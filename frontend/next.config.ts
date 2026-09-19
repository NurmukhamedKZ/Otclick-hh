import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Keep the production image small: Next traces only the runtime files needed
  // by server.js instead of shipping the full source tree and node_modules.
  output: "standalone",
};

export default nextConfig;
