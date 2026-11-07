"""Offline UI-job tests without importing ImGui, backend or an emulator client."""
import ast
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from native_ui import native_message, whole_heart_maximum


class NativeUiTests(unittest.TestCase):
    def test_maximum_health_clamps_to_whole_hearts(self):
        for value, expected in ((0,12),(11,12),(12,12),(13,12),(23,20),(80,80),(99,80)):
            with self.subTest(value=value):
                self.assertEqual(whole_heart_maximum(value), expected)

    def test_all_field_verification_gates_default_false(self):
        tree = ast.parse((ROOT / 'app.py').read_text(encoding='utf-8'))
        assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
                          and any(isinstance(target, ast.Name) and target.id == 'NATIVE_GAMEPLAY_VERIFIED'
                                  for target in node.targets))
        self.assertEqual(ast.literal_eval(assignment.value),
                         {'Life':False,'MaxLife':False,'MP':False,'MPMax':False})

    def test_outcome_messages_never_claim_effect(self):
        text, error = native_message(dict(field='MP', state='queued_effect_unverified'))
        self.assertIn('queued', text)
        self.assertIn('not yet verified', text)
        self.assertFalse(error)
        self.assertIn('no changes', native_message(dict(state='busy_no_changes'))[0])
        self.assertTrue(native_message(dict(state='uncertain_no_retry'))[1])
        self.assertIn('Do not repeat', native_message(dict(state='uncertain_no_retry'))[0])

    def methods(self):
        tree = ast.parse((ROOT / 'app.py').read_text(encoding='utf-8'))
        editor = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'Editor')
        functions = [node for node in editor.body if isinstance(node, ast.FunctionDef)
                     and node.name in ('native_edit', 'native_job', 'player_edit', 'player_job',
                                       'magic_edit','magic_job')]
        namespace = dict(NATIVE_GAMEPLAY_VERIFIED={'Life':False,'MP':False},
                         PLAYER_CURRENT_LIFE_VERIFIED=True, PLAYER_CURRENT_MAGIC_VERIFIED=True)
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(ROOT/'app.py'), 'exec'), namespace)
        return namespace

    def test_magic_job_uses_actor_writer_and_clears_previous_undo(self):
        methods=self.methods()
        calls=[]
        magic=types.SimpleNamespace(write_current=lambda *args:(calls.append(args) or {'state':'applied','field':'MP'}))
        editor=types.SimpleNamespace(player_magic=magic,binding=types.SimpleNamespace(last_edit={'old':'inventory'}),
                                     read_values=lambda:{'items':{}})
        result=methods['magic_job'](editor,24,48)
        self.assertEqual(calls,[(24,48)])
        self.assertIsNone(editor.binding.last_edit)
        self.assertEqual(result['kind'],'player')

    def test_player_action_requires_binding_and_captures_visible_expected(self):
        methods = self.methods()
        queued = []
        editor = types.SimpleNamespace(player_life=None, submit=lambda *args:queued.append(args))
        with self.assertRaises(ValueError):methods['player_edit'](editor, 10, 12)
        self.assertEqual(queued, [])
        calls = []
        editor.player_life = object()
        editor.player_job = lambda *args:calls.append(args)
        methods['player_edit'](editor, 10, 12)
        self.assertTrue(editor.native_undo_blocked)
        queued[0][1]()
        self.assertEqual(calls, [(10,12)])

    def test_player_job_clears_old_undo_and_calls_only_current_writer(self):
        methods = self.methods()
        calls = []
        player = types.SimpleNamespace(write_current=lambda *args:(calls.append(args) or {'state':'applied'}))
        editor = types.SimpleNamespace(player_life=player,
            binding=types.SimpleNamespace(last_edit={'old':'inventory'}), read_values=lambda:{'items':{}})
        result = methods['player_job'](editor, 10, 12)
        self.assertIsNone(editor.binding.last_edit)
        self.assertEqual(calls, [(10,12)])
        self.assertEqual(result['kind'], 'player')

    def test_default_gate_refuses_before_submitting(self):
        functions = self.methods()
        submitted = []
        editor = types.SimpleNamespace(submit=lambda *args:submitted.append(args))
        with self.assertRaises(ValueError):
            functions['native_edit'](editor, 'MP', 0, 24)
        self.assertEqual(submitted, [])

    def test_job_uses_captured_expected_zero_retries_and_clears_previous_undo(self):
        functions = self.methods()
        received = []
        class FakeNative:
            def __init__(self, binding):
                self.session_id = binding.session_id
            def bind(self):
                received.append('bind')
            def set_int(self, *args, **kwargs):
                received.append((args, kwargs))
                return dict(field='MP', state='queued_effect_unverified')
        binding = types.SimpleNamespace(last_edit={'older':'inventory'}, session_id=(1,'one'),
                                        view=lambda:{'items':{}})
        editor = types.SimpleNamespace(binding=binding, native=None)
        with patch.dict(sys.modules, {'native_requests':types.SimpleNamespace(NativeRequests=FakeNative)}):
            result = functions['native_job'](editor, 'MP', 7, 24)
        self.assertIsNone(binding.last_edit)
        self.assertEqual(received, ['bind', (('MP',7,24), {'busy_retries':0})])
        self.assertEqual(result['kind'], 'native')

    def test_failed_lazy_bind_is_not_cached(self):
        functions = self.methods()
        class UnavailableNative:
            def __init__(self, binding): pass
            def bind(self): raise ValueError('unsupported build')
        editor = types.SimpleNamespace(binding=types.SimpleNamespace(last_edit={}, session_id=(1,'one')), native=None)
        with patch.dict(sys.modules, {'native_requests':types.SimpleNamespace(NativeRequests=UnavailableNative)}):
            with self.assertRaises(ValueError):
                functions['native_job'](editor, 'MP', 0, 24)
        self.assertIsNone(editor.native)


if __name__ == '__main__':
    unittest.main(verbosity=2)
