import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Интерактивная карта рисков",
  description:
    "Информационно-аналитическая система оценки социально-экономических " +
    "и криминогенных рисков в регионе.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f1f5f9" },
    { media: "(prefers-color-scheme: dark)", color: "#0b1220" },
  ],
};

/*
  Тема применяется до первой отрисовки, иначе при загрузке успевает мелькнуть
  светлый экран, а затем страница перекрашивается в тёмную. Скрипт намеренно
  синхронный и встроенный: любой асинхронный вариант выполнится уже после
  первого кадра, то есть ровно после того момента, ради которого он нужен.

  Скрипт не читает и не отправляет ничего, кроме собственной настройки темы.
*/
const themeScript = `
(function () {
  try {
    var stored = localStorage.getItem('riskmap-theme');
    var prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    var theme = stored || (prefersDark ? 'dark' : 'light');
    document.documentElement.setAttribute('data-theme', theme);
  } catch (e) {
    document.documentElement.setAttribute('data-theme', 'light');
  }
})();
`;

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    /*
      lang="ru" — не косметика: от него зависят перенос слов, произношение в
      скринридерах и выбор словаря проверки орфографии. Интерфейс русский,
      архитектура готова к казахскому, поэтому значение будет браться из
      настройки локали, когда появится второй язык.
    */
    /*
      suppressHydrationWarning здесь обязателен и точечен. Сервер не знает
      настройку темы конкретного пользователя и всегда отдаёт «light», а
      встроенный скрипт ниже успевает поменять атрибут до гидратации. React
      видит расхождение и предупреждает — но расхождение здесь намеренное и
      составляет всю суть приёма: без него вместо предупреждения в консоли
      пользователь получил бы вспышку светлого экрана.

      Подавление действует ровно на атрибуты этого узла и не распространяется
      на дерево ниже, поэтому настоящие ошибки гидратации в приложении
      останутся видимыми.
    */
    <html lang="ru" data-theme="light" className="h-full" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="min-h-full">
        {/* Ссылка для навигации с клавиатуры: позволяет пропустить меню. */}
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-accent focus:px-4 focus:py-2 focus:text-accent-fg"
        >
          Перейти к содержимому
        </a>
        {children}
      </body>
    </html>
  );
}
