from __future__ import annotations

from pathlib import Path
import os
import queue
import sys
import tempfile
import time
import unittest
import zipfile
from unittest.mock import Mock, patch
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

    def test_readable_text_formats_support_utf8_utf16_bom_and_cp1251(self):
        (self.root / "report.csv").write_text("month,amount\nМай,1200", encoding="utf-8")
        (self.root / "settings.json").write_bytes('{"имя":"Астра"}'.encode("utf-16"))
        (self.root / "script.ps1").write_bytes("Write-Output 'Привет'".encode("cp1251"))
        (self.root / "payload.exe").write_text("not a readable document", encoding="utf-8")

        self.assertEqual(self.workspace.read_text("report.csv"), "month,amount\r\nМай,1200")
        self.assertEqual(self.workspace.read_text("settings.json"), '{"имя":"Астра"}')
        self.assertEqual(self.workspace.read_text("script.ps1"), "Write-Output 'Привет'")
        self.assertEqual(self.workspace.checked_readable_file("script.ps1"), self.root / "script.ps1")
        with self.assertRaisesRegex(WorkspaceDenied, "нельзя открывать"):
            self.workspace.checked_openable_file("script.ps1")
        with self.assertRaisesRegex(WorkspaceDenied, "не поддерживается"):
            self.workspace.read_text("payload.exe")

    def test_html_read_extracts_visible_text_without_granting_open_permission(self):
        (self.root / "guide.html").write_text(
            """<!doctype html><html><head><title>Заголовок окна</title></head><body>
            <main><h1>Привет &amp; мир</h1><p>Текст <strong>для чтения</strong>.</p>
            <div hidden>скрытый блок</div><span aria-hidden="true">скрытая метка</span>
            <div style="display: none">скрытый стиль</div>
            <script>скрытый скрипт</script><script/>скрытая запись</script>
            <style>.secret { color: red }</style>
            <template>шаблон</template><noscript>fallback</noscript><svg>vector label</svg>
            <canvas>canvas fallback</canvas><iframe>встроенное содержимое</iframe>
            <pre>    code one
      code two</pre>
            <p>Конец</p></main></body></html>""",
            encoding="utf-8",
        )

        self.assertEqual(
            self.workspace.read_text("guide.html"),
            "Привет & мир\nТекст для чтения.\n    code one\n      code two\nКонец",
        )
        self.assertEqual(self.workspace.checked_readable_file("guide.html"), self.root / "guide.html")
        with self.assertRaisesRegex(WorkspaceDenied, "тип файла"):
            self.workspace.checked_openable_file("guide.html")

        (self.root / "guide.htm").write_text("<p>Короткая версия</p>", encoding="utf-8")
        self.assertEqual(self.workspace.read_text("guide.htm"), "Короткая версия")

    def test_html_read_honors_cancellation_while_parsing(self):
        (self.root / "long.html").write_text("<p>строка</p>" * 100, encoding="utf-8")
        checks = 0

        def cancel_after_some_parser_events():
            nonlocal checks
            checks += 1
            return checks >= 12

        with self.assertRaisesRegex(WorkspaceDenied, "отменено"):
            self.workspace.read_text("long.html", is_cancelled=cancel_after_some_parser_events)
        self.assertLess(checks, 20)

    def test_file_question_retrieval_can_read_a_selected_csv_without_model_or_network(self):
        from src.file_rag import FileQuestionSession

        (self.root / "budget.csv").write_text(
            "month,amount\nMay,1200\nJune,1800", encoding="utf-8"
        )
        passages, _digest = FileQuestionSession(
            self.workspace, "budget.csv"
        ).retrieve("amount")

        self.assertTrue(passages)
        self.assertTrue(any("June,1800" in passage.text for passage in passages))

    def test_exact_name_scan_is_bounded_and_reports_duplicate_basenames(self):
        (self.root / "report.pdf").write_bytes(b"one")
        self.assertEqual([item.path for item in self.workspace.find_exact_name("report.pdf")], ["report.pdf"])
        nested = self.root / "nested"
        nested.mkdir()
        (nested / "report.pdf").write_bytes(b"two")
        self.assertEqual(len(self.workspace.find_exact_name("REPORT.PDF")), 2)
        with patch.object(FileWorkspace, "MAX_VISITED", 1):
            with self.assertRaisesRegex(WorkspaceDenied, "предел"):
                self.workspace.find_exact_name("missing.pdf")
        with self.assertRaises(WorkspaceDenied):
            self.workspace.find_exact_name("../report.pdf")

    def test_voice_open_rechecks_path_and_allows_only_document_or_media_suffixes(self):
        (self.root / "report.pdf").write_bytes(b"pdf")
        (self.root / "script.ps1").write_text("Write-Host unsafe", encoding="utf-8")
        self.assertEqual(self.workspace.checked_openable_file("report.pdf"), self.root / "report.pdf")
        with self.assertRaisesRegex(WorkspaceDenied, "тип файла"):
            self.workspace.checked_openable_file("script.ps1")
        with self.assertRaises(WorkspaceDenied):
            self.workspace.checked_openable_file(".env")

    def test_search_stops_when_cancelled_during_directory_scan(self):
        for index in range(30):
            (self.root / f"report-{index:02}.txt").write_text("x", encoding="utf-8")

        checks = 0

        def cancel_after_some_entries():
            nonlocal checks
            checks += 1
            return checks >= 8

        with self.assertRaisesRegex(WorkspaceDenied, "отменён"):
            self.workspace.search("report", is_cancelled=cancel_after_some_entries)
        self.assertLess(checks, 12)

    def test_search_stops_when_plan_deadline_expires(self):
        with self.assertRaisesRegex(WorkspaceDenied, "лимит времени"):
            self.workspace.search("", deadline=time.monotonic() - 1)

    def test_search_checks_deadline_before_returning_empty_results(self):
        empty_root = self.root / "empty"
        empty_root.mkdir()
        empty_workspace = FileWorkspace(empty_root)
        with patch("src.file_workspace.time.monotonic", side_effect=[1, 1, 51]):
            with self.assertRaisesRegex(WorkspaceDenied, "лимит времени"):
                empty_workspace.search("", deadline=50)

    def test_read_text_passes_cancellation_into_document_parser(self):
        import threading

        (self.root / "report.pdf").write_bytes(b"mock pdf")
        cancelled = threading.Event()

        def cancel_during_parse(_data, *, check_limits):
            cancelled.set()
            check_limits()

        with patch.object(self.workspace, "_extract_pdf", side_effect=cancel_during_parse):
            with self.assertRaisesRegex(WorkspaceDenied, "отменено"):
                self.workspace.read_text("report.pdf", is_cancelled=cancelled.is_set)

    def test_read_text_rejects_an_expired_plan_deadline(self):
        with self.assertRaisesRegex(WorkspaceDenied, "лимит времени"):
            self.workspace.read_text("notes.txt", deadline=time.monotonic() - 1)

    def test_pdf_extraction_checks_limits_between_pages(self):
        from types import SimpleNamespace

        class Page:
            def get_contents(self):
                return None

            def extract_text(self):
                return "страница"

        pages = [Page(), Page(), Page()]
        reader = SimpleNamespace(is_encrypted=False, pages=pages)
        checks = 0

        def stop_before_second_page():
            nonlocal checks
            checks += 1
            if checks >= 5:
                raise WorkspaceDenied("Чтение отменено пользователем")

        with patch("pypdf.PdfReader", return_value=reader):
            with self.assertRaisesRegex(WorkspaceDenied, "отменено"):
                FileWorkspace._extract_pdf(b"mock pdf", check_limits=stop_before_second_page)
        self.assertEqual(checks, 5)

    def test_conversation_reset_event_roundtrips_through_desktop_bridge_parser(self):
        import json
        from src.runtime_events import PREFIX
        line = PREFIX + json.dumps(
            {"version": 1, "type": "conversation_reset", "text": ""},
            ensure_ascii=False,
        )
        self.assertEqual(parse_event(line), ("conversation_reset", ""))
        unsupported = PREFIX + json.dumps(
            {"version": 1, "type": "clear_all_user_data", "text": ""},
        )
        self.assertIsNone(parse_event(unsupported))

    def test_file_search_event_and_voice_reply_use_strict_protocols(self):
        import json
        from src.desktop_file_search import (
            encode_file_result,
            make_file_open_request,
            make_file_open_result,
            make_file_read_request,
            make_file_read_result,
            make_search_request,
            make_search_result,
            parse_control_line,
        )
        from src.runtime_events import PREFIX

        request = make_search_request("a" * 32, "contract")
        line = PREFIX + json.dumps(
            {"version": 1, "type": "file_search_request", "text": json.dumps(request)},
            ensure_ascii=False,
        )
        self.assertEqual(parse_event(line), ("file_search_request", json.dumps(request, ensure_ascii=False)))
        open_request = make_file_open_request("b" * 32, "report.pdf")
        open_line = PREFIX + json.dumps(
            {"version": 1, "type": "file_open_request", "text": json.dumps(open_request)},
            ensure_ascii=False,
        )
        self.assertEqual(parse_event(open_line), ("file_open_request", json.dumps(open_request, ensure_ascii=False)))
        read_request = make_file_read_request("c" * 32, "memo.txt")
        read_line = PREFIX + json.dumps(
            {"version": 1, "type": "file_read_request", "text": json.dumps(read_request)},
            ensure_ascii=False,
        )
        self.assertEqual(parse_event(read_line), ("file_read_request", json.dumps(read_request, ensure_ascii=False)))

        process = Mock()
        process.poll.return_value = None
        bridge = DesktopBridge(ROOT)
        bridge.process = process
        bridge.mode = "voice"
        result = make_search_result("a" * 32, "ok", 1, ["Reports\\contract.pdf"])
        self.assertTrue(bridge.reply_file_search(result))
        control_line = process.stdin.write.call_args.args[0]
        self.assertEqual(parse_control_line(control_line.rstrip()), result)
        read_result = make_file_read_result("c" * 32, "ok", "memo.txt", "private content")
        self.assertTrue(bridge.reply_file_request(read_result))
        read_control_line = process.stdin.write.call_args.args[0]
        self.assertEqual(parse_control_line(read_control_line.rstrip()), read_result)
        bridge.mode = "text"
        self.assertFalse(bridge.reply_file_search(result))
        replacement_process = Mock()
        replacement_process.poll.return_value = None
        bridge.process = replacement_process
        bridge.mode = "voice"
        self.assertFalse(bridge.reply_file_search(result, expected_process=process))
        replacement_process.stdin.write.assert_not_called()
        opened = make_file_open_result("c" * 32, "ok", "report.pdf")
        self.assertTrue(bridge.reply_file_request(opened, expected_process=replacement_process))
        self.assertEqual(parse_control_line(replacement_process.stdin.write.call_args.args[0].rstrip()), opened)

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
