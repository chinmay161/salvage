"""LABLOG: Laboratory analytical-instrument data logger format decoder.

Layout:
  Header (32 bytes fixed):
    offset 0x00: 4 bytes magic b"LLOG"
    offset 0x04: u8 major version (1)
    offset 0x05: u8 number of channels
    offset 0x06: u16le sample interval in centiseconds (10 ms units)
    offset 0x08: 16 bytes ASCII instrument name (null-padded)
    offset 0x18: u32le start timestamp (seconds since 1990-01-01 00:00:00 UTC)
    offset 0x1C: u16le declared block count
    offset 0x1E: u16le header CRC-16-CCITT over bytes 0x00..0x1D

  Blocks (contiguous starting at offset 0x20):
    +0x00: u8 sync marker 0xB1
    +0x01: u8 block type:
           0x03 = Channel Configuration
           0x01 = Data Records
           0x02 = Event Annotations
    +0x02: u16le payload length L
    +0x04: L bytes block payload
    +0x04 + L: u16le CRC-16-CCITT over type, length, and payload (bytes 1..4+L)

  Channel Configuration (Type 0x03, num_channels * 12 bytes):
    For each channel:
      +0x00: 4 bytes ASCII unit string (null-padded)
      +0x04: float32le scale factor
      +0x08: float32le offset value

  Data Records (Type 0x01, 3 + count * num_channels * 2 bytes):
    +0x00: u16le start sample index
    +0x02: u8 sample count
    Then for each sample:
      num_channels * int16le raw values.
      Raw value -32768 (0x8000) indicates dropout (null).
      Calibrated value: round(raw * scale + offset, 4).
      time_ms: sample_index * sample_interval_ms.

  Events (Type 0x02, 4 + msg_len bytes):
    +0x00: u16le sample index
    +0x02: u8 severity level
    +0x03: u8 message length
    +0x04: ASCII message string
"""

from __future__ import annotations

import datetime
import struct

from salvage.core.model import (Damage, DamageKind, DecodeResult, Field, Record,
                                Status)
from salvage.core.plugin import Decoder
from salvage.core.reader import SafeReader
from salvage.core.resync import ByteView, resync, resync_damage
from salvage.core.standalone import run_standalone

