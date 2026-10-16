"""VAULT archive format decoder."""

from __future__ import annotations

import struct
from typing import Any

from salvagekit.core.limits import MAX_DECOMPRESSED
from salvagekit.core.model import (
    Damage,
    DamageKind,
    DecodeResult,
    Field,
    Record,
    Status,
)
from salvagekit.core.plugin import Decoder
from salvagekit.core.reader import SafeReader
from salvagekit.core.standalone import run_standalone

MAGIC = b"VLT1"
HEADER_SIZE = 16
INDEX_ENTRY_SIZE = 16
CHUNK_MARKER = b"BL"


class VaultDecoder(Decoder):
    """Decoder for the VAULT container archive format."""

    name = "VAULT"
    extensions = (".dat",)

    def probe(self, data: bytes) -> float:
        """Score how likely ``data`` is a VAULT archive (0.0 to 1.0). Never raises."""
        try:
            if not isinstance(data, (bytes, bytearray, memoryview)) or len(data) < 4:
                return 0.0
            if bytes(data[:4]) != MAGIC:
                return 0.0
            if len(data) >= HEADER_SIZE:
                entry_count, xor_key, flags, index_offset, str_table_offset = struct.unpack_from(
                    "<HBBII", data, 4
                )
                if (
                    entry_count > 0
                    and HEADER_SIZE <= str_table_offset <= index_offset
                    and index_offset + entry_count * INDEX_ENTRY_SIZE == len(data)
                ):
                    return 1.0
            return 0.6
        except Exception:
            return 0.0

    def decode(self, reader: SafeReader) -> DecodeResult:
        """Decode a VAULT archive. Reads only via ``reader``. Never raises."""
        try:
            return self._decode_safe(reader)
        except Exception as exc:  # pragma: no cover - defensive safety net
            res = DecodeResult(format=self.name, confidence=0.0)
            res.damage.append(
                Damage(0, reader.size, DamageKind.BAD_LENGTH, f"internal decoding error: {exc}")
            )
            return res

    def _decode_safe(self, reader: SafeReader) -> DecodeResult:
        if reader.peek(4) != MAGIC:
            return DecodeResult(format=self.name, confidence=0.0)

        result = DecodeResult(format=self.name, confidence=0.6)
        file_size = reader.size

        # --- Header ---
        reader.bytes(4, "header.magic")
        entry_count = reader.u16le("header.entry_count")
        xor_key = reader.u8("header.xor_key")
        flags = reader.u8("header.flags")
        index_offset = reader.u32le("header.index_offset")
        string_table_offset = reader.u32le("header.string_table_offset")

        if (
            entry_count is None
            or xor_key is None
            or flags is None
            or index_offset is None
            or string_table_offset is None
        ):
            result.damage.append(
                Damage(0, file_size, DamageKind.TRUNCATED, "header cut short")
            )
            return result

        result.meta["entry_count"] = entry_count
        result.meta["xor_key"] = xor_key
        result.meta["flags"] = flags

        # Header boundary checks
        if index_offset > file_size or string_table_offset > file_size:
            result.damage.append(
                Damage(
                    8,
                    16,
                    DamageKind.OOB_POINTER,
                    f"table offsets out of bounds (index={index_offset}, string_table={string_table_offset}, size={file_size})",
                )
            )
            return result

        if string_table_offset < HEADER_SIZE or string_table_offset > index_offset:
            result.damage.append(
                Damage(
                    12,
                    16,
                    DamageKind.BAD_LENGTH,
                    f"invalid string table offset {string_table_offset} (header={HEADER_SIZE}, index={index_offset})",
                )
            )
            return result

        expected_index_bytes = entry_count * INDEX_ENTRY_SIZE
        if index_offset + expected_index_bytes > file_size:
            result.damage.append(
                Damage(
                    index_offset,
                    file_size,
                    DamageKind.TRUNCATED,
                    f"declared {entry_count} index entries ({expected_index_bytes} bytes), but file ends at {file_size}",
                )
            )
            return result

        # --- Index table ---
        if not reader.seek(index_offset):
            result.damage.append(
                Damage(
                    index_offset,
                    file_size,
                    DamageKind.OOB_POINTER,
                    f"cannot seek to index offset {index_offset}",
                )
            )
            return result

        entries: list[dict[str, Any]] = []
        for i in range(entry_count):
            entry_start = reader.tell()
            rec_id = reader.u16le(f"index[{i}].id")
            type_code = reader.u8(f"index[{i}].type")
            rec_flags = reader.u8(f"index[{i}].flags")
            name_offset = reader.u32le(f"index[{i}].name_offset")
            data_offset = reader.u32le(f"index[{i}].data_offset")
            stored_sz = reader.u16le(f"index[{i}].stored_sz")
            decoded_sz = reader.u16le(f"index[{i}].decoded_sz")

            if (
                rec_id is None
                or type_code is None
                or rec_flags is None
                or name_offset is None
                or data_offset is None
                or stored_sz is None
                or decoded_sz is None
            ):
                result.damage.append(
                    Damage(
                        entry_start,
                        file_size,
                        DamageKind.TRUNCATED,
                        f"index entry {i} cut short",
                    )
                )
                break

            entries.append(
                {
                    "idx": i,
                    "entry_start": entry_start,
                    "id": rec_id,
                    "type_code": type_code,
                    "rec_flags": rec_flags,
                    "name_offset": name_offset,
                    "data_offset": data_offset,
                    "stored_sz": stored_sz,
                    "decoded_sz": decoded_sz,
                }
            )

        # --- String table ---
        filenames: dict[int, str] = {}
        for entry in entries:
            i = entry["idx"]
            name_off = entry["name_offset"]
            str_abs_offset = string_table_offset + name_off
            if str_abs_offset >= index_offset or str_abs_offset < string_table_offset:
                result.damage.append(
                    Damage(
                        entry["entry_start"] + 4,
                        entry["entry_start"] + 8,
                        DamageKind.OOB_POINTER,
                        f"entry {i} name_offset {name_off} outside string table",
                    )
                )
                filenames[i] = f"record_{entry['id']}.bin"
                continue

            with reader.at(str_abs_offset) as ok:
                if not ok:
                    result.damage.append(
                        Damage(
                            str_abs_offset,
                            min(str_abs_offset + 1, file_size),
                            DamageKind.OOB_POINTER,
                            f"entry {i} name offset out of bounds",
                        )
                    )
                    filenames[i] = f"record_{entry['id']}.bin"
                    continue

                raw_len = reader.u8(f"string[{i}].len")
                if raw_len is None:
                    result.damage.append(
                        Damage(
                            str_abs_offset,
                            file_size,
                            DamageKind.TRUNCATED,
                            f"entry {i} string length cut short",
                        )
                    )
                    filenames[i] = f"record_{entry['id']}.bin"
                    continue

                name_len = (raw_len ^ xor_key) if (flags & 0x01) else raw_len
                if str_abs_offset + 1 + name_len > index_offset:
                    result.damage.append(
                        Damage(
                            str_abs_offset,
                            min(str_abs_offset + 1 + name_len, file_size),
                            DamageKind.BAD_LENGTH,
                            f"entry {i} string length {name_len} exceeds string table",
                        )
                    )
                    name_chars = reader.bytes(
                        max(0, index_offset - (str_abs_offset + 1)),
                        f"string[{i}].chars",
                    )
                else:
                    name_chars = reader.bytes(name_len, f"string[{i}].chars")

                # De-XOR characters
                dec_bytes = bytes(
                    b ^ ((xor_key + j) & 0xFF) for j, b in enumerate(name_chars)
                )
                try:
                    name = dec_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    name = dec_bytes.decode("latin-1", errors="replace")
                filenames[i] = name

        # --- Chunks framing validation ---
        for entry in entries:
            i = entry["idx"]
            data_off = entry["data_offset"]
            stored_sz = entry["stored_sz"]

            if stored_sz < 4:
                result.damage.append(
                    Damage(
                        entry["entry_start"] + 12,
                        entry["entry_start"] + 14,
                        DamageKind.BAD_LENGTH,
                        f"entry {i} stored_sz {stored_sz} is less than chunk header size (4)",
                    )
                )
                continue

            chunk_total_span = stored_sz + 4
            if data_off < HEADER_SIZE or data_off + chunk_total_span > file_size:
                result.damage.append(
                    Damage(
                        entry["entry_start"] + 8,
                        entry["entry_start"] + 12,
                        DamageKind.OOB_POINTER,
                        f"entry {i} chunk span [{data_off}, {data_off + chunk_total_span}) out of file bounds",
                    )
                )
                continue

            with reader.at(data_off) as ok:
                if not ok:
                    continue
                marker = reader.bytes(2, f"chunk[{i}].marker")
                chunk_id = reader.u16le(f"chunk[{i}].id")
                payload_len = stored_sz - 4
                reader.bytes(payload_len, f"chunk[{i}].payload")
                reader.u32le(f"chunk[{i}].crc")

                if marker != CHUNK_MARKER:
                    result.damage.append(
                        Damage(
                            data_off,
                            data_off + 2,
                            DamageKind.INVALID_VALUE,
                            f"entry {i} chunk marker mismatch: expected {CHUNK_MARKER!r}, got {marker!r}",
                        )
                    )
                if chunk_id != entry["id"]:
                    result.damage.append(
                        Damage(
                            data_off + 2,
                            data_off + 4,
                            DamageKind.INVALID_VALUE,
                            f"entry {i} chunk ID mismatch: expected {entry['id']}, got {chunk_id}",
                        )
                    )

        return result


if __name__ == "__main__":
    run_standalone(VaultDecoder)
