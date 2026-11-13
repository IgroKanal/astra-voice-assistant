from __future__ import annotations

from pathlib import Path
import os
import queue
import sys
import tempfile
import time
import unittest
import zipfile
from unittest.mock import patch
from io import BytesIO

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.desktop_bridge import DesktopBridge
from src.file_workspace import FileWorkspace, WorkspaceDenied
from src.runtime_events import parse_event


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="astra-workspace-test-", dir=ROOT)
        self.root = Path(self.temp.name)
        (self.root / "notes.txt").write_text("Привет, Астра", encoding="utf-8")
        (self.root / ".env").write_text("TOKEN=test", encoding="utf-8")
        self.workspace = FileWorkspace(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_read_and_search(self):
        self.assertEqual(self.workspace.read_text("notes.txt"), "Привет, Астра")
        self.assertEqual([item.path for item in self.workspace.search()], ["notes.txt"])

    def test_traversal_secrets_and_absolute_paths(self):
        for value in ("../notes.txt", str(self.root / "notes.txt"), ".env", "notes.txt:stream"):
            with self.subTest(value=value), self.assertRaises(WorkspaceDenied):
                self.workspace.read_text(value)

    def test_large_and_binary_files(self):
        (self.root / "binary.bin").write_bytes(b"\x00test")
        (self.root / "large.txt").write_bytes(b"x" * (FileWorkspace.MAX_READ_BYTES + 1))
        for name in ("binary.bin", "large.txt"):
            with self.assertRaises(WorkspaceDenied):
                self.workspace.read_text(name)

    def test_selected_image_preview_is_bounded_and_strips_metadata(self):
        from PIL import Image
        image = Image.new("RGB", (2400, 1200), (70, 40, 180))
        metadata = image.getexif()
        metadata[315] = "private test metadata"
        encoded = BytesIO()
        image.save(encoded, format="JPEG", exif=metadata)
        (self.root / "picture.jpg").write_bytes(encoded.getvalue())
        preview = self.workspace.preview_image("picture.jpg")
        self.assertEqual((preview.image_format, preview.original_width, preview.original_height), ("JPEG", 2400, 1200))
        with Image.open(BytesIO(preview.png)) as result:
            self.assertEqual(result.format, "PNG")
            self.assertEqual(result.size, (1600, 800))
            self.assertFalse(result.getexif())

    def test_image_preview_rejects_unsupported_oversize_and_corrupt_inputs(self):
        from PIL import Image
        (self.root / "vector.svg").write_text("<svg/>", encoding="utf-8")
        (self.root / "broken.png").write_bytes(b"not an image")
        huge = BytesIO()
        Image.new("RGB", (FileWorkspace.MAX_IMAGE_SIDE + 1, 1)).save(huge, format="PNG")
        (self.root / "huge.png").write_bytes(huge.getvalue())
        (self.root / "too-large.png").write_bytes(b"x" * (FileWorkspace.MAX_IMAGE_BYTES + 1))
        for name in ("vector.svg", "broken.png", "huge.png", "too-large.png"):
            with self.subTest(name=name), self.assertRaises(WorkspaceDenied):
                self.workspace.preview_image(name)

    def test_docx_paragraphs_and_tables_are_read_without_extracting_the_zip(self):
        from src.file_workspace import FileWorkspace
        xml = '''<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Привет DOCX</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>Ячейка A</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Ячейка B</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>'''.encode("utf-8")
        with zipfile.ZipFile(self.root / "report.docx", "w", zipfile.ZIP_DEFLATED) as package:
            package.writestr("word/document.xml", xml)
            package.writestr("word/media/ignored.bin", b"\x00" * 100)
        self.assertEqual(self.workspace.read_text("report.docx"), "Привет DOCX\nЯчейка A\nЯчейка B")

    def test_docx_xml_entity_declarations_are_rejected(self):
        xml = '<!DOCTYPE x [<!ENTITY secret "unsafe">]><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>&secret;</w:t></w:r></w:p></w:body></w:document>'.encode("utf-8")
        with zipfile.ZipFile(self.root / "unsafe.docx", "w", zipfile.ZIP_DEFLATED) as package:
            package.writestr("word/document.xml", xml)
        with self.assertRaises(WorkspaceDenied):
            self.workspace.read_text("unsafe.docx")

    def test_docx_xml_expansion_limit_is_enforced(self):
        xml = b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>too large</w:t></w:r></w:p></w:body></w:document>'
        with zipfile.ZipFile(self.root / "large.docx", "w", zipfile.ZIP_DEFLATED) as package:
            package.writestr("word/document.xml", xml)
        with patch.object(FileWorkspace, "MAX_DOCX_XML_BYTES", 8), self.assertRaisesRegex(WorkspaceDenied, "допустимый основной документ"):
            self.workspace.read_text("large.docx")

    def test_xlsx_reads_shared_inline_and_cached_formula_values(self):
        parts = {
            "xl/workbook.xml": '''<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Сводка" sheetId="1" r:id="rId1"/></sheets></workbook>''',
            "xl/_rels/workbook.xml.rels": '''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rExternal" TargetMode="External" Target="https://example.test/book.xlsx"/></Relationships>''',
            "xl/sharedStrings.xml": '''<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>Доходы</t></si></sst>''',
            "xl/worksheets/sheet1.xml": '''<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="inlineStr"><is><t>Значение</t></is></c></row><row r="2"><c r="B2"><f>SUM(B1:B1)</f><v>42</v></c></row></sheetData></worksheet>''',
        }
        with zipfile.ZipFile(self.root / "budget.xlsx", "w", zipfile.ZIP_DEFLATED) as package:
            for name, xml in parts.items():
                package.writestr(name, xml.encode("utf-8"))
        self.assertEqual(self.workspace.read_text("budget.xlsx"), "[Лист: Сводка]\nA1: Доходы\nB1: Значение\nB2: 42")

    def test_pptx_follows_presentation_order_and_extracts_slide_text(self):
        parts = {
            "ppt/presentation.xml": '''<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:sldIdLst><p:sldId id="1" r:id="rIdFirst"/><p:sldId id="2" r:id="rIdSecond"/></p:sldIdLst></p:presentation>''',
            "ppt/_rels/presentation.xml.rels": '''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rIdFirst" Target="slides/slide2.xml"/><Relationship Id="rIdSecond" Target="slides/slide1.xml"/></Relationships>''',
            "ppt/slides/slide1.xml": '''<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>Второй</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>''',
            "ppt/slides/slide2.xml": '''<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>Первый</a:t></a:r><a:r><a:t> слайды</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>''',
        }
        with zipfile.ZipFile(self.root / "briefing.pptx", "w", zipfile.ZIP_DEFLATED) as package:
            for name, xml in parts.items():
                package.writestr(name, xml.encode("utf-8"))
        self.assertEqual(self.workspace.read_text("briefing.pptx"), "[Слайд 1]\nПервый слайды\n\n[Слайд 2]\nВторой")

    def test_pdf_text_is_extracted_with_page_numbers(self):
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
        writer = PdfWriter()
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
        contents = DecodedStreamObject()
        contents.set_data(b"BT /F1 12 Tf 72 720 Td (Hello PDF) Tj ET")
        page[NameObject("/Contents")] = contents
        pdf = BytesIO()
        writer.write(pdf)
        (self.root / "report.pdf").write_bytes(pdf.getvalue())
        self.assertIn("[Страница 1]\nHello PDF", self.workspace.read_text("report.pdf"))

    def test_encrypted_pdf_is_rejected(self):
        from pypdf import PdfWriter
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        writer.encrypt("secret")
        pdf = BytesIO()
        writer.write(pdf)
        (self.root / "locked.pdf").write_bytes(pdf.getvalue())
        with self.assertRaisesRegex(WorkspaceDenied, "Зашифрованный PDF"):
            self.workspace.read_text("locked.pdf")

    def test_pdf_page_limit_is_enforced(self):
        from pypdf import PdfWriter
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        pdf = BytesIO()
        writer.write(pdf)
        (self.root / "many.pdf").write_bytes(pdf.getvalue())
        with patch.object(FileWorkspace, "MAX_PDF_PAGES", 0), self.assertRaisesRegex(WorkspaceDenied, "PDF больше 200 страниц"):
            self.workspace.read_text("many.pdf")

    def test_symlink_does_not_expand_grant(self):
        try:
            (self.root / "link.txt").symlink_to(self.root / "notes.txt")
        except OSError:
            self.skipTest("Symlink privilege unavailable")
        with self.assertRaises(WorkspaceDenied):
            self.workspace.read_text("link.txt")

    def test_hardlink_does_not_expand_grant_to_an_external_file(self):
        base = self.root
        allowed = base / "allowed"
        allowed.mkdir()
        external = base / "outside.txt"
        external.write_text("outside the selected workspace", encoding="utf-8")
        try:
            os.link(external, allowed / "linked.txt")
        except OSError:
            self.skipTest("Hard links are unavailable on this filesystem")
        restricted = FileWorkspace(allowed)
        with self.assertRaises(WorkspaceDenied):
            restricted.read_text("linked.txt")


class DesktopIntegrationTests(unittest.TestCase):
    def test_real_runtime_roundtrip_and_stop(self):
        bridge = DesktopBridge(ROOT)
        try:
            bridge.start("text")
            with self.assertRaises(ValueError):
                bridge.send("Астра, время\nАстра, стоп")
            bridge.send("Астра, сколько времени")
            deadline = time.monotonic() + 30
            response = ""
            while time.monotonic() < deadline:
                try:
                    kind, text = bridge.events.get(timeout=0.5)
                except queue.Empty:
                    continue
                if kind == "assistant":
                    response = text
                    break
            self.assertTrue(response)
            self.assertTrue(bridge.running)
            with self.assertRaises(RuntimeError):
                bridge.start("text")
        finally:
            bridge.stop()
        self.assertFalse(bridge.running)

    def test_protocol_validation(self):
        self.assertEqual(parse_event('Ты: @ASTRA_EVENT {"version":1,"type":"assistant","text":"Привет"}'), ("assistant", "Привет"))
        for line in ('@ASTRA_EVENT []', '@ASTRA_EVENT {"version":2,"type":"assistant","text":"x"}', '@ASTRA_EVENT nope', '@ASTRA_EVENT {"version":1,"type":"shell","text":"x"}'):
            self.assertIsNone(parse_event(line))


if __name__ == "__main__":
    unittest.main(verbosity=2)
