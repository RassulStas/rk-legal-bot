// Single source of truth for the SmartLawyer Premium offer — edit the Kaspi
// business phone here and every UI surface (guide text, copy button) updates.
export const PREMIUM_PLAN = {
  planName: 'SmartLawyer Premium',
  priceLabel: '9,900 ₸ / месяц',
  kaspiPhoneDisplay: '+7 (7XX) XXX-XX-XX',
  features: [
    'Безлимитные ИИ-консультации по 6 кодексам РК (Трудовой, Гражданский, Налоговый, Предпринимательский, Земельный и КоАП).',
    'Автоматический анализ рисков в договорах (загрузка файлов).',
    'Генерация юридических документов, актов и досудебных претензий.',
  ],
} as const

export function premiumGuideText(phoneDisplay: string): string {
  return (
    `Для активации Premium-доступа переведите 9,900 ₸ через приложение Kaspi.kz ` +
    `(Переводы) по номеру телефона: ${phoneDisplay} (Рабочий номер SmartLawyer)`
  )
}