MAGIC = b"LLOG"
BLOCK_MARKER = 0xB1
HEADER_SIZE = 32
SUPPORTED_VERSION = 1
EPOCH_1990 = datetime.datetime(1990, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
DROPOUT_SENTINEL = -32768


def crc16_ccitt(data: bytes | bytearray) -> int:
    """CRC-16-CCITT: polynomial 0x1021, initial value 0xFFFF, no final XOR."""
    crc = 0xFFFF
    for b in data:
        crc ^= (b << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def _format_epoch_1990(seconds: int) -> str:
    """Format seconds since 1990-01-01 00:00:00 UTC as ISO 8601 UTC string."""
    dt = EPOCH_1990 + datetime.timedelta(seconds=seconds)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _looks_like_block(view: ByteView, offset: int) -> bool:
    """Resync predicate: marker 0xB1, valid type, in-bounds length, matching CRC."""
    try:
        if view.u8(offset) != BLOCK_MARKER:
            return False
        b_type = view.u8(offset + 1)
        if b_type not in (1, 2, 3):
            return False
        b_len = view.u16le(offset + 2)
        if b_len is None or offset + 4 + b_len + 2 > view.size:
            return False
        block_span = view.bytes(offset + 1, 3 + b_len)
        if len(block_span) != 3 + b_len:
            return False
        stored_crc = view.u16le(offset + 4 + b_len)
        return stored_crc is not None and crc16_ccitt(block_span) == stored_crc
    except Exception:
        return False


class LablogDecoder(Decoder):
    """Decoder for LABLOG analytical instrument data files."""

    name = "LABLOG"
    extensions = (".dat", ".log")

    def probe(self, data: bytes) -> float:
        """Probe for LABLOG format."""
        try:
            if len(data) < HEADER_SIZE:
                return 0.0
            if bytes(data[:4]) != MAGIC:
                return 0.0
            version = data[4]
            num_channels = data[5]
            if version != SUPPORTED_VERSION or num_channels == 0:
                return 0.2
            stored_crc, = struct.unpack_from("<H", data, 30)
            if crc16_ccitt(data[:30]) == stored_crc:
                return 1.0
            return 0.8
        except Exception:
            return 0.0

    def decode(self, reader: SafeReader) -> DecodeResult:
        """Decode a LABLOG file using reader."""
        if reader.peek(4) != MAGIC:
            return DecodeResult(format=self.name, confidence=0.0)

        result = DecodeResult(format=self.name, confidence=0.8)

        # -- Header (32 bytes) ------------------------------------------------
        if reader.size < HEADER_SIZE:
            reader.bytes(reader.size, "header.truncated")
            result.damage.append(Damage(0, reader.size, DamageKind.TRUNCATED,
                                        "header cut short"))
            result.warnings.append("header truncated")
            return result

        reader.bytes(4, "header.magic")
        version = reader.u8("header.version")
        num_channels = reader.u8("header.num_channels")
        sample_interval_csec = reader.u16le("header.sample_interval")
        instrument_bytes = reader.bytes(16, "header.instrument")
        start_time_sec = reader.u32le("header.start_time")
        declared_blocks = reader.u16le("header.declared_block_count")
        header_crc = reader.u16le("header.crc")

        if (version is None or num_channels is None or sample_interval_csec is None
                or instrument_bytes is None or start_time_sec is None
                or declared_blocks is None or header_crc is None):
            result.damage.append(Damage(0, reader.size, DamageKind.TRUNCATED,
                                        "header cut short during field reads"))
            result.warnings.append("header truncated")
            return result

        # Validate Header CRC
        computed_header_crc = crc16_ccitt(reader._data[:30])
        header_crc_ok = (header_crc == computed_header_crc)
        if header_crc_ok:
            result.confidence = 1.0
        else:
            result.damage.append(Damage(
                30, 32, DamageKind.CHECKSUM,
                f"header CRC mismatch: stored 0x{header_crc:04x}, computed 0x{computed_header_crc:04x}"
            ))
            result.warnings.append("header CRC mismatch")
            result.confidence = 0.6

        sample_interval_ms = sample_interval_csec * 10
        instrument = instrument_bytes.rstrip(b"\x00").decode("ascii", errors="replace")
        start_time_utc = _format_epoch_1990(start_time_sec)

        result.meta["version"] = version
        result.meta["instrument"] = instrument
        result.meta["sample_interval_ms"] = sample_interval_ms
        result.meta["channels"] = []
        result.meta["start_time_utc"] = start_time_utc
        result.meta["declared_block_count"] = declared_blocks
        result.meta["events"] = []

        if version != SUPPORTED_VERSION:
            result.damage.append(Damage(
                0, reader.size, DamageKind.OTHER,
                f"unsupported format version {version} (expected {SUPPORTED_VERSION})"
            ))
            result.warnings.append(f"unsupported version {version}")
            return result

        if num_channels == 0:
            result.damage.append(Damage(
                5, 6, DamageKind.BOUNDS,
                "invalid channel count: 0"
            ))
            result.warnings.append("zero channels declared")
            return result

        # -- Blocks Loop (from offset 0x20) -----------------------------------
        channels: list[dict] = []
        channels_verified = False
        blocks_parsed = 0

        while reader.tell() < reader.size:
            block_start = reader.tell()
            remaining = reader.remaining()

            if remaining < 4:
                reader.bytes(remaining, f"block[{blocks_parsed}].truncated_header")
                result.damage.append(Damage(
                    block_start, reader.size, DamageKind.TRUNCATED,
                    "truncated block header"
                ))
                break

            marker = reader.u8(f"block[{blocks_parsed}].marker")
            if marker != BLOCK_MARKER:
                # Lost sync -> attempt resynchronization
                hit = resync(reader, _looks_like_block, start=block_start)
                dmg = resync_damage(hit, f"invalid block marker 0x{marker:02x}; searching for next valid block")
                if dmg is not None:
                    result.damage.append(dmg)
                if hit.offset is None:
                    break
                continue

            block_type = reader.u8(f"block[{blocks_parsed}].type")
            payload_len = reader.u16le(f"block[{blocks_parsed}].length")

            if block_type is None or payload_len is None:
                result.damage.append(Damage(
                    block_start, reader.size, DamageKind.TRUNCATED,
                    "block cut short reading type or length"
                ))
                break

            if payload_len + 2 > reader.remaining():
                reader.bytes(reader.remaining(), f"block[{blocks_parsed}].truncated_payload")
                result.damage.append(Damage(
                    block_start, reader.size, DamageKind.TRUNCATED,
                    f"block {blocks_parsed} truncated: declared {payload_len} bytes payload + 2 CRC, "
                    f"only {reader.remaining()} remaining"
                ))
                break

            payload_off = reader.tell()
            payload = reader.bytes(payload_len, f"block[{blocks_parsed}].payload")
            stored_crc = reader.u16le(f"block[{blocks_parsed}].crc")
            block_end = reader.tell()

            # CRC check over type (1B) + length (2B) + payload (payload_len bytes)
            block_span = reader._data[block_start + 1 : block_start + 4 + payload_len]
            computed_crc = crc16_ccitt(block_span)
            crc_ok = (stored_crc == computed_crc)

            if not crc_ok:
                result.damage.append(Damage(
                    block_start, block_end, DamageKind.CHECKSUM,
                    f"block {blocks_parsed} CRC mismatch: stored 0x{stored_crc:04x}, computed 0x{computed_crc:04x}"
                ))
                result.warnings.append(f"block {blocks_parsed} CRC mismatch")
                if result.confidence > 0.8:
                    result.confidence = 0.8

            is_verified = crc_ok and channels_verified and header_crc_ok
            field_status = Status.VERIFIED if is_verified else Status.UNVERIFIED
            if is_verified:
                evidence = "CRC-16 matched"
            elif not crc_ok:
                evidence = f"CRC-16 mismatch: stored 0x{stored_crc:04x}, computed 0x{computed_crc:04x}"
            elif not channels_verified:
                evidence = "channel configuration unverified"
            else:
                evidence = "header CRC unverified"

            # -- Interpret block payload by type ------------------------------
            if block_type == 3:  # Channel Configuration
                expected_ch_len = num_channels * 12
                if payload_len != expected_ch_len:
                    result.damage.append(Damage(
                        payload_off, payload_off + payload_len, DamageKind.BOUNDS,
                        f"channel configuration block length {payload_len} != expected {expected_ch_len}"
                    ))
                    result.warnings.append("invalid channel config length")
                    channels_verified = False
                else:
                    channels.clear()
                    result.meta["channels"].clear()
                    for ch_idx in range(num_channels):
                        ch_slice = payload[ch_idx * 12 : (ch_idx + 1) * 12]
                        unit = ch_slice[:4].rstrip(b"\x00").decode("ascii", errors="replace")
                        scale, offset_val = struct.unpack("<ff", ch_slice[4:12])
                        channels.append({
                            "index": ch_idx,
                            "unit": unit,
                            "scale": scale,
                            "offset": offset_val,
                        })
                        result.meta["channels"].append({
                            "index": ch_idx,
                            "unit": unit,
                        })
                    channels_verified = crc_ok

            elif block_type == 1:  # Data Records
                if not channels:
                    result.damage.append(Damage(
                        payload_off, payload_off + payload_len, DamageKind.OTHER,
                        "data block encountered before channel configuration"
                    ))
                    result.warnings.append("data block before channel configuration")
                elif payload_len < 3:
                    result.damage.append(Damage(
                        payload_off, payload_off + payload_len, DamageKind.BOUNDS,
                        "data block payload shorter than header"
                    ))
                else:
                    start_sample, count = struct.unpack_from("<HB", payload, 0)
                    expected_len = 3 + count * num_channels * 2
                    if payload_len != expected_len:
                        result.damage.append(Damage(
                            payload_off, payload_off + payload_len, DamageKind.BOUNDS,
                            f"data block length {payload_len} does not match expected {expected_len}"
                        ))
                    else:
                        sample_bytes = payload[3:]
                        bytes_per_sample = num_channels * 2
                        for s in range(count):
                            curr_sample = start_sample + s
                            curr_time_ms = curr_sample * sample_interval_ms
                            raw_slice = sample_bytes[s * bytes_per_sample : (s + 1) * bytes_per_sample]
                            raw_vals = struct.unpack(f"<{num_channels}h", raw_slice)
                            cal_vals: list[float | None] = []
                            for ch_i, raw in enumerate(raw_vals):
                                if raw == DROPOUT_SENTINEL:
                                    cal_vals.append(None)
                                else:
                                    cal_val = round(raw * channels[ch_i]["scale"] + channels[ch_i]["offset"], 4)
                                    cal_vals.append(cal_val)

                            sample_off = payload_off + 3 + s * bytes_per_sample
                            rec = Record(offset=sample_off, status=field_status, kind="sample")
                            rec.fields = [
                                Field("sample", curr_sample, sample_off, bytes_per_sample, field_status, evidence),
                                Field("time_ms", curr_time_ms, sample_off, bytes_per_sample, field_status, evidence),
                                Field("values", cal_vals, sample_off, bytes_per_sample, field_status, evidence),
                            ]
                            result.records.append(rec)

            elif block_type == 2:  # Event Annotations
                if payload_len < 4:
                    result.damage.append(Damage(
                        payload_off, payload_off + payload_len, DamageKind.BOUNDS,
                        "event block payload shorter than header"
                    ))
                else:
                    ev_sample, ev_sev, ev_msg_len = struct.unpack_from("<HBB", payload, 0)
                    if payload_len != 4 + ev_msg_len:
                        result.damage.append(Damage(
                            payload_off, payload_off + payload_len, DamageKind.BOUNDS,
                            f"event block length {payload_len} != expected {4 + ev_msg_len}"
                        ))
                    else:
                        msg = payload[4 : 4 + ev_msg_len].decode("ascii", errors="replace")
                        result.meta["events"].append({
                            "sample": ev_sample,
                            "severity": ev_sev,
                            "message": msg,
                        })

            else:  # Unknown block type
                result.damage.append(Damage(
                    block_start, block_end, DamageKind.UNPARSED,
                    f"unknown block type 0x{block_type:02x}"
                ))
                result.warnings.append(f"unknown block type 0x{block_type:02x}")

            blocks_parsed += 1

        # -- Post-decode checks -----------------------------------------------
        if blocks_parsed < declared_blocks:
            if not any(d.kind == DamageKind.TRUNCATED for d in result.damage):
                result.damage.append(Damage(
                    reader.tell(), reader.size, DamageKind.TRUNCATED,
                    f"expected {declared_blocks} blocks, found {blocks_parsed}"
                ))
            result.warnings.append(
                f"declared {declared_blocks} blocks, but only {blocks_parsed} recovered"
            )

        return result


if __name__ == "__main__":
    run_standalone(LablogDecoder)
