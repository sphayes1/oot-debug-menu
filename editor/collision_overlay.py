"""Click-through Windows OpenGL collision overlay. Spawned by the debug menu only."""
import argparse
import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import socket
import sys
import time
import numpy as np


def viewport(rect, aspect):
    """Fit the game's projection aspect inside its client area (letterbox aware)."""
    x, y, w, h = rect
    if w <= 0 or h <= 0 or not .2 < aspect < 10:
        raise ValueError('Invalid collision viewport')
    width, height = min(w, h*aspect), min(h, w/aspect)
    return (round(x+(w-width)/2), round(y+(h-height)/2), max(1, round(width)), max(1, round(height)))


class Windows:
    def __init__(self, parent):
        self.parent = parent
        self.user = C.WinDLL('user32', use_last_error=True)
        self.kernel = C.WinDLL('kernel32', use_last_error=True)
        self.enum = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
        u = self.user
        for name, args, result in (
            ('EnumWindows', [self.enum, W.LPARAM], W.BOOL),
            ('GetWindowThreadProcessId', [W.HWND, C.POINTER(W.DWORD)], W.DWORD),
            ('IsWindowVisible', [W.HWND], W.BOOL), ('IsIconic', [W.HWND], W.BOOL),
            ('GetClientRect', [W.HWND, C.POINTER(W.RECT)], W.BOOL),
            ('ClientToScreen', [W.HWND, C.POINTER(W.POINT)], W.BOOL),
            ('GetForegroundWindow', [], W.HWND),
            ('GetWindowLongPtrW', [W.HWND, C.c_int], C.c_ssize_t),
            ('SetWindowLongPtrW', [W.HWND, C.c_int, C.c_ssize_t], C.c_ssize_t),
            ('SetWindowPos', [W.HWND, W.HWND, C.c_int, C.c_int, C.c_int, C.c_int, W.UINT], W.BOOL)):
            fn = getattr(u, name); fn.argtypes = args; fn.restype = result
        self.kernel.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
        self.kernel.OpenProcess.restype = W.HANDLE
        self.kernel.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
        self.kernel.CloseHandle.argtypes = [W.HANDLE]
        self.parent_handle = self.kernel.OpenProcess(0x100000, False, parent)
        if not self.parent_handle:
            raise ValueError('Collision editor process has exited')

    def alive(self):
        return self.kernel.WaitForSingleObject(self.parent_handle, 0) == 258

    def pid(self, hwnd):
        pid = W.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, C.byref(pid))
        return pid.value

    def target(self, pid):
        choices = []
        @self.enum
        def collect(hwnd, _):
            if self.pid(hwnd) == pid and self.user.IsWindowVisible(hwnd) and not self.user.IsIconic(hwnd):
                r = W.RECT()
                if self.user.GetClientRect(hwnd, C.byref(r)) and r.right > 200 and r.bottom > 150:
                    p = W.POINT(0, 0)
                    self.user.ClientToScreen(hwnd, C.byref(p))
                    choices.append((r.right*r.bottom, hwnd, (p.x, p.y, r.right, r.bottom)))
            return True
        self.user.EnumWindows(collect, 0)
        if not choices:
            return None
        _, hwnd, rect = max(choices, key=lambda v: v[0])
        foreground = self.user.GetForegroundWindow()
        return (hwnd, rect) if self.pid(foreground) in (pid, self.parent) else None

    def overlay(self, hwnd):
        # GLFW MOUSE_PASSTHROUGH supplies TRANSPARENT + LAYERED together.
        # Add NOACTIVATE / TOOLWINDOW to keep this out of focus and Alt-Tab.
        flags = self.user.GetWindowLongPtrW(hwnd, -20)
        self.user.SetWindowLongPtrW(hwnd, -20, flags | 0x20 | 0x80000 | 0x08000000 | 0x80)

    def move(self, hwnd, rect):
        foreground = self.user.GetForegroundWindow()
        after = foreground if self.pid(foreground) == self.parent else W.HWND(0)
        self.user.SetWindowPos(hwnd, after, *rect, 0x10)

    def close(self):
        self.kernel.CloseHandle(self.parent_handle)


VERTEX = '''#version 330 core
layout(location=0) in vec3 position;
layout(location=1) in float category;
uniform mat4 vp;
out vec3 world;
flat out int kind;
void main(){world=position;kind=int(category);gl_Position=vp*vec4(position,1.0);}
'''
FRAGMENT = '''#version 330 core
in vec3 world;
flat in int kind;
uniform int enabled;
uniform vec3 eye;
uniform float radius;
uniform float opacity;
out vec4 color;
const vec3 colors[7]=vec3[7](vec3(.58,.78,.87),vec3(1.,.24,.19),vec3(1.,.62,.12),
 vec3(.77,.32,1.),vec3(.1,.85,.69),vec3(.2,.5,1.),vec3(.95,.45,.72));
void main(){if((enabled&(1<<kind))==0||distance(world,eye)>radius)discard;
 color=vec4(colors[clamp(kind,0,6)],opacity);}
'''


