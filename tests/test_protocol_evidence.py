"""Check dependency wire fields against the original client's REA observations.

These checks corroborate two message layouts; they do not claim full protocol
equivalence or successful live transfers. Outer length framing is supplied by
aioslsk; the observed function bodies establish message IDs and payload order.
"""
import struct

from aioslsk.protocol.messages import FileSearch, PeerTransferQueue


def test_global_search_fields_match_rea_observation():
    # analysis/rea/server-file-search.json: ev_3232047f3ab86bcb...
    frame = FileSearch.Request(ticket=0x12345678, query="test song").serialize()
    payload = frame[4:]
    assert struct.unpack_from("<II", payload) == (26, 0x12345678)
    assert struct.unpack_from("<I", payload, 8)[0] == len(b"test song")
    assert payload[12:] == b"test song"


def test_download_queue_fields_match_rea_observation():
    # analysis/rea/peer-queue-download.json: ev_1d3029902e1c546b...
    name = r"Music\test.flac"
    payload = PeerTransferQueue.Request(filename=name).serialize()[4:]
    assert struct.unpack_from("<II", payload) == (43, len(name.encode()))
    assert payload[8:] == name.encode()
