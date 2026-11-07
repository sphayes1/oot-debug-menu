"""Decode selected game assets with the dump's own compression dictionaries."""
import oead
import zstandard as zstd
from nup import Nup, MAX_MEMBER



class Assets:
    def __init__(self, nup):
        self.nup = nup
        packed = nup.read('romfs/Pack/ZsDic.pack.zs')
        archive = oead.Sarc(zstd.ZstdDecompressor().decompress(packed, max_output_size=MAX_MEMBER))
        self.dictionaries = {}
        for f in archive.get_files():
            d = zstd.ZstdCompressionDict(bytes(f.data))
            self.dictionaries[d.dict_id()] = d

    def decode(self, data):
        if data[:4] != b'\x28\xb5\x2f\xfd':
            return data
        params = zstd.get_frame_parameters(data)
        dictionary = self.dictionaries[params.dict_id] if params.dict_id else None
        return zstd.ZstdDecompressor(dict_data=dictionary).decompress(data, max_output_size=MAX_MEMBER)
