import sys
import os
import pyodbc
import logging
import bcrypt
from cryptography.fernet import Fernet
import datetime
import time
import qrcode
from PIL import Image
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTableView, QComboBox, QDateEdit, QDialog,
    QMessageBox, QTabWidget, QFileDialog, QMenuBar, QAction, QDockWidget,
    QToolBar, QSystemTrayIcon, QMenu, QTextEdit, QFormLayout, QSpinBox,
    QProgressBar, QShortcut, QListWidget, QSizePolicy, QFontComboBox, QInputDialog, QColorDialog, QHeaderView,
    QUndoCommand, QUndoStack
)
from PyQt5.QtCore import QTimer, QDate, Qt, QEvent, QAbstractTableModel, QUrl
from PyQt5.QtGui import QIcon, QColor, QPalette, QKeySequence, QFont, QTextCursor, QTextListFormat, QTextCharFormat, QTextImageFormat
from PyQt5.QtPrintSupport import QPrinter, QPrintDialog
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate, Table, Image as ReportImage
from reportlab.lib import colors
import openpyxl
from openpyxl.drawing.image import Image as XLImage
from jinja2 import Template
import csv
import matplotlib.pyplot as plt
from io import BytesIO
import base64
from functools import lru_cache
import json
from apscheduler.schedulers.background import BackgroundScheduler
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication

# Настройка логирования
logging.basicConfig(filename='app.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Ключ шифрования для AES-256
ENCRYPTION_KEY_FILE = 'secret.key'

def generate_key():
    """Генерация ключа шифрования AES-256"""
    key = Fernet.generate_key()
    with open(ENCRYPTION_KEY_FILE, 'wb') as key_file:
        key_file.write(key)

def load_key():
    """Загрузка ключа шифрования"""
    if not os.path.exists(ENCRYPTION_KEY_FILE):
        generate_key()
    return open(ENCRYPTION_KEY_FILE, 'rb').read()

KEY = load_key()
cipher = Fernet(KEY)

def encrypt_data(data):
    """Шифрование данных"""
    return cipher.encrypt(data.encode())

def decrypt_data(encrypted_data):
    """Расшифровка данных"""
    return cipher.decrypt(encrypted_data).decode()

class ReportTableModel(QAbstractTableModel):
    """Модель таблицы для списка отчётов"""
    def __init__(self, db, user_id):
        super().__init__()
        self.db = db
        self.user_id = user_id
        self.data = self.load_reports()

    def load_reports(self):
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT id, config, type, created_at FROM report_templates WHERE user_id = ? ORDER BY created_at DESC", (self.user_id,))
        reports = []
        for row in cursor.fetchall():
            config = json.loads(row[1])
            reports.append((row[0], config.get('name', 'Без названия'), row[3], row[2]))
        return reports

    def rowCount(self, parent=None):
        return len(self.data)

    def columnCount(self, parent=None):
        return 3  # Название, Дата создания, Тип

    def data(self, index, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            return str(self.data[index.row()][index.column() + 1])
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            headers = ['Название', 'Дата создания', 'Тип']
            return headers[section]
        return None

    def refresh(self):
        self.data = self.load_reports()
        self.layoutChanged.emit()

class UserTableModel(QAbstractTableModel):
    """Модель таблицы для списка пользователей"""
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.data = self.load_users()

    def load_users(self):
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT id, username, role FROM users")
        return cursor.fetchall()

    def rowCount(self, parent=None):
        return len(self.data)

    def columnCount(self, parent=None):
        return 3  # ID, Username, Role

    def data(self, index, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            return str(self.data[index.row()][index.column()])
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            headers = ['ID', 'Имя пользователя', 'Роль']
            return headers[section]
        return None

    def refresh(self):
        self.data = self.load_users()
        self.layoutChanged.emit()

class ReportGenerator:
    """Генератор отчётов в различных форматах"""
    def __init__(self, db, config, format='pdf', logo_path=None):
        self.db = db
        self.config = config
        self.format = format
        self.logo_path = logo_path
        self.data, self.headers = self.fetch_data()

    def fetch_data(self):
        cursor = self.db.conn.cursor()
        fields = self.config.get('fields', ['id', 'name', 'category', 'quantity', 'condition'])
        query = f"SELECT {', '.join(fields)} FROM inventory WHERE 1=1"
        params = []
        filters = self.config.get('filters', {})
        if filters.get('category'):
            query += " AND category = ?"
            params.append(filters['category'])
        if filters.get('condition'):
            query += " AND condition = ?"
            params.append(filters['condition'])
        if filters.get('date_from'):
            query += " AND purchase_date >= ?"
            params.append(filters['date_from'])
        if filters.get('date_to'):
            query += " AND purchase_date <= ?"
            params.append(filters['date_to'])
        cursor.execute(query, params)
        return cursor.fetchall(), fields

    def add_visualization(self, viz_type='table'):
        if viz_type == 'table':
            return None
        fig, ax = plt.subplots()
        data = list(self.data)
        headers = self.headers
        if viz_type == 'bar':
            ax.bar([row[0] for row in data], [row[3] if len(row) > 3 else 0 for row in data])
            ax.set_xlabel(headers[0])
            ax.set_ylabel(headers[3] if len(headers) > 3 else 'Количество')
        elif viz_type == 'pie':
            ax.pie([row[3] if len(row) > 3 else 0 for row in data], labels=[row[1] for row in data], autopct='%1.1f%%')
        elif viz_type == 'line':
            ax.plot([row[0] for row in data], [row[3] if len(row) > 3 else 0 for row in data])
            ax.set_xlabel(headers[0])
            ax.set_ylabel(headers[3] if len(headers) > 3 else 'Количество')
        buf = BytesIO()
        fig.savefig(buf, format='png')
        buf.seek(0)
        plt.close(fig)
        return buf

    def export(self, filename):
        if self.format == 'pdf':
            self.generate_pdf(filename)
        elif self.format == 'excel':
            self.generate_excel(filename)
        elif self.format == 'html':
            self.generate_html(filename)

    def generate_pdf(self, filename):
        doc = SimpleDocTemplate(filename, pagesize=letter)
        elements = []
        if self.logo_path:
            logo = ReportImage(self.logo_path, width=100, height=50)
            elements.append(logo)
        table_data = [self.headers] + [list(row) for row in self.data]
        table = Table(table_data)
        table.setStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), self.config.get('font', 'Helvetica')),
            ('FONTSIZE', (0, 0), (-1, 0), self.config.get('font_size', 12)),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ])
        elements.append(table)
        if self.config.get('viz_type') != 'table':
            img_buf = self.add_visualization(self.config.get('viz_type', 'bar'))
            if img_buf:
                img = ReportImage(img_buf, width=400, height=200)
                elements.append(img)
        doc.build(elements)

    def generate_excel(self, filename):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(self.headers)
        for row in self.data:
            ws.append(list(row))
        if self.config.get('viz_type') != 'table':
            img_buf = self.add_visualization(self.config.get('viz_type', 'bar'))
            if img_buf:
                img = XLImage(img_buf)
                ws.add_image(img, 'A10')
        wb.save(filename)

    def generate_html(self, filename):
        template_str = """
        <html>
        <head>
            <style>
                table { border-collapse: collapse; width: 100%; font-family: {{font}}; font-size: {{font_size}}px; }
                th, td { border: 1px solid black; padding: 8px; text-align: center; }
                th { background-color: {{header_color}}; color: white; }
                body { background-color: {{bg_color}}; }
            </style>
        </head>
        <body>
            {% if logo %}
            <img src="{{logo}}">
            {% endif %}
            <h1>{{title}}</h1>
            <table>
                <tr>{% for header in headers %}<th>{{header}}</th>{% endfor %}</tr>
                {% for row in data %}
                <tr>{% for col in row %}<td>{{col}}</td>{% endfor %}</tr>
                {% endfor %}
            </table>
            {% if chart %}
            <img src="data:image/png;base64,{{chart}}">
            {% endif %}
        </body>
        </html>
        """
        template = Template(template_str)
        data = list(self.data)
        chart_base64 = ''
        if self.config.get('viz_type') != 'table':
            buf = self.add_visualization(self.config.get('viz_type', 'bar'))
            if buf:
                chart_base64 = base64.b64encode(buf.read()).decode()
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(template.render(
                logo=self.logo_path or '',
                title=self.config.get('name', 'Отчёт'),
                font=self.config.get('font', 'Helvetica'),
                font_size=self.config.get('font_size', 12),
                header_color=self.config.get('header_color', 'grey'),
                bg_color=self.config.get('bg_color', '#f0f0f0'),
                headers=self.headers,
                data=data,
                chart=chart_base64
            ))

