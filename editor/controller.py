"""Controller hotkeys through the emulator's mapped-input lease, not XInput hooks."""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import queue
import secrets
import threading
import time
from camera import fly
from live import Client

ROOT = Path(__file__).resolve().parent
BUTTONS = ['A', 'B', 'X', 'Y', 'StickL', 'StickR', 'L', 'R', 'ZL', 'ZR', 'Plus', 'Minus', 'Left', 'Up', 'Right', 'Down']
ACTIONS = ['enter', 'exit', 'teleport', 'save', 'load']
LABELS = {'enter': 'Enter free camera', 'exit': 'Exit camera', 'teleport': 'Teleport and exit camera',
          'save': 'Quick save', 'load': 'Load latest save'}
FRIENDLY = {'L': 'LB / L', 'R': 'RB / R', 'ZL': 'LT / ZL', 'ZR': 'RT / ZR', 'Minus': '-', 'Plus': '+'}
DEFAULT = {'version': 1, 'enabled': True,
           'bindings': {'enter': ['L', 'Minus'], 'exit': ['B'], 'teleport': ['A'],
                        'save': ['L', 'R', 'ZL', 'ZR', 'Left'], 'load': ['L', 'R', 'ZL', 'ZR', 'Right']},
           'deadzone': .18, 'look_speed': 140., 'invert_y': False,
           'move_stick': 'left', 'look_stick': 'right', 'up': 'ZR', 'down': 'ZL'}


def mask(buttons):
    return sum(1 << BUTTONS.index(button) for button in buttons)


def chord(buttons):
    return ' + '.join(FRIENDLY.get(b, b) for b in buttons)


def next_event(result, seen):
    sequence = result['sequence']
    if sequence < seen:  # A renewed lease or Player1/Handheld switch resets native state.
        seen = sequence
    if sequence != seen and result['action'] in range(5):
        return sequence, ACTIONS[result['action']]
    return seen, None


def validate_config(config):
    if not isinstance(config, dict) or set(config) != set(DEFAULT) or config['version'] != 1:
        raise ValueError('Unsupported controller settings')
    if type(config['enabled']) is not bool or type(config['invert_y']) is not bool:
        raise ValueError('Invalid controller toggles')
    if not isinstance(config['bindings'], dict) or set(config['bindings']) != set(ACTIONS):
        raise ValueError('Five controller shortcuts are required')
    for buttons in config['bindings'].values():
        if not isinstance(buttons, list) or not 1 <= len(buttons) <= 8 or len(set(buttons)) != len(buttons) or any(b not in BUTTONS for b in buttons):
            raise ValueError('Choose one to eight different buttons per shortcut')
    for i, action in enumerate(ACTIONS):
        a = set(config['bindings'][action])
        for other in ACTIONS[i+1:]:
            b = set(config['bindings'][other])
            if a <= b or b <= a:
                raise ValueError(LABELS[action]+' and '+LABELS[other]+' overlap; choose separate combinations')
    for key, lo, hi in (('deadzone', .05, .5), ('look_speed', 20, 360)):
        if type(config[key]) not in (int, float) or not lo <= config[key] <= hi:
            raise ValueError('Invalid controller '+key)
    if config['move_stick'] not in ('left', 'right') or config['look_stick'] not in ('left', 'right') or config['move_stick'] == config['look_stick']:
        raise ValueError('Movement and look must use different sticks')
    if config['up'] not in BUTTONS or config['down'] not in BUTTONS or config['up'] == config['down']:
        raise ValueError('Choose different camera up/down buttons')
    for button in (config['up'], config['down']):
        if any(set(config['bindings'][a]) <= {button} for a in ('exit', 'teleport', 'save', 'load')):
            raise ValueError('Camera up/down overlaps an action')
    return json.loads(json.dumps(config))


def radial(x, y, deadzone):
    length = (x*x+y*y)**.5
    if length <= deadzone:
        return 0., 0.
    scale = min(1., (length-deadzone)/(1-deadzone))/length
    return x*scale, y*scale


def controller_flight(pose, sample, config, speed, dt):
    axes = [max(-1., min(1., float(v)/32767)) for v in sample['axes']]
    left, right = radial(*axes[:2], config['deadzone']), radial(*axes[2:], config['deadzone'])
    move, look = (left, right) if config['move_stick'] == 'left' else (right, left)
    buttons = int(sample['buttons'])
    vertical = int(bool(buttons & mask([config['up']])))-int(bool(buttons & mask([config['down']])))
    if not any((*move, *look, vertical)):
        return None
    # fly() uses radians/.004 per mouse delta; convert stick angular speed.
    import math
    angle = math.radians(config['look_speed'])*min(.08, dt)/.004
    return fly(pose, side=move[0], forward=move[1], vertical=vertical,
               distance=speed*min(.08, dt), dx=look[0]*angle,
               dy=look[1]*angle*(1 if config['invert_y'] else -1))


