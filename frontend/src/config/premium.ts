// Single source of truth for the SmartLawyer Premium offer. The Kaspi number is
// shown in plain text on the checkout card (owner decision 2026-10-21) so a
// client can read it and copy it by hand even where the clipboard API is
// blocked — mobile in-app browsers from ad clicks deny it often enough that a
// clipboard-only flow was a dead end. The old reversed-digits obfuscation was
// dropped with it: masking protects nothing once the number is rendered.

export const PREMIUM_PLAN = {
  planName: 'SmartLawyer Premium',
  priceLabel: '9,900 ₸ / месяц',
  features: [
    'Безлимитные ИИ-консультации по 6 кодексам РК (Трудовой, Гражданский, Налоговый, Предпринимательский, Земельный и КоАП).',
    'Автоматический анализ рисков в договорах (загрузка файлов).',
    'Генерация юридических документов, актов и досудебных претензий.',
  ],
} as const

// Canonical form — exactly what Kaspi's transfer screen accepts, so the copy
// button can paste it without the client reformatting anything.
export const KASPI_PHONE = '+77055753933'

export const CHECKOUT_COPY = {
  title: 'Активация подписки SmartLawyer Premium',
  requisitesLabel: 'Номер для перевода',
  // One label for both surfaces: the button only ever copied the requisites, so
  // the old mobile wording ("Перейти к оплате в Kaspi.kz") promised a redirect
  // that never happened.
  copyButton: `Скопировать ${KASPI_PHONE}`,
  desktopLead:
    'Для активации Premium-доступа совершите платёж 9,900 ₸ на верифицированный счёт Администрации сервиса через Kaspi.kz (Переводы -> Клиенту Kaspi).',
  toast: 'Номер скопирован! Вставьте его в поле перевода в Kaspi.',
  note: 'После подтверждения транзакции введите ваш номер телефона ниже. Доступ будет активирован сразу после ручного подтверждения перевода Администратором.',
} as const
