# Phase 0 report: bootstrap and shared contract

## 1. File tree created

```
.gitignore
CLAUDE.md
Makefile
docs/log/.gitkeep
docs/phase-reports/phase-0.md
docs/schema-notes.md
docs/spec/.gitkeep
salvage/__init__.py
salvage/cli.py
salvage/core/__init__.py
salvage/core/checksums.py
salvage/core/model.py
salvage/core/plugin.py
salvage/core/reader.py
salvage/core/standalone.py
salvage/formats/__init__.py
salvage/formats/stub.py
samples/            (created empty; did not exist)
schema/             (created empty; did not exist)
tests/__init__.py
tests/core/__init__.py
tests/core/test_checksums.py
tests/core/test_model.py
tests/core/test_plugin.py
tests/core/test_reader.py
tests/core/test_stub.py
tests/fixtures/__init__.py
tests/fixtures/fake_formats/__init__.py
tests/fixtures/fake_formats/_private.py
tests/fixtures/fake_formats/broken.py
tests/fixtures/fake_formats/dup.py
tests/fixtures/fake_formats/good.py
tools/api_dump.py
vendor/.gitkeep
```

`git init` was run; nothing is committed.

## 2. `make api` output

Run as `python tools/api_dump.py` (see Deviations: no `make` on this machine). Exit code 0.

```
== salvage.core.checksums
class ChecksumMatch(NamedTuple): name: str, start: int, end: int
def adler32(data: 'bytes') -> 'int'
def crc(data: 'bytes', *, width: 'int', poly: 'int', init: 'int', refin: 'bool', refout: 'bool', xorout: 'int') -> 'int'
def crc_preset(name: 'str', data: 'bytes') -> 'int'
def find_checksum(data: 'bytes', target: 'int', *, ranges: 'Iterable[tuple[int, int]] | None' = None, algorithms: 'Iterable[str] | None' = None, max_ranges: 'int' = 200000) -> 'list[ChecksumMatch]'
def fletcher16(data: 'bytes') -> 'int'
def sum16(data: 'bytes') -> 'int'
def sum16_words_be(data: 'bytes') -> 'int'
def sum16_words_le(data: 'bytes') -> 'int'
def sum32(data: 'bytes') -> 'int'
def sum8(data: 'bytes') -> 'int'
def sum8_neg(data: 'bytes') -> 'int'
def xor8(data: 'bytes') -> 'int'

== salvage.core.model
class Damage(start: 'int', end: 'int', kind: 'DamageKind', reason: 'str') -> None
class DamageKind(str, Enum)
    TRUNCATED = 'truncated'
    CHECKSUM = 'checksum'
    BOUNDS = 'bounds'
    UNPARSED = 'unparsed'
    OTHER = 'other'
class DecodeResult(format: 'str', confidence: 'float', records: 'list[Record]' = <factory>, members: "list['DecodeResult']" = <factory>, damage: 'list[Damage]' = <factory>, meta: 'dict[str, JSONValue]' = <factory>, warnings: 'list[str]' = <factory>, name: 'str | None' = None) -> None
    name = None
    def to_dict(self) -> 'dict[str, JSONValue]'
    def validate(self, file_size: 'int') -> 'list[str]'
class Field(name: 'str', value: 'JSONValue', offset: 'int', length: 'int', status: 'Status', evidence: 'str' = '') -> None
    evidence = ''
class Record(offset: 'int', status: 'Status', kind: 'str' = 'record', fields: 'list[Field]' = <factory>) -> None
    kind = 'record'
class Status(str, Enum)
    VERIFIED = 'verified'
    CONSISTENT = 'consistent'
    UNVERIFIED = 'unverified'
    LOST = 'lost'
    @property rank
    @staticmethod worst(statuses: 'Iterable[Any]') -> "'Status'"
def json_safe(value: 'Any') -> 'JSONValue'

== salvage.core.plugin
class Decoder()
    @classmethod can_encode(cls) -> 'bool'
    def decode(self, reader: "'SafeReader'") -> 'DecodeResult'
    def encode(self, result: 'DecodeResult') -> 'bytes'
    extensions = ()
    name = ''
    def probe(self, data: 'bytes') -> 'float'
class DiscoveryResult(decoders: 'list[Decoder]' = <factory>, errors: 'list[str]' = <factory>) -> None
def discover_decoders(package: 'str' = 'salvage.formats') -> 'DiscoveryResult'
def safe_probe(decoder: 'Decoder', data: 'bytes') -> 'tuple[float, str | None]'

== salvage.core.reader
class ReaderEvent(NamedTuple): kind: str, offset: int, wanted: int | None, available: int | None, label: str | None
class SafeReader(data: 'bytes') -> 'None'
    def at(self, offset: 'int') -> 'Iterator[bool]'
    def bytes(self, n: 'int', label: 'str | None' = None) -> 'bytes'
    def claimed(self) -> 'list[tuple[int, int, str]]'
    def covered_bytes(self) -> 'int'
    def cstring(self, max_len: 'int' = 4096, label: 'str | None' = None) -> 'bytes | None'
    @property events
    def f32le(self, label: 'str | None' = None) -> 'float | None'
    def f64le(self, label: 'str | None' = None) -> 'float | None'
    def i16be(self, label: 'str | None' = None) -> 'int | None'
    def i16le(self, label: 'str | None' = None) -> 'int | None'
    def i32be(self, label: 'str | None' = None) -> 'int | None'
    def i32le(self, label: 'str | None' = None) -> 'int | None'
    def i8(self, label: 'str | None' = None) -> 'int | None'
    def peek(self, n: 'int') -> 'bytes'
    def remaining(self) -> 'int'
    def seek(self, pos: 'int') -> 'bool'
    @property size
    def skip(self, n: 'int') -> 'bool'
    def tell(self) -> 'int'
    def u16be(self, label: 'str | None' = None) -> 'int | None'
    def u16le(self, label: 'str | None' = None) -> 'int | None'
    def u32be(self, label: 'str | None' = None) -> 'int | None'
    def u32le(self, label: 'str | None' = None) -> 'int | None'
    def u64le(self, label: 'str | None' = None) -> 'int | None'
    def u8(self, label: 'str | None' = None) -> 'int | None'
    def unpack(self, fmt: 'str', label: 'str | None' = None) -> 'tuple | None'

== salvage.core.standalone
def run_standalone(decoder_cls: 'type[Decoder]') -> 'int'

== salvage.formats.stub
class StubDecoder(Decoder)()
    @classmethod can_encode(cls) -> 'bool'
    def decode(self, reader: 'SafeReader') -> 'DecodeResult'
    def encode(self, result: 'DecodeResult') -> 'bytes'
    extensions = ('.stub',)
    name = 'STUB'
    def probe(self, data: 'bytes') -> 'float'
```

