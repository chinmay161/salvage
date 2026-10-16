"""WPD: WordPerfect 5.x document format decoder.

Format layout:
- Begins with a 16-byte fixed identification header:
  - 0x00: magic bytes 0xFF 'W' 'P' 'C' (\\xFFWPC)
  - 0x04: u32le document text pointer
  - 0x08: u8 product type (1 = WordPerfect)
  - 0x09: u8 file type / major version (10 = WP 5.x)
  - 0x0A: u8 minor version (2)
  - 0x0B: u16le encryption key (0 = unencrypted)
  - 0x0D: 3 bytes reserved / padding
- Followed by document prefix area up to doc_ptr.
- Followed by document body text stream with function codes.
"""

from __future__ import annotations

import struct

from salvagekit.core.model import (Damage, DamageKind, DecodeResult, Field, Record,
                                  Status)
from salvagekit.core.plugin import Decoder
from salvagekit.core.reader import SafeReader
from salvagekit.core.standalone import run_standalone


class WpdDecoder(Decoder):
    """Decoder for WordPerfect 5.x document files."""

    name = "WPD"
    extensions = (".wpd",)

    def probe(self, data: bytes) -> float:
        """Probe for WPD: magic \\xFFWPC with WP product type and version."""
        try:
            if len(data) < 4:
                return 0.0
            if data[:4] != b"\xffWPC":
                return 0.0
            if len(data) >= 10 and data[8] == 1 and data[9] == 10:
                return 1.0
            return 0.7
        except Exception:
            return 0.0

    def decode(self, reader: SafeReader) -> DecodeResult:
        """Decode WPD file into metadata, paragraphs, page breaks, and damage."""
        size = reader.size
        result = DecodeResult(format=self.name, confidence=1.0)

        if size < 4 or reader.peek(4) != b"\xffWPC":
            return DecodeResult(format=self.name, confidence=0.0)

        if reader.remaining() < 16:
            reader.bytes(reader.remaining(), "header_fragment")
            result.damage.append(Damage(0, size, DamageKind.TRUNCATED, "header cut short", lossy=True))
            result.warnings.append("truncated header")
            return result

        reader.bytes(4, "magic")
        doc_ptr = reader.u32le("doc_pointer")
        prod_type = reader.u8("product_type")
        major_ver = reader.u8("major_version")
        minor_ver = reader.u8("minor_version")
        encrypt_key = reader.u16le("encrypt_key")
        reader.bytes(3, "padding")

        result.meta["product_type"] = prod_type
        result.meta["major_version"] = major_ver
        result.meta["minor_version"] = minor_ver

        if encrypt_key is not None and encrypt_key != 0:
            result.unsupported = True
            result.damage.append(Damage(11, 13, DamageKind.ENCRYPTED,
                                        "password protected / encrypted document", lossy=True))
            result.warnings.append("password protected / encrypted document")
            return result

        if doc_ptr is None or doc_ptr > size:
            result.damage.append(Damage(4, 8, DamageKind.OOB_POINTER,
                                        f"document text pointer {doc_ptr} beyond file size {size}",
                                        lossy=True))
            result.warnings.append("document text pointer beyond file size")
            return result

        if doc_ptr < 16:
            result.damage.append(Damage(4, 8, DamageKind.INVALID_VALUE,
                                        f"document text pointer {doc_ptr} inside header", lossy=True))
            result.warnings.append("invalid document text pointer")
            return result

        prefix_len = doc_ptr - reader.tell()
        trailing_pkt_off = None
        trailing_pkt_size = 0

        if prefix_len > 0:
            prefix_bytes = reader.bytes(prefix_len, "prefix_area")
            # Parse prefix packet table if present (entries start at table offset 14 / file offset 30)
            if prefix_len >= 22:
                num_packets = struct.unpack_from("<H", prefix_bytes, 2)[0]
                if 1 <= num_packets <= 100:
                    pkt_type, pkt_size, pkt_off = struct.unpack_from("<HHI", prefix_bytes, 14)
                    if pkt_type != 0 and doc_ptr <= pkt_off:
                        trailing_pkt_off = pkt_off
                        trailing_pkt_size = pkt_size

        body_off = reader.tell()
        body_end = min(size, trailing_pkt_off) if trailing_pkt_off is not None else size
        body_len = max(0, body_end - body_off)
        body = reader.bytes(body_len, "body_text")

        current_para: list[str] = []
        rec_idx = 0
        para_start = body_off

        def flush_para(end_off: int) -> None:
            nonlocal rec_idx, para_start
            text = "".join(current_para).strip("\r")
            current_para.clear()
            para_len = max(0, end_off - para_start)
            fields = [
                Field("index", rec_idx, para_start, para_len, Status.CONSISTENT),
                Field("type", "paragraph", para_start, para_len, Status.CONSISTENT),
                Field("text", text, para_start, para_len, Status.CONSISTENT),
            ]
            result.records.append(Record(offset=para_start, status=Status.CONSISTENT,
                                         kind="paragraph", fields=fields))
            rec_idx += 1
            para_start = end_off

        i = 0
        while i < body_len:
            b = body[i]
            curr_pos = body_off + i
            if b == 0x0A:  # Hard return -> paragraph break
                flush_para(curr_pos + 1)
                i += 1
            elif b in (0x0B, 0x0C):  # Page break
                if current_para:
                    flush_para(curr_pos)
                fields = [
                    Field("index", rec_idx, curr_pos, 1, Status.CONSISTENT),
                    Field("type", "page_break", curr_pos, 1, Status.CONSISTENT),
                    Field("text", "", curr_pos, 0, Status.CONSISTENT),
                ]
                result.records.append(Record(offset=curr_pos, status=Status.CONSISTENT,
                                             kind="page_break", fields=fields))
                rec_idx += 1
                para_start = curr_pos + 1
                i += 1
            elif b == 0x0D:  # Soft return -> soft line wrap space
                if current_para and not current_para[-1].endswith(" "):
                    current_para.append(" ")
                i += 1
            elif b == 0x09:  # Tab
                current_para.append("\t")
                i += 1
            elif b == 0xA0:  # Hard space
                current_para.append(" ")
                i += 1
            elif b == 0xAA:  # Soft hyphen -> stripped
                i += 1
            elif 32 <= b < 127:  # Printable ASCII
                current_para.append(chr(b))
                i += 1
            elif 0xC0 <= b <= 0xC7:  # Fixed 3-byte function code
                if i + 3 <= body_len and body[i + 2] == b:
                    i += 3
                else:
                    if i + 3 > body_len:
                        result.damage.append(Damage(curr_pos, size, DamageKind.TRUNCATED,
                                                    f"function code 0x{b:02x} cut short", lossy=True))
                        result.warnings.append("truncated function code")
                        break
                    i += 1
            elif 0xD0 <= b <= 0xFF:  # Variable multi-byte function code with length prefix
                if i + 4 <= body_len:
                    fn_len = struct.unpack_from("<H", body, i + 2)[0]
                    if fn_len >= 4 and i + fn_len <= body_len and body[i + fn_len - 1] == b:
                        i += fn_len
                        continue
                    if fn_len >= 4 and i + fn_len > body_len:
                        result.damage.append(Damage(curr_pos, size, DamageKind.TRUNCATED,
                                                    f"function code 0x{b:02x} length {fn_len} cut short",
                                                    lossy=True))
                        result.warnings.append("truncated variable function code")
                        break
                # Fallback: search for closing delimiter byte
                end_pos = body.find(bytes([b]), i + 1)
                if end_pos != -1:
                    i = end_pos + 1
                else:
                    result.damage.append(Damage(curr_pos, size, DamageKind.TRUNCATED,
                                                f"function code 0x{b:02x} unclosed", lossy=True))
                    result.warnings.append("unclosed function code")
                    break
            else:
                i += 1

        if current_para:
            flush_para(body_off + body_len)
            result.damage.append(Damage(body_off + body_len, size, DamageKind.TRUNCATED,
                                        "document text ends abruptly without closing paragraph delimiter",
                                        lossy=True))
            result.warnings.append("document text truncated")

        # Process trailing packet if declared
        if trailing_pkt_off is not None:
            if reader.remaining() > 0:
                avail = reader.remaining()
                reader.bytes(avail, "trailing_packet")
                if avail < trailing_pkt_size:
                    dmg_start = min(size, trailing_pkt_off)
                    result.damage.append(Damage(dmg_start, size, DamageKind.TRUNCATED,
                                                f"packet at offset {trailing_pkt_off} declared length {trailing_pkt_size} exceeds file size",
                                                lossy=True))
                    result.warnings.append("truncated trailing packet")
            elif size < trailing_pkt_off + trailing_pkt_size:
                # File cut before or inside trailing packet
                if not result.damage:
                    dmg_start = min(size, trailing_pkt_off)
                    result.damage.append(Damage(dmg_start, size, DamageKind.TRUNCATED,
                                                "missing trailing prefix packet", lossy=True))
                    result.warnings.append("missing trailing packet")

        return result


if __name__ == "__main__":
    run_standalone(WpdDecoder)
