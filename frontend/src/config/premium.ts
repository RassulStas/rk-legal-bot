// Single source of truth for the SmartLawyer Premium offer — edit the Kaspi
// business phone here and every UI surface (guide text, copy button) updates.
export const PREMIUM_PLAN = {
  planName: 'SmartLawyer Premium',
  priceLabel: '9,900 ₸ / месяц',
  // Canonical digits — what "Скопировать номер" puts on the clipboard.
  kaspiPhone: '+77055753933',
  kaspiPhoneDisplay: '+7 (705) 575-39-33',
  features: [
    'Безлимитные ИИ-консультации по 6 кодексам РК (Трудовой, Гражданский, Налоговый, Предпринимательский, Земельный и КоАП).',
    'Автоматический анализ рисков в договорах (загрузка файлов).',
    'Генерация юридических документов, актов и досудебных претензий.',
  ],
} as const

// Payment instructions for the checkout step. Kept as separate blocks
// (title / lead / note) because the modal renders them as distinct paragraphs —
// a single template string would collapse the intended line breaks.
export const PREMIUM_GUIDE = {
  title: 'Активация подписки SmartLawyer Premium',
  lead:
    'Оплата услуг производится в ручном режиме. Пожалуйста, совершите платёж в размере ' +
    '9,900 ₸ через мобильный банкинг Kaspi.kz ➔ Переводы ➔ Клиенту Kaspi на ' +
    'верифицированный счет Администрации сервиса:',
  note:
    'После подтверждения транзакции введите ваш номер телефона ниже. Доступ к безлимитному ' +
    'анализу кодексов и договоров будет активирован автоматически в течение 60 секунд.',
} as const