## 3. `make test` output (last 30 lines)

Run as `python -m unittest discover -s tests -t . -v`. Exit code 0.

```
test_at_restores_on_exception (tests.core.test_reader.SeekTests.test_at_restores_on_exception) ... ok
test_at_restores_position (tests.core.test_reader.SeekTests.test_at_restores_position) ... ok
test_seek_bounds (tests.core.test_reader.SeekTests.test_seek_bounds) ... ok
test_skip_bounds (tests.core.test_reader.SeekTests.test_skip_bounds) ... ok
test_bytes_exact (tests.core.test_reader.TruncationTests.test_bytes_exact) ... ok
test_bytes_negative_length (tests.core.test_reader.TruncationTests.test_bytes_negative_length) ... ok
test_bytes_short_tail (tests.core.test_reader.TruncationTests.test_bytes_short_tail) ... ok
test_every_numeric_read_truncates_cleanly (tests.core.test_reader.TruncationTests.test_every_numeric_read_truncates_cleanly) ... ok
test_truncated_read_returns_none_and_keeps_position (tests.core.test_reader.TruncationTests.test_truncated_read_returns_none_and_keeps_position) ... ok
test_cstring_empty (tests.core.test_reader.UnpackAndCStringTests.test_cstring_empty) ... ok
test_cstring_nul_beyond_max_len (tests.core.test_reader.UnpackAndCStringTests.test_cstring_nul_beyond_max_len) ... ok
test_cstring_with_nul (tests.core.test_reader.UnpackAndCStringTests.test_cstring_with_nul) ... ok
test_cstring_without_nul (tests.core.test_reader.UnpackAndCStringTests.test_cstring_without_nul) ... ok
test_unpack (tests.core.test_reader.UnpackAndCStringTests.test_unpack) ... ok
test_unpack_requires_endianness (tests.core.test_reader.UnpackAndCStringTests.test_unpack_requires_endianness) ... ok
test_unpack_truncated (tests.core.test_reader.UnpackAndCStringTests.test_unpack_truncated) ... ok
test_deterministic_json (tests.core.test_stub.StubTests.test_deterministic_json) ... ok
test_probe (tests.core.test_stub.StubTests.test_probe) ... ok
test_round_trip (tests.core.test_stub.StubTests.test_round_trip) ... ok
test_standalone_cli (tests.core.test_stub.StubTests.test_standalone_cli) ... ok
test_statuses (tests.core.test_stub.StubTests.test_statuses) ... ok
test_trailing_bytes_reported (tests.core.test_stub.StubTests.test_trailing_bytes_reported) ... ok
test_truncated (tests.core.test_stub.StubTests.test_truncated) ... ok
test_truncated_inside_count (tests.core.test_stub.StubTests.test_truncated_inside_count) ... ok
test_wrong_magic (tests.core.test_stub.StubTests.test_wrong_magic) ... ok

----------------------------------------------------------------------
Ran 84 tests in 0.580s

OK
```

