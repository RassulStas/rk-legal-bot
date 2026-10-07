export type Language = 'kk' | 'ru'

export const DISCLAIMER =
  'Disclaimer: Этот бот предоставляет справочную информацию на основе законодательства РК и не является официальной юридической консультацией.'

export const UI_STRINGS = {
  kk: {
    subtitle: 'Қазақстан Республикасының заңнамасы бойынша AI көмекші',
    inputPlaceholder: 'Заңдық сұрағыңызды жазып жіберіңіз...',
    send: 'Жіберу',
    thinking: 'Ойланып жатыр...',
    welcome:
      'Сәлеметсіз бе! Мен заң саласындағы AI көмекшісімін. Қазақстан Республикасының заңнамасы бойынша сұрақтарыңызға жауап бере аламын. Қалай көмектесе аламын?',
    errorTitle: 'Қате',
    freeTierBadge: 'Тегін режим',
    premiumPendingBadge: 'Premium тексерілуде',
    premiumBadge: 'Premium',
    premiumButton: 'Premium',
    premiumButtonAria: 'SmartLawyer Premium жоспарын ашу',
    attachContract: 'Тәуекелдерді талдау үшін шартты тіркеу (Premium)',
    attachBlocked: 'Файлды талдау Premium жоспарында ғана қолжетімді',
    analyzing: 'Шарт талдануда...',
    analysisTitle: 'Шарт талдамасы',
    fileTooLarge: 'Файл 10 МБ-тан аспауы керек',
  },
  ru: {
    subtitle: 'AI-помощник по законодательству Республики Казахстан',
    inputPlaceholder: 'Задайте ваш юридический вопрос...',
    send: 'Отправить',
    thinking: 'Думаю...',
    welcome:
      'Здравствуйте! Я AI-помощник в сфере права. Могу ответить на ваши вопросы по законодательству Республики Казахстан. Чем могу помочь?',
    errorTitle: 'Ошибка',
    freeTierBadge: 'Бесплатный режим',
    premiumPendingBadge: 'Premium на проверке',
    premiumBadge: 'Premium',
    premiumButton: 'Premium',
    premiumButtonAria: 'Открыть тариф SmartLawyer Premium',
    attachContract: 'Прикрепить договор для анализа рисков (Premium)',
    attachBlocked: 'Анализ файлов доступен в тарифе Premium',
    analyzing: 'Анализирую договор...',
    analysisTitle: 'Анализ договора',
    fileTooLarge: 'Файл должен быть не больше 10 МБ',
  },
} as const

export const LANG_LABELS: Record<Language, string> = {
  kk: 'ҚАЗ',
  ru: 'РУС',
}
