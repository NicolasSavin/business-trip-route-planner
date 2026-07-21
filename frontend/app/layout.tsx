import type { Metadata } from 'next';
import type { ReactNode } from 'react';
import './globals.css';

export const metadata: Metadata = {
  title: 'Business Trip Planner',
  description: 'Современный SaaS-интерфейс поиска маршрутов для командировок по России',
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ru">
      <body>
        {children}
        <div className="border-t border-line bg-white px-5 py-4 text-center text-xs text-muted sm:px-8">
          Данные о расписании предоставлены сервисом{' '}
          <a
            href="https://rasp.yandex.ru/"
            target="_blank"
            rel="noopener noreferrer"
            className="font-semibold text-brand underline decoration-brand/30 underline-offset-4 transition hover:decoration-brand"
          >
            Яндекс Расписания
          </a>
          . Наличие мест проверяется отдельными источниками и может быть не подтверждено.
        </div>
      </body>
    </html>
  );
}