## 4. Deviations

1. **`make` could not be run.** This Windows machine has no `make`, and
   `python3` is only the Microsoft Store alias (`python` is 3.12.2). I ran
   the Makefile's two recipes directly with `python`. On a machine with
   make, use `make test PY=python` here, or plain `make test` where
   `python3` exists. The Makefile is as specified.
2. **The duplicate-decoder test keeps dup.py, not good.py.** The spec says
   "keep the first (by module name)", and `dup` sorts before `good`. So the
   kept `GOOD` decoder is `DupDecoder` from dup.py, and good.py's class is
   the one reported as a duplicate. The error message names both modules
   (`...good: duplicate decoder name 'GOOD' in GoodDecoder; keeping the one
   from ...dup`). The test still checks exactly one `GOOD`, one error for
   broken, one duplicate error, and that `_private` is never imported. It
   also asserts which module won. I kept the rule as written and changed
   the test, not the other way round.
3. **STUB has a header record.** The spec says "one Record per value". The
   magic and count fields also need a home, so `records[0]` is a `header`
   record (offset 0) holding them, and value records (`kind="value"`)
   follow. The header's status is the worst of its fields' statuses.
4. **STUB reports trailing bytes.** If all values decode and bytes are left
   over, STUB adds `Damage(UNPARSED)` over them plus a warning. The spec
   doesn't mention trailing bytes; reporting them is the honest choice.
   A truncated count field gives `Damage(TRUNCATED)` from offset 13 to EOF.
5. **`cstring(max_len)`:** the NUL must be within the next `max_len` bytes,
   so the longest string returned is `max_len - 1` bytes.
6. **Additions beyond the spec (all backward-compatible):**
   - `Status.rank` property.
   - `checksums.crc_preset(name, data)` helper.
   - `ReaderEvent` kinds `bad_data` (constructor got non-bytes) and
     `bad_length` (also for an invalid `cstring` max_len).
   - `DecodeResult.validate` also flags non-list collections and a
     non-`DamageKind` damage kind.
7. **Robustness choices:**
   - `Status.worst` counts values that aren't valid statuses as `LOST`.
   - `json_safe` returns `"<unserializable list|dict|tuple>"` for cyclic
     containers or nesting deeper than 100 levels. Without this it could
     hit a recursion error, or return a ~1000-deep list that `json.dumps`
     can't handle.
   - Non-str dict keys are converted with `json_safe` and then turned into
     a string.
   - `safe_probe` also catches `SystemExit`.
   - `run_standalone` returns 0 and doesn't call `sys.exit`.
   - Bad inputs to `peek` (negative or non-int `n`) return `b""` and record
     no event.
8. **Extra file:** `docs/schema-notes.md`. Section 10 requires it, but it
   isn't in the section 2 layout list.

## 5. Schema BLOCKERS

- **schema/ is empty** (it didn't exist and was created empty), so the
  draft version, required fields and mapping are all unknown. The mapping
  assumptions are in `docs/schema-notes.md`. Phase 1's emitter needs the
  real schema.

## 6. Not done

- Nothing in scope was left out.
- `make test` / `make api` weren't run through `make` itself (Deviation 1).
- As instructed, there is no CLI logic, emitter, Docker setup or schema
  validation.
