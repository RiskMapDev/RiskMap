import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /*
    `standalone` собирает серверную часть вместе с нужными модулями в
    `.next/standalone`. Нужен образу контейнера: без него в образ пришлось бы
    класть весь `node_modules`, а это сотни мегабайт зависимостей сборки,
    которые в рантайме не используются.

    На локальный запуск через `next start` режим не влияет.
  */
  output: "standalone",
};

export default nextConfig;