class ReportEditor(QDialog):
    """Редактор отчётов с поддержкой Undo/Redo и редактируемым предпросмотром"""
    class AddFieldCommand(QUndoCommand):
        def __init__(self, fields_list, field):
            super().__init__()
            self.fields_list = fields_list
            self.field = field
            self.setText(f"Добавить поле {field}")

        def redo(self):
            self.fields_list.addItem(self.field)

        def undo(self):
            for i in range(self.fields_list.count()):
                if self.fields_list.item(i).text() == self.field:
                    self.fields_list.takeItem(i)
                    break

    class RemoveFieldCommand(QUndoCommand):
        def __init__(self, fields_list, field):
            super().__init__()
            self.fields_list = fields_list
            self.field = field
            self.setText(f"Удалить поле {field}")

        def redo(self):
            for i in range(self.fields_list.count()):
                if self.fields_list.item(i).text() == self.field:
                    self.fields_list.takeItem(i)
                    break

        def undo(self):
            self.fields_list.addItem(self.field)

    def __init__(self, db, user_id, report_id=None, config=None):
        super().__init__()
        self.setWindowTitle('Редактор отчётов')
        self.db = db
        self.user_id = user_id
        self.report_id = report_id
        self.config = config or {
            'name': 'Новый отчёт',
            'fields': ['name', 'category', 'quantity'],
            'filters': {},
            'viz_type': 'table',
            'font': 'Helvetica',
            'font_size': 12,
            'header_color': 'grey',
            'bg_color': '#f0f0f0',
            'preview_html': '<h1>Предпросмотр отчёта</h1>'
        }
        self.undo_stack = QUndoStack(self)
        self.setup_ui()
        self.preview.setHtml(self.config['preview_html'])
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def setup_ui(self):
        layout = QHBoxLayout()

        # Панель доступных полей
        fields_panel = QVBoxLayout()
        fields_label = QLabel('Доступные поля')
        self.available_fields = QListWidget()
        self.available_fields.addItems(['ID', 'Название', 'Категория', 'Количество', 'Состояние', 'Дата покупки', 'Срок службы'])
        self.available_fields.setDragEnabled(True)
        fields_panel.addWidget(fields_label)
        fields_panel.addWidget(self.available_fields)

        # Панель выбранных полей
        selected_fields_panel = QVBoxLayout()
        selected_fields_label = QLabel('Выбранные поля')
        self.selected_fields = QListWidget()
        self.selected_fields.setAcceptDrops(True)
        self.selected_fields.dropEvent = self.drop_event
        for field in self.config['fields']:
            self.selected_fields.addItem(field)
        add_field_btn = QPushButton('Добавить поле')
        add_field_btn.clicked.connect(self.add_field)
        remove_field_btn = QPushButton('Удалить поле')
        remove_field_btn.clicked.connect(self.remove_field)
        selected_fields_panel.addWidget(selected_fields_label)
        selected_fields_panel.addWidget(self.selected_fields)
        selected_fields_panel.addWidget(add_field_btn)
        selected_fields_panel.addWidget(remove_field_btn)

        # Панель свойств
        properties_panel = QFormLayout()
        self.name_input = QLineEdit(self.config['name'])
        self.category_filter = QComboBox()
        self.category_filter.addItems(['Все', 'Balls', 'Equipment'])
        self.category_filter.setCurrentText(self.config['filters'].get('category', 'Все'))
        self.condition_filter = QComboBox()
        self.condition_filter.addItems(['Все', 'Новый', 'Хороший', 'Изношенный', 'Сломанный'])
        self.condition_filter.setCurrentText(self.config['filters'].get('condition', 'Все'))
        self.date_from = QDateEdit()
        self.date_from.setDate(QDate.fromString(self.config['filters'].get('date_from', '2000-01-01'), 'yyyy-MM-dd'))
        self.date_to = QDateEdit()
        self.date_to.setDate(QDate.fromString(self.config['filters'].get('date_to', QDate.currentDate().toString('yyyy-MM-dd')), 'yyyy-MM-dd'))
        self.viz_type = QComboBox()
        self.viz_type.addItems(['Таблица', 'Столбчатая диаграмма', 'Круговая диаграмма', 'Линейный график'])
        self.viz_type.setCurrentText({
            'table': 'Таблица',
            'bar': 'Столбчатая диаграмма',
            'pie': 'Круговая диаграмма',
            'line': 'Линейный график'
        }.get(self.config['viz_type'], 'Таблица'))
        self.font_input = QFontComboBox()
        self.font_input.setCurrentFont(QFont(self.config.get('font', 'Helvetica')))
        self.font_size = QSpinBox()
        self.font_size.setValue(self.config.get('font_size', 12))
        self.header_color = QLineEdit(self.config.get('header_color', 'grey'))
        self.bg_color = QLineEdit(self.config.get('bg_color', '#f0f0f0'))
        properties_panel.addRow('Название отчёта', self.name_input)
        properties_panel.addRow('Категория', self.category_filter)
        properties_panel.addRow('Состояние', self.condition_filter)
        properties_panel.addRow('Дата с', self.date_from)
        properties_panel.addRow('Дата по', self.date_to)
        properties_panel.addRow('Тип визуализации', self.viz_type)
        properties_panel.addRow('Шрифт', self.font_input)
        properties_panel.addRow('Размер шрифта', self.font_size)
        properties_panel.addRow('Цвет заголовков', self.header_color)
        properties_panel.addRow('Цвет фона', self.bg_color)

        # Панель предпросмотра с возможностью редактирования
        preview_panel = QVBoxLayout()
        preview_label = QLabel('Предпросмотр (редактируемый)')
        self.preview_toolbar = QToolBar()
        self.add_formatting_toolbar()
        preview_panel.addWidget(preview_label)
        preview_panel.addWidget(self.preview_toolbar)
        self.preview = QTextEdit()
        self.preview.setAcceptRichText(True)
        preview_panel.addWidget(self.preview)

        # Кнопки
        buttons_panel = QVBoxLayout()
        insert_data_btn = QPushButton('Вставить данные')
        insert_data_btn.clicked.connect(self.insert_data)
        preview_btn = QPushButton('Обновить предпросмотр')
        preview_btn.clicked.connect(self.update_preview)
        save_btn = QPushButton('Сохранить')
        save_btn.clicked.connect(self.save_report)
        undo_btn = QPushButton('Отменить')
        undo_btn.clicked.connect(self.undo_stack.undo)
        redo_btn = QPushButton('Повторить')
        redo_btn.clicked.connect(self.undo_stack.redo)
        print_btn = QPushButton('Печать')
        print_btn.clicked.connect(self.print_preview)
        show_inventory_btn = QPushButton('Показать таблицу инвентаря')
        show_inventory_btn.clicked.connect(self.show_inventory)
        buttons_panel.addWidget(insert_data_btn)
        buttons_panel.addWidget(preview_btn)
        buttons_panel.addWidget(save_btn)
        buttons_panel.addWidget(undo_btn)
        buttons_panel.addWidget(redo_btn)
        buttons_panel.addWidget(print_btn)
        buttons_panel.addWidget(show_inventory_btn)

        layout.addLayout(fields_panel)
        layout.addLayout(selected_fields_panel)
        layout.addLayout(properties_panel)
        layout.addLayout(preview_panel)
        layout.addLayout(buttons_panel)
        self.setLayout(layout)
        self.update_preview()

    def add_formatting_toolbar(self):
        # Bold
        bold_action = QAction('B', self)
        bold_action.setCheckable(True)
        bold_action.triggered.connect(self.toggle_bold)
        self.preview_toolbar.addAction(bold_action)

        # Italic
        italic_action = QAction('I', self)
        italic_action.setCheckable(True)
        italic_action.triggered.connect(self.toggle_italic)
        self.preview_toolbar.addAction(italic_action)

        # Underline
        underline_action = QAction('U', self)
        underline_action.setCheckable(True)
        underline_action.triggered.connect(self.toggle_underline)
        self.preview_toolbar.addAction(underline_action)

        self.preview_toolbar.addSeparator()

        # Align left
        align_left_action = QAction('←', self)
        align_left_action.triggered.connect(lambda: self.set_alignment(Qt.AlignLeft))
        self.preview_toolbar.addAction(align_left_action)

        # Align center
        align_center_action = QAction('↔', self)
        align_center_action.triggered.connect(lambda: self.set_alignment(Qt.AlignCenter))
        self.preview_toolbar.addAction(align_center_action)

        # Align right
        align_right_action = QAction('→', self)
        align_right_action.triggered.connect(lambda: self.set_alignment(Qt.AlignRight))
        self.preview_toolbar.addAction(align_right_action)

        # Align justify
        align_justify_action = QAction('⇔', self)
        align_justify_action.triggered.connect(lambda: self.set_alignment(Qt.AlignJustify))
        self.preview_toolbar.addAction(align_justify_action)

        self.preview_toolbar.addSeparator()

        # Bullet list
        bullet_list_action = QAction('•', self)
        bullet_list_action.triggered.connect(self.bullet_list)
        self.preview_toolbar.addAction(bullet_list_action)

        # Numbered list
        numbered_list_action = QAction('1.', self)
        numbered_list_action.triggered.connect(self.numbered_list)
        self.preview_toolbar.addAction(numbered_list_action)

        self.preview_toolbar.addSeparator()

        # Insert link
        link_action = QAction('🔗', self)
        link_action.triggered.connect(self.insert_link)
        self.preview_toolbar.addAction(link_action)

        # Insert image
        image_action = QAction('🖼', self)
        image_action.triggered.connect(self.insert_image)
        self.preview_toolbar.addAction(image_action)

        self.preview_toolbar.addSeparator()

        # Color
        color_action = QAction('Цвет', self)
        color_action.triggered.connect(self.set_text_color)
        self.preview_toolbar.addAction(color_action)

    def toggle_bold(self):
        fmt = QTextCharFormat()
        fmt.setFontWeight(QFont.Bold if self.preview.fontWeight() != QFont.Bold else QFont.Normal)
        self.merge_format(fmt)

    def toggle_italic(self):
        fmt = QTextCharFormat()
        fmt.setFontItalic(not self.preview.fontItalic())
        self.merge_format(fmt)

    def toggle_underline(self):
        fmt = QTextCharFormat()
        fmt.setFontUnderline(not self.preview.fontUnderline())
        self.merge_format(fmt)

    def merge_format(self, format):
        cursor = self.preview.textCursor()
        if not cursor.hasSelection():
            cursor.select(QTextCursor.WordUnderCursor)
        cursor.mergeCharFormat(format)
        self.preview.mergeCurrentCharFormat(format)

    def set_alignment(self, alignment):
        self.preview.setAlignment(alignment)

    def bullet_list(self):
        cursor = self.preview.textCursor()
        cursor.createList(QTextListFormat.ListDisc)

    def numbered_list(self):
        cursor = self.preview.textCursor()
        cursor.createList(QTextListFormat.ListDecimal)

    def insert_link(self):
        url, ok = QInputDialog.getText(self, 'Вставить ссылку', 'URL:')
        if ok:
            text = self.preview.textCursor().selectedText() or 'Ссылка'
            self.preview.textCursor().insertHtml(f'<a href="{url}">{text}</a>')

    def insert_image(self):
        file, _ = QFileDialog.getOpenFileName(self, 'Выбрать изображение', '', 'Images (*.png *.jpg *.bmp)')
        if file:
            cursor = self.preview.textCursor()
            image_format = QTextImageFormat()
            image_format.setName(file)
            cursor.insertImage(image_format)

    def set_text_color(self):
        color = QColorDialog.getColor()
        if color.isValid():
            self.preview.setTextColor(color)

    def drop_event(self, event):
        field = event.mimeData().text()
        if field not in [self.selected_fields.item(i).text() for i in range(self.selected_fields.count())]:
            command = self.AddFieldCommand(self.selected_fields, field)
            self.undo_stack.push(command)
        event.accept()

    def add_field(self):
        current = self.available_fields.currentItem()
        if current and current.text() not in [self.selected_fields.item(i).text() for i in range(self.selected_fields.count())]:
            command = self.AddFieldCommand(self.selected_fields, current.text())
            self.undo_stack.push(command)

    def remove_field(self):
        current = self.selected_fields.currentItem()
        if current:
            command = self.RemoveFieldCommand(self.selected_fields, current.text())
            self.undo_stack.push(command)

    def insert_data(self):
        self.config['fields'] = [self.selected_fields.item(i).text().lower() for i in range(self.selected_fields.count())]
        self.config['filters'] = {
            'category': self.category_filter.currentText() if self.category_filter.currentText() != 'Все' else None,
            'condition': self.condition_filter.currentText() if self.condition_filter.currentText() != 'Все' else None,
            'date_from': self.date_from.date().toString('yyyy-MM-dd'),
            'date_to': self.date_to.date().toString('yyyy-MM-dd')
        }
        self.config['viz_type'] = {'Таблица': 'table', 'Столбчатая диаграмма': 'bar', 'Круговая диаграмма': 'pie', 'Линейный график': 'line'}[self.viz_type.currentText()]
        self.config['font'] = self.font_input.currentFont().family()
        self.config['font_size'] = self.font_size.value()
        self.config['header_color'] = self.header_color.text()
        self.config['bg_color'] = self.bg_color.text()
        self.update_preview()

    def update_preview(self):
        self.config['fields'] = [self.selected_fields.item(i).text().lower() for i in range(self.selected_fields.count())]
        self.config['name'] = self.name_input.text()
        report = ReportGenerator(self.db, self.config, 'html', 'school_logo.png')
        report.generate_html('preview.html')
        with open('preview.html', 'r', encoding='utf-8') as f:
            generated_html = f.read()
        self.preview.setHtml(generated_html)
        self.config['preview_html'] = generated_html  # Инициализируем сгенерированным HTML

    def print_preview(self):
        """Печать содержимого предпросмотра"""
        printer = QPrinter()
        dialog = QPrintDialog(printer, self)
        if dialog.exec_() == QPrintDialog.Accepted:
            self.preview.print_(printer)
            QMessageBox.information(self, 'Успех', 'Отчёт отправлен на печать')

    def save_report(self):
        self.config['name'] = self.name_input.text()
        self.config['fields'] = [self.selected_fields.item(i).text().lower() for i in range(self.selected_fields.count())]
        self.config['filters'] = {
            'category': self.category_filter.currentText() if self.category_filter.currentText() != 'Все' else None,
            'condition': self.condition_filter.currentText() if self.condition_filter.currentText() != 'Все' else None,
            'date_from': self.date_from.date().toString('yyyy-MM-dd'),
            'date_to': self.date_to.date().toString('yyyy-MM-dd')
        }
        self.config['viz_type'] = {'Таблица': 'table', 'Столбчатая диаграмма': 'bar', 'Круговая диаграмма': 'pie', 'Линейный график': 'line'}[self.viz_type.currentText()]
        self.config['font'] = self.font_input.currentFont().family()
        self.config['font_size'] = self.font_size.value()
        self.config['header_color'] = self.header_color.text()
        self.config['bg_color'] = self.bg_color.text()
        self.config['preview_html'] = self.preview.toHtml()  # Сохраняем отредактированный HTML
        cursor = self.db.conn.cursor()
        if self.report_id:
            cursor.execute("UPDATE report_templates SET config = ?, type = ? WHERE id = ?",
                           (json.dumps(self.config), self.config['viz_type'], self.report_id))
        else:
            cursor.execute("INSERT INTO report_templates (user_id, config, type, created_at) VALUES (?, ?, ?, ?)",
                           (self.user_id, json.dumps(self.config), self.config['viz_type'], datetime.datetime.now()))
        self.db.conn.commit()
        self.db.log_action(self.user_id, f"Сохранён отчёт {self.config['name']}")
        QMessageBox.information(self, 'Успех', 'Отчёт сохранён')
        self.accept()

    def show_inventory(self):
        """Показывает таблицу инвентаря в отдельном диалоге"""
        dialog = QDialog(self)
        dialog.setWindowTitle('Таблица инвентаря')
        layout = QVBoxLayout()
        table = QTableView()
        model = InventoryTableModel(self.db)
        table.setModel(model)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(table)
        dialog.setLayout(layout)
        dialog.resize(800, 600)
        dialog.exec_()

