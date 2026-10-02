import io
from docx import Document
from docx.shared import Pt, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH

def generate_legal_document(doc_type: str, data: dict) -> io.BytesIO:
    """Генератор официальных документов в формате .docx по законам РК"""
    doc = Document()
    
    # Задаем стандартные поля по ГОСТу РК (Левое 3см, Правое 1см)
    for section in doc.sections:
        section.top_margin = Inches(0.8)
        section.bottom_margin = Inches(0.8)
        section.left_margin = Inches(1.1)
        section.right_margin = Inches(0.4)

    # Настройка базового шрифта (Times New Roman, 14)
    style = doc.styles['Normal']
    font = style.font
    font.name = 'Times New Roman'
    font.size = Pt(14)

    if doc_type == "pretenzia":
        # 1. ШАПКА ДОКУМЕНТА (Выравнивание по правому краю)
        p_header = doc.add_paragraph()
        p_header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        p_header.add_run(f"Кому: {data.get('respondent', 'Наименование ответчика')}\n")
        p_header.add_run(f"От кого: {data.get('claimant', 'ФИО заявителя')}\n")
        p_header.add_run(f"ИИН/БИН: {data.get('iin', '__________')}\n")
        p_header.add_run(f"Контакты: {data.get('phone', '__________')}\n")
        
        # 2. ЗАГОЛОВОК
        p_title = doc.add_paragraph()
        p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_title.add_run("\n\nДОСУДЕБНАЯ ПРЕТЕНЗИЯ\n").bold = True
        p_title.add_run("(в порядке досудебного урегулирования спора на основе ГПК РК)").italic = True

        # 3. ТЕКСТ КОРПУСА
        p_body = doc.add_paragraph()
        p_body.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        p_body.paragraph_format.first_line_indent = Inches(0.5) # Красная строка
        p_body.add_run(f"Я, {data.get('claimant', '__________')}, направляю настоящую претензию в связи с неисполнением обязательств. ")
        p_body.add_run(f"На основании Гражданского кодекса Республики Казахстан, требую выплатить сумму в размере {data.get('amount', '_____')} тенге в срок до {data.get('deadline', '_____')} года. ")
        p_body.add_run("В случае невыполнения требований, я буду вынужден обратиться в суд Республики Казахстан с исковым заявлением, где дополнительно будут взысканы судебные расходы и государственная пошлина.")

        # 4. ПОДПИСЬ
        p_footer = doc.add_paragraph()
        p_footer.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p_footer.add_run(f"\n\nДата: {data.get('date', '__________')} года              Подпись: ___________")

    # Сохраняем файл в оперативную память, чтобы мгновенно отдать пользователю на скачивание
    file_stream = io.BytesIO()
    doc.save(file_stream)
    file_stream.seek(0)
    return file_stream
