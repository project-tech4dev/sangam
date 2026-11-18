"""Fingerprints: the same page or report, spaced, encoded or re-exported differently, hashes the same."""

import hashlib
import io

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.ingest.reading.fetch import document_hash
from app.ingest.reading.fingerprint import bytes_hash, normalise, text_hash

ZERO_WIDTH, SOFT_HYPHEN, BOM, NBSP = chr(0x200B), chr(0x00AD), chr(0xFEFF), chr(0x00A0)
E_ACUTE, COMBINING_ACUTE = chr(0x00E9), chr(0x0301)


class TestNormalise:
    def test_spacing_does_not_matter(self):
        assert normalise("a  b\n") == normalise("a b") == "a b"

    def test_line_breaks_and_tabs_collapse(self):
        assert normalise("  a\n\n\tb \r\n c  ") == "a b c"

    def test_nfc_and_nfd_are_equal(self):
        assert normalise("Caf" + E_ACUTE) == normalise("Cafe" + COMBINING_ACUTE)

    def test_case_is_kept(self):
        assert normalise("A") != normalise("a")

    def test_invisible_characters_are_dropped(self):
        assert normalise(f"a{ZERO_WIDTH} b{SOFT_HYPHEN}c{BOM}") == "a bc"

    def test_a_non_breaking_space_is_a_space(self):
        assert normalise(f"a{NBSP}{NBSP}b") == "a b"

    def test_a_changed_word_still_differs(self):
        assert normalise("grants of 400 crore") != normalise("grants of 500 crore")


class TestTextHash:
    def test_two_spacings_hash_the_same(self):
        assert text_hash("Grants of 400 crore\n\n\nin Assam.") == text_hash("Grants of 400 crore in Assam.")

    def test_one_changed_word_hashes_differently(self):
        assert text_hash("Grants of 400 crore") != text_hash("Grants of 500 crore")

    def test_it_is_sha256_of_the_normalised_text(self):
        assert text_hash(" a  b ") == hashlib.sha256(b"a b").hexdigest()


def _pdf(text: str, modified: str) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(300, 200)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    fonts = DictionaryObject({NameObject("/F1"): writer._add_object(font)})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): fonts})
    content = DecodedStreamObject()
    content.set_data(f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode() if text else b"")
    page[NameObject("/Contents")] = writer._add_object(content)
    writer.add_metadata({"/ModDate": modified})
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


class TestDocumentHash:
    def test_a_re_export_with_a_new_date_is_not_a_change(self, tmp_path):
        first, second = tmp_path / "a.pdf", tmp_path / "b.pdf"
        first.write_bytes(_pdf("Annual report 2026", "D:20260101000000Z"))
        second.write_bytes(_pdf("Annual report 2026", "D:20261118000000Z"))
        assert first.read_bytes() != second.read_bytes()
        assert document_hash(first) == document_hash(second)

    def test_changed_text_in_a_pdf_is_a_change(self, tmp_path):
        first, second = tmp_path / "a.pdf", tmp_path / "b.pdf"
        first.write_bytes(_pdf("Annual report 2026", "D:20260101000000Z"))
        second.write_bytes(_pdf("Annual report 2027", "D:20260101000000Z"))
        assert document_hash(first) != document_hash(second)

    def test_a_pdf_with_no_text_hashes_its_bytes(self, tmp_path):
        scan = tmp_path / "scan.pdf"
        scan.write_bytes(_pdf("", "D:20260101000000Z"))
        assert document_hash(scan) == bytes_hash(scan.read_bytes())

    def test_a_broken_pdf_hashes_its_bytes(self, tmp_path):
        broken = tmp_path / "broken.pdf"
        broken.write_bytes(b"not a pdf at all")
        assert document_hash(broken) == bytes_hash(b"not a pdf at all")

    def test_another_file_hashes_its_bytes(self, tmp_path):
        word = tmp_path / "report.docx"
        word.write_bytes(b"PK zipped")
        assert document_hash(word) == bytes_hash(b"PK zipped")
