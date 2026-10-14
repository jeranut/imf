# -*- coding: utf-8 -*-
"""Lecture et écriture minimales d'un classeur .xlsx (sans openpyxl, absent de l'environnement) : le modèle Excel de la
balance d'ouverture est écrit avec xlsxwriter (déjà utilisé par les rapports) et relu ici avec zipfile + XML."""
import io
import re
import zipfile
from datetime import date, datetime, timedelta
from xml.etree import ElementTree

import xlsxwriter

NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
HEADERS = ['Code du compte', 'Libellé du compte (information)', 'Partenaire (facultatif)', 'Débit', 'Crédit']


def _column_index(reference):
    letters = re.match(r'[A-Z]+', reference).group(0)
    index = 0
    for char in letters:
        index = index * 26 + (ord(char) - 64)
    return index - 1


def _open_book(content):
    try:
        return zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as error:
        raise ValueError("Le fichier n'est pas un classeur Excel (.xlsx) lisible.") from error


def _shared_strings(book):
    shared = []
    if 'xl/sharedStrings.xml' in book.namelist():
        for item in ElementTree.fromstring(book.read('xl/sharedStrings.xml')).findall('m:si', NS):
            shared.append(''.join(t.text or '' for t in item.iter('{%s}t' % NS['m'])))
    return shared


def _read_sheet(book, path, shared):
    root = ElementTree.fromstring(book.read(path))
    rows = []
    for row in root.iter('{%s}row' % NS['m']):
        values = {}
        for cell in row.findall('m:c', NS):
            kind, node = cell.get('t'), cell.find('m:v', NS)
            if kind == 's' and node is not None:
                value = shared[int(node.text)]
            elif kind == 'inlineStr':
                value = ''.join(t.text or '' for t in cell.iter('{%s}t' % NS['m']))
            elif node is not None:
                value = node.text
                if kind in (None, 'n'):
                    try:
                        value = float(value)
                    except (TypeError, ValueError):
                        pass
            else:
                value = None
            values[_column_index(cell.get('r'))] = value
        width = max(values) + 1 if values else 0
        rows.append((int(row.get('r')), [values.get(i) for i in range(width)]))
    return rows


def read_rows(content):
    """Lignes de la première feuille : liste de (numéro de ligne Excel, liste de valeurs). Lève ValueError si le fichier
    n'est pas un .xlsx lisible."""
    book = _open_book(content)
    try:
        sheet_name = sorted(n for n in book.namelist() if re.match(r'xl/worksheets/sheet\d+\.xml$', n))[0]
        return _read_sheet(book, sheet_name, _shared_strings(book))
    except (KeyError, IndexError, ElementTree.ParseError) as error:
        raise ValueError("Le fichier n'est pas un classeur Excel (.xlsx) lisible.") from error


def read_sheets(content):
    """Toutes les feuilles : dict {nom de la feuille: lignes (numéro Excel, valeurs)}, dans l'ordre du classeur. Lève
    ValueError si le fichier n'est pas un .xlsx lisible."""
    book = _open_book(content)
    try:
        shared = _shared_strings(book)
        rels = {}
        for rel in ElementTree.fromstring(book.read('xl/_rels/workbook.xml.rels')):
            target = rel.get('Target')
            rels[rel.get('Id')] = target.lstrip('/') if target.startswith('/') else 'xl/' + target
        sheets = {}
        for sheet in ElementTree.fromstring(book.read('xl/workbook.xml')).iter('{%s}sheet' % NS['m']):
            rid = sheet.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
            sheets[sheet.get('name')] = _read_sheet(book, rels[rid], shared)
        return sheets
    except (KeyError, IndexError, ElementTree.ParseError) as error:
        raise ValueError("Le fichier n'est pas un classeur Excel (.xlsx) lisible.") from error


def to_date(value):
    """Date lue dans une cellule : numéro de série Excel (système 1900) ou texte « jj/mm/aaaa » / « aaaa-mm-jj ».
    Lève ValueError si invalide ; None si la cellule est vide."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, (int, float)):
        if value != value or not 1 <= value < 2958466:
            raise ValueError(value)
        return date(1899, 12, 30) + timedelta(days=int(value))
    text = str(value).strip()
    for pattern in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y', '%d/%m/%y'):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    raise ValueError(value)


def build_template(company_name, date, lines, instructions):
    """Classeur modèle : feuille « Balance » (une ligne par compte du modèle, montants à zéro) et feuille « Mode d'emploi »."""
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    bold = workbook.add_format({'bold': True, 'bg_color': '#D9E1F2', 'border': 1})
    money = workbook.add_format({'num_format': '#,##0.00'})
    sheet = workbook.add_worksheet('Balance')
    sheet.write_row(0, 0, HEADERS, bold)
    for row, (code, label, partner, debit, credit) in enumerate(lines, start=1):
        sheet.write_string(row, 0, code)
        sheet.write_string(row, 1, label or '')
        sheet.write_string(row, 2, partner or '')
        sheet.write_number(row, 3, debit, money)
        sheet.write_number(row, 4, credit, money)
    sheet.set_column(0, 0, 16)
    sheet.set_column(1, 2, 46)
    sheet.set_column(3, 4, 18)
    sheet.freeze_panes(1, 0)
    help_sheet = workbook.add_worksheet("Mode d'emploi")
    help_sheet.set_column(0, 0, 110)
    help_sheet.write(0, 0, "Balance d'ouverture - %s - au %s" % (company_name, date), workbook.add_format({'bold': True}))
    for row, text in enumerate(instructions, start=2):
        help_sheet.write(row, 0, text)
    workbook.close()
    return output.getvalue()


def build_workbook(sheets, instructions, title):
    """Classeur à plusieurs feuilles. `sheets` : liste de {'name', 'headers', 'rows', 'text_columns', 'money_columns'} ;
    les colonnes « texte » (référence, CIN, téléphone, dates) sont écrites en cellules texte (zéros de tête et chiffres
    longs conservés). Dernière feuille : « Mode d'emploi »."""
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    bold = workbook.add_format({'bold': True, 'bg_color': '#D9E1F2', 'border': 1, 'text_wrap': True})
    money = workbook.add_format({'num_format': '#,##0.00'})
    text = workbook.add_format({'num_format': '@'})
    for spec in sheets:
        sheet = workbook.add_worksheet(spec['name'])
        sheet.write_row(0, 0, spec['headers'], bold)
        for col in range(len(spec['headers'])):
            sheet.set_column(col, col, 24, text if col in spec.get('text_columns', ()) else None)
        for number, row in enumerate(spec['rows'], start=1):
            for col, value in enumerate(row):
                if col in spec.get('text_columns', ()):
                    sheet.write_string(number, col, '%s' % (value if value is not None else ''), text)
                elif isinstance(value, (int, float)):
                    sheet.write_number(number, col, value, money if col in spec.get('money_columns', ()) else None)
                elif value is not None:
                    sheet.write_string(number, col, value)
        sheet.freeze_panes(1, 0)
    help_sheet = workbook.add_worksheet("Mode d'emploi")
    help_sheet.set_column(0, 0, 120)
    help_sheet.write(0, 0, title, workbook.add_format({'bold': True}))
    for row, line in enumerate(instructions, start=2):
        help_sheet.write(row, 0, line)
    workbook.close()
    return output.getvalue()
