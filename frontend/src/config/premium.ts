// Single source of truth for the SmartLawyer Premium offer. Checkout runs
// through Robokassa: the paywall fetches a server-signed payment URL from
// /api/premium/payment-link, so no payment requisites or merchant secrets
// ever live in this bundle.

export const PREMIUM_PLAN = {
  planName: 'SmartLawyer Premium',
  priceLabel: '9,900 ₸ / месяц',
  features: [
    'Безлимитные ИИ-консультации по 6 кодексам РК (Трудовой, Гражданский, Налоговый, Предпринимательский, Земельный и КоАП).',
    'Автоматический анализ рисков в договорах (загрузка файлов).',
    'Генерация юридических документов, актов и досудебных претензий.',
  ],
} as const
