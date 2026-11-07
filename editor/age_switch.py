"""Bookmark the standing position and reload that same area as the other age."""
from datetime import datetime
from locations import LocationStore
from teleport import TeleportTransport


class AgeSwitch:
    def __init__(self, binding, store=None):
        self.transport = TeleportTransport(binding)
        self.store = store if store is not None else LocationStore()
        self.last_bookmark = None

    def switch(self, age):
        if age not in ('Child', 'Adult'):
            raise ValueError('Choose Child or Adult')
        self.transport.validate(age_reload=True)
        origin = self.transport.fields.capture()
        if origin['age'] == age:
            raise ValueError('Link is already that age')
        revision = self.transport.binding.schema['source_sha256']
        label = ('Before '+age+': '+origin['banc']+' '+datetime.now().strftime('%H:%M:%S'))[:80]
        # Persist the original era/pose before any native request. A failed save
        # must prevent the switch; a failed warp must retain the recovery bookmark.
        self.last_bookmark = self.store.save(label, origin, revision)
        pose = dict(origin, age=age, entry='')
        # The explicit age action opts into the area's opposite player age.
        # The native manual override prevents the area forcing its usual age.
        result = self.transport.warp(pose, revision, target_age=age, allow_any_era=True)
        return dict(result, origin_bookmark=self.last_bookmark)
