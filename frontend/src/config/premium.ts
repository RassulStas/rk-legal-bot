// Single source of truth for the SmartLawyer Premium offer. The Kaspi routing
// number is stored reversed and only un-reversed at copy time: the raw digits
// never appear verbatim in the JS bundle, which defeats naive phone scrapers.

export const PREMIUM_PLAN = {
  planName: 'SmartLawyer Premium',
  priceLabel: '9,900 ₸ / месяц',
  features: [
    'Безлимитные ИИ-консультации по 6 кодексам РК (Трудовой, Гражданский, Налоговый, Предпринимательский, Земельный и КоАП).',
    'Автоматический анализ рисков в договорах (загрузка файлов).',
    'Генерация юридических документов, актов и досудебных претензий.',
  ],
} as const

// The display-formatted number was removed intentionally — users never see the
// raw requisites; both platforms receive them via clipboard instead.
const KASPI_PHONE_REVERSED = '33935755077'

export function getKaspiPhone(): string {
  return [...KASPI_PHONE_REVERSED].reverse().join('')
}

// Checkout card copy, split by surface. Mobile gets a single prominent
// action; desktop gets the corporate explainer plus a requisites button.
export const CHECKOUT_COPY = {
  title: 'Активация подписки SmartLawyer Premium',
  mobileButton: 'Перейти к оплате в Kaspi.kz',
  desktopLead:
    'Для активации Premium-доступа совершите платёж 9,900 ₸ на верифицированный счёт Администрации сервиса через Kaspi.kz (Переводы -> Клиенту Kaspi).',
  desktopButton: 'Получить реквизиты для быстрой оплаты',
  toast: 'Реквизиты скопированы! Вставьте их в поле перевода в Kaspi.',
  note: 'После подтверждения транзакции введите ваш номер телефона ниже. Доступ к безлимитному анализу кодексов и договоров будет активирован автоматически в течение 60 секунд.',
} as const
