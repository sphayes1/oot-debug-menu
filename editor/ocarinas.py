"""Narrow equipment-string planner from the captured normal Saria handoff.

The handoff writes Item_Ocarina_Fairy, not Pouch_Ocarina_Fairy. No story,
tutorial or unidentified item flags are changed here. Live grant validation is
recorded separately from the read-only planner and its fake-memory tests.
"""
import struct

ACTORS = ('Item_Ocarina_Fairy', 'Item_Ocarina_Time')
FIELD_HASH = 'b72cd3fc'


def write_plan(binding, counts, current):
    if not set(counts).intersection(ACTORS):
        return []
    desired = dict(current['counts'], **counts)
    target = next((actor for actor in reversed(ACTORS) if desired.get(actor, 0)>0), '')
    assignments = binding.assignments
    if assignments is None:
        raise ValueError('Connect the ocarina equipment field before editing it')
    assignments.validate()
    field = assignments.schema['fields']['EquipOcarina']
    if field['hash'] != FIELD_HASH or field['type'] != 'String64':
        raise ValueError('Ocarina equipment schema changed')
    state = assignments._string(field)
    if state['actor'] not in ('', *ACTORS, 'Pouch_Ocarina_Fairy', 'Pouch_Ocarina_Time'):
        raise ValueError('Unknown equipped ocarina; reconnect before editing')
    address, data = assignments._object(field)
    payload = target.encode('ascii').ljust(64,b'\0')
    plan = []
    for wrapper, offset in ((104,116),(184,196)):
        if struct.unpack_from('<Q',data,wrapper)[0] != address+offset or struct.unpack_from('<I',data,wrapper+8)[0] != 64:
            raise ValueError('Ocarina string wrapper changed')
        old = data[offset:offset+64]
        if b'\0' not in old:
            raise ValueError('Unterminated ocarina equipment string')
        if old == payload:
            continue
        first = struct.unpack_from('<I',old)[0]
        # Readers see Empty while tails change; publish the complete actor last.
        if first:
            plan.append(dict(address=address+offset,expected=first,value=0,field='Ocarina clear prefix'))
        for i in range(4,64,4):
            before = struct.unpack_from('<I',old,i)[0]
            after = struct.unpack_from('<I',payload,i)[0]
            if before != after:
                plan.append(dict(address=address+offset+i,expected=before,value=after,field='Ocarina string tail'))
        new_first = struct.unpack_from('<I',payload)[0]
        if new_first:
            plan.append(dict(address=address+offset,expected=0,value=new_first,field='Ocarina publish '+(target or 'None')))
    return plan
