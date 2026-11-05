"""Custom Robo LZSS encoder; complementary to survey_rom.decode.

Wire format verified against the supplied ROM. No original bytes are modified.
"""
import struct
from collections import defaultdict, deque


def encode(raw: bytes) -> bytes:
    data = bytes(0xfee) + raw
    positions = defaultdict(deque)
    for i in range(0xfee):
        positions[data[i:i+3]].append(i)
    current = 0xfee
    stream = bytearray()
    while current < len(data):
        flagpos = len(stream)
        stream.append(0)
        for bit in range(8):
            if current == len(data):
                break
            key = data[current:current+3]
            candidates = positions[key]
            while candidates and candidates[0] < current - 4095:
                candidates.popleft()
            best_length, best_at = 0, 0
            limit = min(18, len(data)-current)
            for at in reversed(candidates):
                length = 3
                while length < limit and data[at+length] == data[current+length]:
                    length += 1
                if length > best_length:
                    best_length, best_at = length, at
                    if length == limit:
                        break
            if best_length >= 3 and limit >= 3:
                address = best_at & 4095
                stream.extend((address & 255, ((address >> 4) & 240) | (best_length - 3)))
                step = best_length
            else:
                stream[flagpos] |= 1 << bit
                stream.append(data[current])
                step = 1
            for at in range(current, current + step):
                positions[data[at:at+3]].append(at)
            current += step
    packed = len(stream) + 4
    total = (12 + len(stream) + 3) & ~3
    return struct.pack('>III', total, packed, len(raw)) + stream + bytes(total-12-len(stream))


if __name__ == '__main__':
    import json, time, hashlib
    from survey_rom import ROOT, decode
    started = time.monotonic()
    rows = json.loads((ROOT/'manifests/compressed-streams.json').read_text())
    fits, stored, encoded = 0, 0, 0
    for row in rows:
        raw = (ROOT/row['file']).read_bytes()
        result = encode(raw)
        assert decode(result, 0)[0] == raw, row['file']
        fits += len(result) <= row['stored_size']
        stored += row['stored_size']
        encoded += len(result)
    report = {'streams_tested': len(rows), 'decode_encode_decode_exact': True,
              'original_slots_fit': fits, 'original_bytes': stored, 'encoded_bytes': encoded,
              'seconds': round(time.monotonic()-started, 2)}
    (ROOT/'manifests/codec-roundtrip.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))