class InventoryTableModel(QAbstractTableModel):
    """Модель таблицы с пагинацией для инвентаря"""
    def __init__(self, db, page_size=100):
        super().__init__()
        self.db = db
        self.page = 0
        self.page_size = page_size
        self.data = self.load_page()

    def load_page(self):
        offset = self.page * self.page_size
        query = f"SELECT * FROM inventory ORDER BY id OFFSET {offset} ROWS FETCH NEXT {self.page_size} ROWS ONLY"
        cursor = self.db.conn.cursor()
        cursor.execute(query)
        return cursor.fetchall()

    def rowCount(self, parent=None):
        return len(self.data)

    def columnCount(self, parent=None):
        return 7  # ID, Название, Категория, Количество, Состояние, Дата покупки, Срок службы

    def data(self, index, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            return str(self.data[index.row()][index.column()])
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            headers = ['ID', 'Название', 'Категория', 'Количество', 'Состояние', 'Дата покупки', 'Срок службы']
            return headers[section]
        return None

    def next_page(self):
        self.page += 1
        self.data = self.load_page()
        self.layoutChanged.emit()

    def prev_page(self):
        if self.page > 0:
            self.page -= 1
            self.data = self.load_page()
            self.layoutChanged.emit()

class Database:
    """Обработка операций с базой данных SQL Server"""
    def __init__(self):
        self.server = 'H9ISE'
        self.database = 'inventoryyyyyyyy'
        self.conn = None
        self.connect_or_create()
        self.create_tables()
        self.add_default_users()
        self.add_default_templates()

    def connect_or_create(self):
        master_conn_str = f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={self.server};DATABASE=master;Trusted_Connection=yes;"
        try:
            master_conn = pyodbc.connect(master_conn_str, autocommit=True)
            cursor = master_conn.cursor()
            cursor.execute(f"""
                IF NOT EXISTS (SELECT name FROM sys.databases WHERE name = N'{self.database}')
                CREATE DATABASE {self.database}
            """)
            cursor.close()
            master_conn.close()
        except Exception as e:
            logging.error(f"Ошибка создания базы данных: {e}")
            raise

        conn_str = f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={self.server};DATABASE={self.database};Trusted_Connection=yes;"
        try:
            self.conn = pyodbc.connect(conn_str)
            self.conn.autocommit = False
        except Exception as e:
            logging.error(f"Ошибка подключения к базе данных: {e}")
            raise

    def create_tables(self):
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='users' AND xtype='U')
                CREATE TABLE users (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    username NVARCHAR(50) UNIQUE,
                    password VARBINARY(MAX),
                    role NVARCHAR(20) CHECK (role IN ('Admin', 'Teacher', 'Student'))
                )
            """)
            self.conn.commit()
            logging.info("Таблица users создана или уже существует")

            cursor.execute("""
                IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='inventory' AND xtype='U')
                CREATE TABLE inventory (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    name NVARCHAR(100),
                    category NVARCHAR(50),
                    quantity INT,
                    condition NVARCHAR(20),
                    purchase_date DATE,
                    service_life INT,
                    photo VARBINARY(MAX)
                )
            """)
            self.conn.commit()
            logging.info("Таблица inventory создана или уже существует")

            cursor.execute("""
                IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='bookings' AND xtype='U')
                CREATE TABLE bookings (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    inventory_id INT,
                    user_id INT,
                    booking_date DATE,
                    class NVARCHAR(50),
                    FOREIGN KEY (inventory_id) REFERENCES inventory(id),
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            """)
            self.conn.commit()
            logging.info("Таблица bookings создана или уже существует")

            cursor.execute("""
                IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='logs' AND xtype='U')
                CREATE TABLE logs (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    user_id INT,
                    action NVARCHAR(255),
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            """)
            self.conn.commit()
            logging.info("Таблица logs создана или уже существует")

            cursor.execute("""
                IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='report_templates' AND xtype='U')
                CREATE TABLE report_templates (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    user_id INT,
                    config NVARCHAR(MAX),
                    type NVARCHAR(50),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            """)
            self.conn.commit()
            logging.info("Таблица report_templates создана или уже существует")

            cursor.execute("""
                IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='report_history' AND xtype='U')
                CREATE TABLE report_history (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    report_id INT,
                    user_id INT,
                    action NVARCHAR(255),
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (report_id) REFERENCES report_templates(id),
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            """)
            self.conn.commit()
            logging.info("Таблица report_history создана или уже существует")
        except pyodbc.Error as e:
            self.conn.rollback()
            logging.error(f"Ошибка создания таблиц: {e}")
            raise

    def add_default_users(self):
        cursor = self.conn.cursor()
        try:
            hashed = bcrypt.hashpw('admin'.encode(), bcrypt.gensalt())
            cursor.execute("""
                IF NOT EXISTS (SELECT 1 FROM users WHERE username = 'admin')
                INSERT INTO users (username, password, role) VALUES ('admin', ?, 'Admin')
            """, (hashed,))
            hashed = bcrypt.hashpw('teacher'.encode(), bcrypt.gensalt())
            cursor.execute("""
                IF NOT EXISTS (SELECT 1 FROM users WHERE username = 'teacher')
                INSERT INTO users (username, password, role) VALUES ('teacher', ?, 'Teacher')
            """, (hashed,))
            hashed = bcrypt.hashpw('student'.encode(), bcrypt.gensalt())
            cursor.execute("""
                IF NOT EXISTS (SELECT 1 FROM users WHERE username = 'student')
                INSERT INTO users (username, password, role) VALUES ('student', ?, 'Student')
            """, (hashed,))
            self.conn.commit()
            logging.info("Добавлены пользователи по умолчанию")
        except pyodbc.Error as e:
            self.conn.rollback()
            logging.error(f"Ошибка добавления пользователей: {e}")
            raise

    def add_default_templates(self):
        cursor = self.conn.cursor()
        try:
            templates = [
                {
                    'name': 'Полный инвентарь',
                    'fields': ['id', 'name', 'category', 'quantity', 'condition', 'purchase_date', 'service_life'],
                    'filters': {},
                    'viz_type': 'table',
                    'font': 'Helvetica',
                    'font_size': 12,
                    'header_color': 'grey',
                    'bg_color': '#f0f0f0',
                    'preview_html': '<h1>Полный инвентарь</h1>'
                },
                {
                    'name': 'Состояние по категориям',
                    'fields': ['category', 'condition', 'quantity'],
                    'filters': {},
                    'viz_type': 'pie',
                    'font': 'Times',
                    'font_size': 14,
                    'header_color': 'blue',
                    'bg_color': '#ffffff',
                    'preview_html': '<h1>Состояние по категориям</h1>'
                },
                {
                    'name': 'План закупок',
                    'fields': ['category', 'quantity'],
                    'filters': {'quantity': '< 10'},
                    'viz_type': 'bar',
                    'font': 'Courier',
                    'font_size': 12,
                    'header_color': 'green',
                    'bg_color': '#f0f0f0',
                    'preview_html': '<h1>План закупок</h1>'
                }
            ]
            for template in templates:
                cursor.execute("""
                    IF NOT EXISTS (SELECT 1 FROM report_templates WHERE config LIKE ?)
                    INSERT INTO report_templates (user_id, config, type, created_at) VALUES (?, ?, ?, ?)
                """, (f'%{template["name"]}%', 1, json.dumps(template), template['viz_type'], datetime.datetime.now()))
            self.conn.commit()
            logging.info("Добавлены шаблоны отчётов по умолчанию")
        except pyodbc.Error as e:
            self.conn.rollback()
            logging.error(f"Ошибка добавления шаблонов отчётов: {e}")
            raise

    def add_user(self, username, password, role):
        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
        cursor = self.conn.cursor()
        try:
            cursor.execute('INSERT INTO users (username, password, role) VALUES (?, ?, ?)', (username, hashed, role))
            self.conn.commit()
        except pyodbc.Error as e:
            self.conn.rollback()
            logging.error(f"Ошибка добавления пользователя {username}: {e}")
            raise

    def authenticate(self, username, password):
        cursor = self.conn.cursor()
        cursor.execute('SELECT id, password, role FROM users WHERE username = ?', (username,))
        user = cursor.fetchone()
        if user and bcrypt.checkpw(password.encode(), user[1]):
            return user[0], user[2]
        return None, None

    def log_action(self, user_id, action):
        cursor = self.conn.cursor()
        try:
            cursor.execute('INSERT INTO logs (user_id, action) VALUES (?, ?)', (user_id, action))
            self.conn.commit()
            logging.info(f'Пользователь {user_id} выполнил действие: {action}')
        except pyodbc.Error as e:
            self.conn.rollback()
            logging.error(f"Ошибка логирования действия для пользователя {user_id}: {e}")

    def log_report_action(self, report_id, user_id, action):
        cursor = self.conn.cursor()
        try:
            cursor.execute('INSERT INTO report_history (report_id, user_id, action, timestamp) VALUES (?, ?, ?, ?)',
                           (report_id, user_id, action, datetime.datetime.now()))
            self.conn.commit()
            logging.info(f'Действие с отчётом {report_id} пользователем {user_id}: {action}')
        except pyodbc.Error as e:
            self.conn.rollback()
            logging.error(f"Ошибка логирования действия с отчётом {report_id}: {e}")

    @lru_cache(maxsize=100)
    def get_inventory(self):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM inventory')
        return cursor.fetchall()

    def add_inventory(self, name, category, quantity, condition, purchase_date, service_life, photo=None):
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO inventory (name, category, quantity, condition, purchase_date, service_life, photo)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (name, category, quantity, condition, purchase_date, service_life, photo))
            self.conn.commit()
            self.get_inventory.cache_clear()
        except pyodbc.Error as e:
            self.conn.rollback()
            logging.error(f"Ошибка добавления инвентаря {name}: {e}")
            raise

    def update_inventory(self, id, name, category, quantity, condition, purchase_date, service_life, photo=None):
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                UPDATE inventory SET name=?, category=?, quantity=?, condition=?, purchase_date=?, service_life=?, photo=?
                WHERE id=?
            """, (name, category, quantity, condition, purchase_date, service_life, photo, id))
            self.conn.commit()
            self.get_inventory.cache_clear()
        except pyodbc.Error as e:
            self.conn.rollback()
            logging.error(f"Ошибка обновления инвентаря {id}: {e}")
            raise

    def delete_inventory(self, id):
        cursor = self.conn.cursor()
        try:
            cursor.execute('DELETE FROM inventory WHERE id=?', (id,))
            self.conn.commit()
            self.get_inventory.cache_clear()
        except pyodbc.Error as e:
            self.conn.rollback()
            logging.error(f"Ошибка удаления инвентаря {id}: {e}")
            raise

    def add_booking(self, inventory_id, user_id, booking_date, class_):
        cursor = self.conn.cursor()
        try:
            cursor.execute('INSERT INTO bookings (inventory_id, user_id, booking_date, class) VALUES (?, ?, ?, ?)',
                           (inventory_id, user_id, booking_date, class_))
            self.conn.commit()
        except pyodbc.Error as e:
            self.conn.rollback()
            logging.error(f"Ошибка добавления бронирования для инвентаря {inventory_id}: {e}")
            raise

    def get_bookings(self, user_id=None):
        cursor = self.conn.cursor()
        if user_id:
            cursor.execute('SELECT * FROM bookings WHERE user_id = ?', (user_id,))
        else:
            cursor.execute('SELECT * FROM bookings')
        return cursor.fetchall()

    def search_inventory(self, query):
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM inventory WHERE name LIKE ? OR category LIKE ? OR condition LIKE ?
        """, (f'%{query}%', f'%{query}%', f'%{query}%'))
        return cursor.fetchall()

    def get_users(self):
        cursor = self.conn.cursor()
        cursor.execute('SELECT id, username, role FROM users')
        return cursor.fetchall()

    def close(self):
        self.conn.close()

class LoginDialog(QDialog):
    """Окно входа в систему"""
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Вход')
        layout = QVBoxLayout()
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        login_btn = QPushButton('Войти')
        login_btn.clicked.connect(self.login)
        layout.addWidget(QLabel('Имя пользователя:'))
        layout.addWidget(self.username)
        layout.addWidget(QLabel('Пароль:'))
        layout.addWidget(self.password)
        layout.addWidget(login_btn)
        self.setLayout(layout)
        self.db = Database()
        self.user_id = None
        self.role = None

    def login(self):
        self.user_id, self.role = self.db.authenticate(self.username.text(), self.password.text())
        if self.user_id:
            self.db.log_action(self.user_id, 'Вход выполнен')
            self.accept()
        else:
            QMessageBox.warning(self, 'Ошибка', 'Неверные учетные данные')

class BaseMainWindow(QMainWindow):
    """Базовое окно для интерфейсов"""
    def __init__(self, user_id, role):
        super().__init__()
        self.setWindowTitle('Учёт спортивного инвентаря')
        self.setMinimumSize(1280, 720)
        self.user_id = user_id
        self.role = role
        self.db = Database()
        self.db.log_action(self.user_id, 'Открыто главное окно')
        self.inactivity_timer = QTimer(self)
        self.inactivity_timer.timeout.connect(self.logout)
        self.inactivity_timer.start(15 * 60 * 1000)
        self.installEventFilter(self)

        self.theme = 'light'
        self.set_theme()

        self.setup_ui()

    def eventFilter(self, obj, event):
        if event.type() in [QEvent.KeyPress, QEvent.MouseButtonPress, QEvent.MouseMove]:
            self.inactivity_timer.stop()
            self.inactivity_timer.start(15 * 60 * 1000)
        return super().eventFilter(obj, event)

    def logout(self):
        self.db.log_action(self.user_id, 'Выход из-за неактивности')
        self.close()

    def set_theme(self):
        palette = QPalette()
        if self.theme == 'dark':
            palette.setColor(QPalette.Window, QColor(53, 53, 53))
            palette.setColor(QPalette.WindowText, Qt.white)
            palette.setColor(QPalette.Base, QColor(25, 25, 25))
            palette.setColor(QPalette.Text, Qt.white)
            palette.setColor(QPalette.Button, QColor(53, 53, 53))
            palette.setColor(QPalette.ButtonText, Qt.white)
        QApplication.setPalette(palette)

    def setup_ui(self):
        self.toolbar = QToolBar()
        self.addToolBar(Qt.TopToolBarArea, self.toolbar)
        self.dock = QDockWidget('Меню', self)
        self.dock.setAllowedAreas(Qt.LeftDockWidgetArea)
        self.dock_widget = QWidget()
        self.dock_layout = QVBoxLayout()
        self.dock_widget.setLayout(self.dock_layout)
        self.dock.setWidget(self.dock_widget)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.dock)
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        menubar = self.menuBar()
        file_menu = menubar.addMenu('Файл')
        theme_action = QAction('Переключить тему', self)
        theme_action.triggered.connect(self.toggle_theme)
        file_menu.addAction(theme_action)
        backup_action = QAction('Резервное копирование базы данных', self)
        backup_action.triggered.connect(self.backup_db)
        file_menu.addAction(backup_action)

        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(QIcon.fromTheme('dialog-information'))
        self.tray.show()
        self.check_reminders()

    def toggle_theme(self):
        self.theme = 'dark' if self.theme == 'light' else 'light'
        self.set_theme()

    def backup_db(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('Резервное копирование базы данных')
        layout = QVBoxLayout()
        progress = QProgressBar()
        progress.setValue(0)
        layout.addWidget(progress)
        backup_btn = QPushButton('Начать копирование')
        layout.addWidget(backup_btn)
        dialog.setLayout(layout)
        def do_backup():
            for i in range(101):
                progress.setValue(i)
                time.sleep(0.05)
            QMessageBox.information(self, 'Резервное копирование', 'Копирование завершено (используйте SSMS для реального копирования).')
            dialog.close()
        backup_btn.clicked.connect(do_backup)
        dialog.exec_()

    def check_reminders(self):
        items = self.db.get_inventory()
        current_year = datetime.date.today().year
        reminders = [item[1] for item in items if item[5] and datetime.date.fromisoformat(str(item[5])).year + item[6] <= current_year]
        if reminders:
            self.tray.showMessage('Напоминание', f'Необходима замена предметов: {", ".join(reminders)}', QSystemTrayIcon.Information)

    def closeEvent(self, event):
        self.db.close()
        super().closeEvent(event)

class AdminWindow(BaseMainWindow):
    def setup_ui(self):
        super().setup_ui()
        self.add_inventory_tab()
        self.add_users_tab()
        self.add_reports_tab()
        self.add_logs_tab()
        self.toolbar.addAction('Добавить', self.add_item_dialog)
        self.toolbar.addAction('Поиск', self.search_inventory)

    def add_inventory_tab(self):
        tab = QWidget()
        layout = QVBoxLayout()
        self.inventory_table = QTableView()
        self.model = InventoryTableModel(self.db)
        self.inventory_table.setModel(self.model)
        self.inventory_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.inventory_table)

        nav_layout = QHBoxLayout()
        prev_btn = QPushButton('Предыдущая страница')
        prev_btn.clicked.connect(self.model.prev_page)
        next_btn = QPushButton('Следующая страница')
        next_btn.clicked.connect(self.model.next_page)
        nav_layout.addWidget(prev_btn)
        nav_layout.addWidget(next_btn)
        layout.addLayout(nav_layout)

        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        search_btn = QPushButton('Поиск')
        search_btn.clicked.connect(self.search_inventory)
        search_layout.addWidget(QLabel('Поиск:'))
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(search_btn)
        layout.addLayout(search_layout)

        add_btn = QPushButton('Добавить предмет')
        add_btn.clicked.connect(self.add_item_dialog)
        layout.addWidget(add_btn)
        update_btn = QPushButton('Обновить предмет')
        update_btn.clicked.connect(self.update_item_dialog)
        layout.addWidget(update_btn)
        delete_btn = QPushButton('Удалить предмет')
        delete_btn.clicked.connect(self.delete_item)
        layout.addWidget(delete_btn)
        qr_btn = QPushButton('Сгенерировать QR-код')
        qr_btn.clicked.connect(self.generate_qr)
        layout.addWidget(qr_btn)

        tab.setLayout(layout)
        self.dock_layout.addWidget(QPushButton('Инвентарь', clicked=lambda: self.tabs.setCurrentWidget(tab)))
        self.tabs.addTab(tab, 'Инвентарь')

    def add_item_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('Добавить предмет')
        layout = QFormLayout()
        name = QLineEdit()
        category = QLineEdit()
        quantity = QSpinBox()
        condition = QComboBox()
        condition.addItems(['Новый', 'Хороший', 'Изношенный', 'Сломанный'])
        purchase_date = QDateEdit(QDate.currentDate())
        service_life = QSpinBox()
        photo_path = [None]
        photo_btn = QPushButton('Загрузить фото')
        photo_btn.clicked.connect(lambda: photo_path.__setitem__(0, QFileDialog.getOpenFileName(self, 'Выбрать фото')[0]))
        add_btn = QPushButton('Добавить')
        def add_item():
            photo = None
            if photo_path[0]:
                try:
                    with open(photo_path[0], 'rb') as f:
                        photo = f.read()
                except Exception as e:
                    logging.error(f"Ошибка чтения фото: {e}")
                    QMessageBox.warning(self, 'Ошибка', 'Не удалось загрузить фото')
                    return
            self.db.add_inventory(name.text(), category.text(), quantity.value(), condition.currentText(),
                                  purchase_date.date().toString('yyyy-MM-dd'), service_life.value(), photo)
            self.db.log_action(self.user_id, f'Добавлен предмет {name.text()}')
            self.model.data = self.model.load_page()
            self.model.layoutChanged.emit()
            dialog.close()
        add_btn.clicked.connect(add_item)
        layout.addRow('Название', name)
        layout.addRow('Категория', category)
        layout.addRow('Количество', quantity)
        layout.addRow('Состояние', condition)
        layout.addRow('Дата покупки', purchase_date)
        layout.addRow('Срок службы (годы)', service_life)
        layout.addRow('Фото', photo_btn)
        layout.addRow(add_btn)
        dialog.setLayout(layout)
        dialog.exec_()

    def update_item_dialog(self):
        row = self.inventory_table.currentIndex().row()
        if row < 0:
            QMessageBox.warning(self, 'Ошибка', 'Выберите предмет')
            return
        id = int(self.model.data[row][0])
        item = next(i for i in self.db.get_inventory() if i[0] == id)
        dialog = QDialog(self)
        dialog.setWindowTitle('Обновить предмет')
        layout = QFormLayout()
        name = QLineEdit(item[1])
        category = QLineEdit(item[2])
        quantity = QSpinBox()
        quantity.setValue(item[3])
        condition = QComboBox()
        condition.addItems(['Новый', 'Хороший', 'Изношенный', 'Сломанный'])
        condition.setCurrentText(item[4])
        purchase_date = QDateEdit(QDate.fromString(item[5], 'yyyy-MM-dd'))
        service_life = QSpinBox()
        service_life.setValue(item[6])
        photo_path = [None]
        photo_btn = QPushButton('Загрузить новое фото')
        photo_btn.clicked.connect(lambda: photo_path.__setitem__(0, QFileDialog.getOpenFileName(self, 'Выбрать фото')[0]))
        update_btn = QPushButton('Обновить')
        def update_item():
            photo = item[7]
            if photo_path[0]:
                try:
                    with open(photo_path[0], 'rb') as f:
                        photo = f.read()
                except Exception as e:
                    logging.error(f"Ошибка чтения фото: {e}")
                    QMessageBox.warning(self, 'Ошибка', 'Не удалось загрузить фото')
                    return
            self.db.update_inventory(id, name.text(), category.text(), quantity.value(), condition.currentText(),
                                     purchase_date.date().toString('yyyy-MM-dd'), service_life.value(), photo)
            self.db.log_action(self.user_id, f'Обновлён предмет {id}')
            self.model.data = self.model.load_page()
            self.model.layoutChanged.emit()
            dialog.close()
        update_btn.clicked.connect(update_item)
        layout.addRow('Название', name)
        layout.addRow('Категория', category)
        layout.addRow('Количество', quantity)
        layout.addRow('Состояние', condition)
        layout.addRow('Дата покупки', purchase_date)
        layout.addRow('Срок службы (годы)', service_life)
        layout.addRow('Фото', photo_btn)
        layout.addRow(update_btn)
        dialog.setLayout(layout)
        dialog.exec_()

    def delete_item(self):
        row = self.inventory_table.currentIndex().row()
        if row < 0:
            QMessageBox.warning(self, 'Ошибка', 'Выберите предмет')
            return
        id = int(self.model.data[row][0])
        self.db.delete_inventory(id)
        self.db.log_action(self.user_id, f'Удалён предмет {id}')
        self.model.data = self.model.load_page()
        self.model.layoutChanged.emit()

    def generate_qr(self):
        row = self.inventory_table.currentIndex().row()
        if row < 0:
            QMessageBox.warning(self, 'Ошибка', 'Выберите предмет')
            return
        id = self.model.data[row][0]
        qr = qrcode.QRCode()
        qr.add_data(f'ID инвентаря: {id} - Название: {self.model.data[row][1]}')
        qr.make(fit=True)
        img = qr.make_image(fill='black', back_color='white')
        img.save(f'qr_{id}.png')
        QMessageBox.information(self, 'QR-код сгенерирован', f'QR-код сохранён как qr_{id}.png')

    def search_inventory(self):
        query = self.search_input.text()
        items = self.db.search_inventory(query)
        self.model.data = items
        self.model.layoutChanged.emit()

    def add_users_tab(self):
        tab = QWidget()
        layout = QVBoxLayout()
        self.users_table = QTableView()
        self.users_model = UserTableModel(self.db)
        self.users_table.setModel(self.users_model)
        self.users_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.users_table)

        form_layout = QFormLayout()
        username = QLineEdit()
        password = QLineEdit()
        role = QComboBox()
        role.addItems(['Администратор', 'Учитель', 'Ученик'])
        add_btn = QPushButton('Добавить пользователя')
        def add_user():
            try:
                self.db.add_user(username.text(), password.text(), role.currentText())
                self.db.log_action(self.user_id, f'Добавлен пользователь {username.text()}')
                self.users_model.refresh()
                QMessageBox.information(self, 'Успех', 'Пользователь добавлен')
            except Exception as e:
                QMessageBox.warning(self, 'Ошибка', f'Не удалось добавить пользователя: {str(e)}')
        add_btn.clicked.connect(add_user)
        form_layout.addRow('Имя пользователя', username)
        form_layout.addRow('Пароль', password)
        form_layout.addRow('Роль', role)
        form_layout.addRow(add_btn)
        layout.addLayout(form_layout)
        tab.setLayout(layout)
        self.dock_layout.addWidget(QPushButton('Пользователи', clicked=lambda: self.tabs.setCurrentWidget(tab)))
        self.tabs.addTab(tab, 'Пользователи')

    def add_reports_tab(self):
        tab = QWidget()
        layout = QVBoxLayout()
        self.reports_table = QTableView()
        self.reports_model = ReportTableModel(self.db, self.user_id)
        self.reports_table.setModel(self.reports_model)
        self.reports_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.reports_table.clicked.connect(self.show_report)
        self.reports_table.doubleClicked.connect(self.edit_report)
        layout.addWidget(self.reports_table)

        toolbar = QHBoxLayout()
        create_btn = QPushButton('Создать')
        create_btn.clicked.connect(self.create_report)
        edit_btn = QPushButton('Редактировать')
        edit_btn.clicked.connect(self.edit_report)
        delete_btn = QPushButton('Удалить')
        delete_btn.clicked.connect(self.delete_report)
        export_btn = QPushButton('Экспорт')
        export_btn.clicked.connect(self.export_report)
        share_btn = QPushButton('Поделиться')
        share_btn.clicked.connect(self.share_report)
        toolbar.addWidget(create_btn)
        toolbar.addWidget(edit_btn)
        toolbar.addWidget(delete_btn)
        toolbar.addWidget(export_btn)
        toolbar.addWidget(share_btn)
        layout.addLayout(toolbar)

        self.preview = QTextEdit()
        self.preview.setHtml('<h1>Выберите отчёт для предпросмотра</h1>')
        layout.addWidget(self.preview)

        tab.setLayout(layout)
        self.dock_layout.addWidget(QPushButton('Отчёты', clicked=lambda: self.tabs.setCurrentWidget(tab)))
        self.tabs.addTab(tab, 'Отчёты')

    def create_report(self):
        editor = ReportEditor(self.db, self.user_id)
        if editor.exec_():
            self.reports_model.refresh()
            self.db.log_report_action(None, self.user_id, 'Создан новый отчёт')

    def show_report(self, index):
        row = index.row()
        report_id = self.reports_model.data[row][0]
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT config FROM report_templates WHERE id = ?", (report_id,))
        config = json.loads(cursor.fetchone()[0])
        self.preview.setHtml(config.get('preview_html', '<h1>Отчёт</h1>'))

    def edit_report(self):
        row = self.reports_table.currentIndex().row()
        if row < 0:
            QMessageBox.warning(self, 'Ошибка', 'Выберите отчёт')
            return
        report_id = self.reports_model.data[row][0]
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT config FROM report_templates WHERE id = ?", (report_id,))
        config = json.loads(cursor.fetchone()[0])
        editor = ReportEditor(self.db, self.user_id, report_id, config)
        if editor.exec_():
            self.reports_model.refresh()
            self.db.log_report_action(report_id, self.user_id, f'Отредактирован отчёт {config["name"]}')
            self.show_report(self.reports_table.currentIndex())

    def delete_report(self):
        row = self.reports_table.currentIndex().row()
        if row < 0:
            QMessageBox.warning(self, 'Ошибка', 'Выберите отчёт')
            return
        report_id = self.reports_model.data[row][0]
        cursor = self.db.conn.cursor()
        cursor.execute("DELETE FROM report_templates WHERE id = ?", (report_id,))
        self.db.conn.commit()
        self.reports_model.refresh()
        self.db.log_report_action(report_id, self.user_id, 'Удалён отчёт')
        self.preview.setHtml('<h1>Выберите отчёт для предпросмотра</h1>')

    def export_report(self):
        row = self.reports_table.currentIndex().row()
        if row < 0:
            QMessageBox.warning(self, 'Ошибка', 'Выберите отчёт')
            return
        report_id = self.reports_model.data[row][0]
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT config FROM report_templates WHERE id = ?", (report_id,))
        config = json.loads(cursor.fetchone()[0])
        dialog = QDialog(self)
        dialog.setWindowTitle('Экспорт отчёта')
        layout = QFormLayout()
        format_selector = QComboBox()
        format_selector.addItems(['PDF', 'Excel', 'HTML'])
        layout.addRow('Формат', format_selector)
        export_btn = QPushButton('Экспортировать')
        def do_export():
            report = ReportGenerator(self.db, config, format_selector.currentText().lower(), 'school_logo.png')
            filename = f'report_{report_id}.{format_selector.currentText().lower()}'
            report.export(filename)
            QMessageBox.information(self, 'Успех', f'Отчёт экспортирован: {filename}')
            self.db.log_report_action(report_id, self.user_id, f'Экспортирован отчёт в {format_selector.currentText()}')
            dialog.close()
        export_btn.clicked.connect(do_export)
        layout.addRow(export_btn)
        dialog.setLayout(layout)
        dialog.exec_()

    def share_report(self):
        row = self.reports_table.currentIndex().row()
        if row < 0:
            QMessageBox.warning(self, 'Ошибка', 'Выберите отчёт')
            return
        report_id = self.reports_model.data[row][0]
        dialog = QDialog(self)
        dialog.setWindowTitle('Поделиться отчётом')
        layout = QFormLayout()
        user_selector = QComboBox()
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT id, username FROM users WHERE id != ?", (self.user_id,))
        users = cursor.fetchall()
        user_selector.addItems([u[1] for u in users])
        layout.addRow('Пользователь', user_selector)
        share_btn = QPushButton('Поделиться')
        def do_share():
            target_user_id = users[user_selector.currentIndex()][0]
            cursor.execute("SELECT config, type FROM report_templates WHERE id = ?", (report_id,))
            config, report_type = cursor.fetchone()
            cursor.execute("INSERT INTO report_templates (user_id, config, type, created_at) VALUES (?, ?, ?, ?)",
                           (target_user_id, config, report_type, datetime.datetime.now()))
            self.db.conn.commit()
            QMessageBox.information(self, 'Успех', 'Отчёт поделён')
            self.db.log_report_action(report_id, self.user_id, f'Отчёт поделён с пользователем {target_user_id}')
            dialog.close()
        share_btn.clicked.connect(do_share)
        layout.addRow(share_btn)
        dialog.setLayout(layout)
        dialog.exec_()

    def add_logs_tab(self):
        tab = QWidget()
        layout = QVBoxLayout()
        logs_text = QTextEdit()
        cursor = self.db.conn.cursor()
        cursor.execute('SELECT * FROM logs ORDER BY timestamp DESC')
        logs = cursor.fetchall()
        logs_text.setText('\n'.join(f'ID: {log[0]}, Пользователь: {log[1]}, Действие: {log[2]}, Время: {log[3]}' for log in logs))
        layout.addWidget(logs_text)
        tab.setLayout(layout)
        self.dock_layout.addWidget(QPushButton('Логи', clicked=lambda: self.tabs.setCurrentWidget(tab)))
        self.tabs.addTab(tab, 'Логи')

class TeacherWindow(BaseMainWindow):
    def setup_ui(self):
        super().setup_ui()
        self.add_inventory_tab()
        self.add_bookings_tab()
        self.add_reports_tab()
        self.toolbar.addAction('Забронировать', self.add_booking_dialog)
        self.toolbar.addAction('Поиск', self.search_inventory)
        QShortcut(QKeySequence('Ctrl+B'), self, self.add_booking_dialog)

    def add_inventory_tab(self):
        tab = QWidget()
        layout = QVBoxLayout()
        self.inventory_table = QTableView()
        self.model = InventoryTableModel(self.db)
        self.inventory_table.setModel(self.model)
        self.inventory_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.inventory_table)

        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        search_btn = QPushButton('Поиск')
        search_btn.clicked.connect(self.search_inventory)
        search_layout.addWidget(QLabel('Поиск:'))
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(search_btn)
        layout.addLayout(search_layout)

        tab.setLayout(layout)
        self.dock_layout.addWidget(QPushButton('Инвентарь', clicked=lambda: self.tabs.setCurrentWidget(tab)))
        self.tabs.addTab(tab, 'Инвентарь')

    def search_inventory(self):
        query = self.search_input.text()
        items = self.db.search_inventory(query)
        self.model.data = items
        self.model.layoutChanged.emit()

    def add_bookings_tab(self):
        tab = QWidget()
        layout = QVBoxLayout()
        self.bookings_table = QTableView()
        self.load_bookings()
        self.bookings_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.bookings_table)

        add_btn = QPushButton('Добавить бронирование')
        add_btn.clicked.connect(self.add_booking_dialog)
        layout.addWidget(add_btn)
        tab.setLayout(layout)
        self.dock_layout.addWidget(QPushButton('Бронирования', clicked=lambda: self.tabs.setCurrentWidget(tab)))
        self.tabs.addTab(tab, 'Бронирования')

    def load_bookings(self):
        bookings = self.db.get_bookings(self.user_id)
        model = QAbstractTableModel()
        model.data = bookings
        model.rowCount = lambda parent=None: len(bookings)
        model.columnCount = lambda parent=None: 5
        model.data = lambda index, role=Qt.DisplayRole: str(bookings[index.row()][index.column()]) if role == Qt.DisplayRole else None
        model.headerData = lambda section, orientation, role=Qt.DisplayRole: ['ID', 'ID инвентаря', 'ID пользователя', 'Дата брони', 'Занятие'][section] if role == Qt.DisplayRole and orientation == Qt.Horizontal else None
        self.bookings_table.setModel(model)

    def add_booking_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('Добавить бронирование')
        layout = QFormLayout()
        inventory_id = QSpinBox()
        booking_date = QDateEdit(QDate.currentDate())
        class_ = QLineEdit()
        add_btn = QPushButton('Забронировать')
        def add_booking():
            self.db.add_booking(inventory_id.value(), self.user_id, booking_date.date().toString('yyyy-MM-dd'), class_.text())
            self.db.log_action(self.user_id, f'Забронирован предмет {inventory_id.value()}')
            self.load_bookings()
            dialog.close()
        add_btn.clicked.connect(add_booking)
        layout.addRow('ID инвентаря', inventory_id)
        layout.addRow('Дата бронирования', booking_date)
        layout.addRow('Занятие', class_)
        layout.addRow(add_btn)
        dialog.setLayout(layout)
        dialog.exec_()

    def add_reports_tab(self):
        tab = QWidget()
        layout = QVBoxLayout()
        self.reports_table = QTableView()
        self.reports_model = ReportTableModel(self.db, self.user_id)
        self.reports_table.setModel(self.reports_model)
        self.reports_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.reports_table.clicked.connect(self.show_report)
        self.reports_table.doubleClicked.connect(self.edit_report)
        layout.addWidget(self.reports_table)

        toolbar = QHBoxLayout()
        export_btn = QPushButton('Экспорт')
        export_btn.clicked.connect(self.export_report)
        toolbar.addWidget(export_btn)
        layout.addLayout(toolbar)

        self.preview = QTextEdit()
        self.preview.setHtml('<h1>Выберите отчёт для предпросмотра</h1>')
        layout.addWidget(self.preview)

        tab.setLayout(layout)
        self.dock_layout.addWidget(QPushButton('Отчёты', clicked=lambda: self.tabs.setCurrentWidget(tab)))
        self.tabs.addTab(tab, 'Отчёты')

    def show_report(self, index):
        row = index.row()
        report_id = self.reports_model.data[row][0]
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT config FROM report_templates WHERE id = ?", (report_id,))
        config = json.loads(cursor.fetchone()[0])
        self.preview.setHtml(config.get('preview_html', '<h1>Отчёт</h1>'))

    def edit_report(self):
        row = self.reports_table.currentIndex().row()
        if row < 0:
            QMessageBox.warning(self, 'Ошибка', 'Выберите отчёт')
            return
        report_id = self.reports_model.data[row][0]
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT config FROM report_templates WHERE id = ?", (report_id,))
        config = json.loads(cursor.fetchone()[0])
        editor = ReportEditor(self.db, self.user_id, report_id, config)
        if editor.exec_():
            self.reports_model.refresh()
            self.db.log_report_action(report_id, self.user_id, f'Отредактирован отчёт {config["name"]}')
            self.show_report(self.reports_table.currentIndex())

    def export_report(self):
        row = self.reports_table.currentIndex().row()
        if row < 0:
            QMessageBox.warning(self, 'Ошибка', 'Выберите отчёт')
            return
        report_id = self.reports_model.data[row][0]
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT config FROM report_templates WHERE id = ?", (report_id,))
        config = json.loads(cursor.fetchone()[0])
        dialog = QDialog(self)
        dialog.setWindowTitle('Экспорт отчёта')
        layout = QFormLayout()
        format_selector = QComboBox()
        format_selector.addItems(['PDF', 'Excel', 'HTML'])
        layout.addRow('Формат', format_selector)
        export_btn = QPushButton('Экспортировать')
        def do_export():
            report = ReportGenerator(self.db, config, format_selector.currentText().lower(), 'school_logo.png')
            filename = f'report_{report_id}.{format_selector.currentText().lower()}'
            report.export(filename)
            QMessageBox.information(self, 'Успех', f'Отчёт экспортирован: {filename}')
            self.db.log_report_action(report_id, self.user_id, f'Экспортирован отчёт в {format_selector.currentText()}')
            dialog.close()
        export_btn.clicked.connect(do_export)
        layout.addRow(export_btn)
        dialog.setLayout(layout)
        dialog.exec_()

class StudentWindow(BaseMainWindow):
    def setup_ui(self):
        super().setup_ui()
        self.add_inventory_tab()
        self.add_bookings_tab()
        self.toolbar.addAction('Поиск', self.search_inventory)
        QShortcut(QKeySequence('Ctrl+F'), self, self.search_inventory)

    def add_inventory_tab(self):
        tab = QWidget()
        layout = QVBoxLayout()
        self.inventory_table = QTableView()
        self.model = InventoryTableModel(self.db)
        self.inventory_table.setModel(self.model)
        self.inventory_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.inventory_table)

        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        search_btn = QPushButton('Поиск')
        search_btn.clicked.connect(self.search_inventory)
        search_layout.addWidget(QLabel('Поиск:'))
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(search_btn)
        layout.addLayout(search_layout)

        qr_scan_btn = QPushButton('Сканировать QR-код')
        qr_scan_btn.clicked.connect(self.scan_qr)
        layout.addWidget(qr_scan_btn)

        tab.setLayout(layout)
        self.dock_layout.addWidget(QPushButton('Инвентарь', clicked=lambda: self.tabs.setCurrentWidget(tab)))
        self.tabs.addTab(tab, 'Инвентарь')

    def search_inventory(self):
        query = self.search_input.text()
        items = self.db.search_inventory(query)
        self.model.data = items
        self.model.layoutChanged.emit()

    def scan_qr(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('Сканировать QR-код')
        layout = QVBoxLayout()
        qr_input = QLineEdit()
        layout.addWidget(QLabel('Введите данные QR-кода:'))
        layout.addWidget(qr_input)
        scan_btn = QPushButton('Поиск')
        def search_qr():
            data = qr_input.text()
            if 'ID инвентаря' in data:
                id = int(data.split(':')[1].split('-')[0].strip())
                items = self.db.search_inventory(str(id))
                self.model.data = items
                self.model.layoutChanged.emit()
                dialog.close()
        scan_btn.clicked.connect(search_qr)
        layout.addWidget(scan_btn)
        dialog.setLayout(layout)
        dialog.exec_()

    def add_bookings_tab(self):
        tab = QWidget()
        layout = QVBoxLayout()
        self.bookings_table = QTableView()
        self.load_bookings()
        self.bookings_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.bookings_table)
        tab.setLayout(layout)
        self.dock_layout.addWidget(QPushButton('Мои бронирования', clicked=lambda: self.tabs.setCurrentWidget(tab)))
        self.tabs.addTab(tab, 'Мои бронирования')

    def load_bookings(self):
        bookings = self.db.get_bookings(self.user_id)
        model = QAbstractTableModel()
        model.data = bookings
        model.rowCount = lambda parent=None: len(bookings)
        model.columnCount = lambda parent=None: 5
        model.data = lambda index, role=Qt.DisplayRole: str(bookings[index.row()][index.column()]) if role == Qt.DisplayRole else None
        model.headerData = lambda section, orientation, role=Qt.DisplayRole: ['ID', 'ID инвентаря', 'ID пользователя', 'Дата брони', 'Занятие'][section] if role == Qt.DisplayRole and orientation == Qt.Horizontal else None
        self.bookings_table.setModel(model)

if __name__ == '__main__':
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    app = QApplication(sys.argv)
    app.setStyleSheet("""
        QWidget {
            background-color: #f8f9fa;
            font-family: Arial, sans-serif;
            font-size: 14px;
        }
        QMainWindow {
            background-color: #ffffff;
        }
        QPushButton {
            background-color: #007bff;
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 4px;
        }
        QPushButton:hover {
            background-color: #0056b3;
        }
        QLineEdit, QComboBox, QSpinBox, QDateEdit, QTextEdit {
            border: 1px solid #ced4da;
            padding: 6px;
            border-radius: 4px;
            background-color: white;
        }
        QTableView {
            border: 1px solid #dee2e6;
            gridline-color: #dee2e6;
            selection-background-color: #007bff;
            selection-color: white;
        }
        QTabWidget::pane {
            border: 1px solid #dee2e6;
        }
        QLabel {
            color: #212529;
        }
    """)
    login = LoginDialog()
    if login.exec_() == QDialog.Accepted:
        if login.role == 'Admin':
            window = AdminWindow(login.user_id, login.role)
        elif login.role == 'Teacher':
            window = TeacherWindow(login.user_id, login.role)
        else:
            window = StudentWindow(login.user_id, login.role)
        window.show()
        sys.exit(app.exec_())
    else:
        sys.exit(0)