class Controller:
    def __init__(self):
        self.error = ''
        try:
            self.config = validate_config(json.loads((ROOT/'controller-hotkeys.json').read_text(encoding='utf-8')))
        except FileNotFoundError:
            self.config = validate_config(DEFAULT)
        except (ValueError, TypeError) as exc:
            self.config = validate_config(DEFAULT);self.config['enabled'] = False;self.error = str(exc)
        self.context_value = None
        self.sample = None
        self.status = 'Connect to gameplay'
        self.recording = False
        self.events = queue.Queue()
        self.completions = queue.Queue()
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name='oot-controller', daemon=True)
        self.thread.start()

    def context(self, session, armed, camera):
        self.context_value = (tuple(session), bool(armed), bool(camera)) if session else None

    def apply(self, config):
        config = validate_config(config)
        temporary = ROOT/'controller-hotkeys.json.tmp'
        temporary.write_text(json.dumps(config, indent=2)+'\n', encoding='utf-8')
        temporary.replace(ROOT/'controller-hotkeys.json')
        self.config = config
        self.error = ''

    def complete(self, sequence, camera, session=None):
        session = tuple(session) if session is not None else (self.context_value[0] if self.context_value else None)
        self.completions.put((sequence, bool(camera), session))

    def take_completion(self, session):
        while True:
            try:
                row = self.completions.get_nowait()
            except queue.Empty:
                return None
            if row[2] == session:
                return row

    def take(self):
        result = []
        while True:
            try:
                result.append(self.events.get_nowait())
            except queue.Empty:
                return result

    def close(self):
        self.stop_event.set();self.thread.join(timeout=2)

    def _run(self):
        client = Client()
        owner = secrets.token_hex(16)
        session = None
        seen = 0
        last_samples = None
        last_hid = 0.
        try:
            user = ctypes.WinDLL('user32', use_last_error=True)
            user.GetForegroundWindow.restype = wintypes.HWND
            user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
            def focused(pid):
                foreground = wintypes.DWORD()
                user.GetWindowThreadProcessId(user.GetForegroundWindow(), ctypes.byref(foreground))
                return foreground.value == pid
            while not self.stop_event.wait(1/60):
                context = self.context_value
                if not context or not self.config['enabled']:
                    if session:
                        try:client.call('controller_debug', dict(owner=owner, enabled=False, bindings=[mask(self.config['bindings'][a]) for a in ACTIONS]), timeout=1)
                        except Exception:pass
                    session = None;self.sample = None;self.status = 'Disabled / game disconnected'
                    continue
                current, idle, camera = context
                try:
                    receipt = json.loads((ROOT/'runtime/session.json').read_text(encoding='utf-8'))
                    if (receipt['pid'], receipt['started']) != current:
                        client.close();session = None;self.sample = None
                        self.status = 'Emulator session changed; reconnect'
                        continue
                except (OSError, ValueError, KeyError):
                    client.close();session = None;self.sample = None
                    continue
                if session != current:
                    try:
                        client.close();client.status()
                    except Exception as exc:
                        self.error = str(exc);self.sample = None;self.stop_event.wait(.5)
                        continue
                    session = current;owner = secrets.token_hex(16);seen = 0
                    last_samples = None;last_hid = 0.
                    while not self.completions.empty():
                        self.completions.get_nowait()
                config = self.config
                active = focused(current[0])
                params = dict(owner=owner, enabled=True, armed=idle and active,
                              bindings=[mask(config['bindings'][a]) for a in ACTIONS],
                              capture=camera, recording=self.recording)
                completion = self.take_completion(current)
                if completion:
                    params.update(complete=completion[0], capture=completion[1])
                try:
                    result = client.call('controller_debug', params, timeout=1)
                    if result.get('protocol') != 1:
                        raise ValueError('Controller bridge revision differs')
                    self.error = ''
                    self.status = 'Controller ready' if active else 'Controller shortcuts need game focus'
                    if result['samples'] != last_samples:
                        last_samples = result['samples'];last_hid = time.monotonic()
                    self.sample = dict(result, active=active, at=last_hid, session=current)
                    seen, action = next_event(result, seen)
                    if action is not None:
                        self.events.put((action, seen, current, time.monotonic()))
                except Exception as exc:
                    self.error = 'Controller shortcuts need the updated emulator bridge: '+str(exc)
                    self.sample = None
                    self.stop_event.wait(.5)
        except Exception as exc:
            self.error = str(exc)
        finally:
            if session:
                try:client.call('controller_debug', dict(owner=owner, enabled=False, bindings=[mask(self.config['bindings'][a]) for a in ACTIONS]), timeout=1)
                except Exception:pass
            client.close()