class Renderer:
    def __init__(self):
        from OpenGL import GL
        from OpenGL.GL.shaders import compileProgram, compileShader
        self.gl = GL
        self.program = compileProgram(compileShader(VERTEX, GL.GL_VERTEX_SHADER), compileShader(FRAGMENT, GL.GL_FRAGMENT_SHADER))
        self.vao = GL.glGenVertexArrays(1)
        self.vbo = GL.glGenBuffers(1)
        GL.glBindVertexArray(self.vao)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo)
        GL.glVertexAttribPointer(0, 3, GL.GL_FLOAT, False, 16, C.c_void_p(0))
        GL.glVertexAttribPointer(1, 1, GL.GL_FLOAT, False, 16, C.c_void_p(12))
        GL.glEnableVertexAttribArray(0); GL.glEnableVertexAttribArray(1)
        self.uniforms = {key: GL.glGetUniformLocation(self.program, key) for key in ('vp', 'enabled', 'eye', 'radius', 'opacity')}
        self.path = None
        self.scene = None
        self.count = 0

    def load(self, path, scene):
        if self.path == path and self.scene == scene:
            return
        p = Path(path).resolve()
        root = Path(__file__).resolve().parent/'runtime/collision'
        if not p.is_relative_to(root.resolve()) or p.suffix != '.npz' or p.stat().st_size > 256*1024*1024:
            raise ValueError('Collision cache is outside this editor runtime')
        with np.load(p, allow_pickle=False) as data:
            metadata = json.loads(str(data['metadata']))
            tr, kinds = data['triangles'], data['kinds']
        if (metadata['scene'] != scene or tr.ndim != 3 or tr.shape[1:] != (3, 3) or
                tr.dtype != np.float32 or len(tr) > 4_000_000 or kinds.shape != (len(tr),) or
                not np.isfinite(tr).all() or not np.isin(kinds, range(7)).all()):
            raise ValueError('Invalid collision mesh cache')
        vertices = np.empty((len(tr)*3, 4), np.float32)
        vertices[:, :3] = tr.reshape(-1, 3)
        vertices[:, 3] = np.repeat(kinds, 3)
        g = self.gl
        g.glBindBuffer(g.GL_ARRAY_BUFFER, self.vbo)
        g.glBufferData(g.GL_ARRAY_BUFFER, vertices.nbytes, vertices, g.GL_STATIC_DRAW)
        self.path, self.scene, self.count = path, scene, len(vertices)

    def draw(self, state, width, height):
        g = self.gl
        g.glViewport(0, 0, width, height)
        g.glClearColor(0, 0, 0, 0)
        g.glClear(g.GL_COLOR_BUFFER_BIT | g.GL_DEPTH_BUFFER_BIT)
        view = np.asarray(state['view'], np.float32).reshape(4, 4)
        projection = np.asarray(state['projection'], np.float32).reshape(4, 4)
        vp = np.ascontiguousarray(projection @ view)
        g.glUseProgram(self.program)
        g.glBindVertexArray(self.vao)
        g.glUniformMatrix4fv(self.uniforms['vp'], 1, True, vp)
        g.glUniform1i(self.uniforms['enabled'], int(state.get('mask', 63)) & 127)
        g.glUniform3f(self.uniforms['eye'], *state['eye'])
        g.glUniform1f(self.uniforms['radius'], float(state.get('radius', 100)))
        g.glDisable(g.GL_CULL_FACE)
        g.glEnable(g.GL_BLEND)
        g.glBlendFuncSeparate(g.GL_SRC_ALPHA, g.GL_ONE_MINUS_SRC_ALPHA, g.GL_ONE, g.GL_ONE_MINUS_SRC_ALPHA)
        g.glDepthMask(True)
        if state.get('xray'):
            g.glDisable(g.GL_DEPTH_TEST)
        else:
            g.glEnable(g.GL_DEPTH_TEST)
            g.glDepthFunc(g.GL_LEQUAL)
            g.glColorMask(False, False, False, False)
            g.glPolygonMode(g.GL_FRONT_AND_BACK, g.GL_FILL)
            g.glDrawArrays(g.GL_TRIANGLES, 0, self.count)
            g.glColorMask(True, True, True, True)
        if state.get('fill', True):
            g.glPolygonMode(g.GL_FRONT_AND_BACK, g.GL_FILL)
            g.glUniform1f(self.uniforms['opacity'], float(state.get('opacity', .12)))
            g.glDrawArrays(g.GL_TRIANGLES, 0, self.count)
        g.glPolygonMode(g.GL_FRONT_AND_BACK, g.GL_LINE)
        g.glUniform1f(self.uniforms['opacity'], .8)
        g.glDrawArrays(g.GL_TRIANGLES, 0, self.count)
        g.glPolygonMode(g.GL_FRONT_AND_BACK, g.GL_FILL)

    def close(self):
        self.gl.glDeleteBuffers(1, [self.vbo])
        self.gl.glDeleteVertexArrays(1, [self.vao])
        self.gl.glDeleteProgram(self.program)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--parent', type=int, required=True)
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--token', required=True)
    a = p.parse_args()
    # This process uses the glfw package's own 3.4 DLL. The menu's older
    # bundled DLL lacks the mouse-passthrough creation hint.
    os.environ.pop('PYGLFW_LIBRARY', None)
    import glfw
    native = Windows(a.parent)
    channel = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    channel.bind(('127.0.0.1', 0)); channel.setblocking(False)
    destination = ('127.0.0.1', a.port)
    def report(**value):
        channel.sendto(json.dumps(dict(token=a.token, **value)).encode(), destination)
    window = renderer = None
    try:
        if not glfw.init():
            raise RuntimeError('Cannot initialize collision OpenGL renderer')
        for key, value in ((glfw.VISIBLE, False), (glfw.DECORATED, False), (glfw.FOCUSED, False),
                           (glfw.FLOATING, False), (glfw.MOUSE_PASSTHROUGH, True), (glfw.TRANSPARENT_FRAMEBUFFER, True),
                           (glfw.CONTEXT_VERSION_MAJOR, 3), (glfw.CONTEXT_VERSION_MINOR, 3),
                           (glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE), (glfw.DEPTH_BITS, 24)):
            glfw.window_hint(key, value)
        window = glfw.create_window(640, 360, 'Ocarina collision overlay', None, None)
        if not window or not glfw.get_window_attrib(window, glfw.TRANSPARENT_FRAMEBUFFER):
            raise RuntimeError('Desktop does not support a transparent collision overlay')
        hwnd = glfw.get_win32_window(window)
        native.overlay(hwnd)
        glfw.make_context_current(window); glfw.swap_interval(0)
        renderer = Renderer()
        state = {}
        last = time.monotonic()
        last_report = 0.
        shown = False
        logged = None
        while native.alive() and not glfw.window_should_close(window):
            start = time.monotonic()
            try:
                while True:
                    raw, source = channel.recvfrom(65536)
                    if source != destination:
                        continue
                    value = json.loads(raw)
                    if value.get('token') == a.token:
                        state = value
                        last = start
            except BlockingIOError:
                pass
            if state.get('stop') or start-last > 8:
                break
            target = native.target(int(state.get('pid', 0))) if state.get('path') and start-last < .5 else None
            valid = bool(target and state.get('visible') and state.get('scene'))
            if valid:
                renderer.load(state['path'], state['scene'])
                aspect = abs(state['projection'][5]/state['projection'][0])
                rect = viewport(target[1], aspect)
                native.move(hwnd, rect)
                if not shown:
                    glfw.show_window(window); shown = True
                renderer.draw(state, *glfw.get_framebuffer_size(window))
                if os.environ.get('OOT_COLLISION_CAPTURE') == '1' and not getattr(renderer, 'captured', False):
                    from PIL import Image
                    width, height = glfw.get_framebuffer_size(window)
                    pixels = renderer.gl.glReadPixels(0, 0, width, height, renderer.gl.GL_RGBA, renderer.gl.GL_UNSIGNED_BYTE)
                    Image.frombytes('RGBA', (width, height), pixels).transpose(Image.Transpose.FLIP_TOP_BOTTOM).save(
                        Path(__file__).parent/'runtime/collision-preview.png')
                    renderer.captured = True
                glfw.swap_buffers(window)
            elif shown:
                glfw.hide_window(window); shown = False
            if start-last_report > .5:
                status = dict(ready=True, visible=shown, triangles=renderer.count//3, scene=renderer.scene,
                       transparent=True, click_through=bool(native.user.GetWindowLongPtrW(hwnd, -20) & 0x20))
                report(**status)
                diagnostic = dict(status, target_pid=state.get('pid'),
                                  foreground_pid=native.pid(native.user.GetForegroundWindow()),
                                  fresh=start-last < .5, requested=state.get('visible'))
                if diagnostic != logged:
                    print(json.dumps(diagnostic), flush=True)
                    logged = diagnostic
                last_report = start
            glfw.poll_events()
            time.sleep(max(.001, 1/30-(time.monotonic()-start)))
    except Exception as exc:
        report(error=str(exc))
        raise
    finally:
        if renderer:
            renderer.close()
        if window:
            glfw.destroy_window(window)
        glfw.terminate()
        native.close()
        channel.close()


if __name__ == '__main__':
    main()
