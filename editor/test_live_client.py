"""Debug protocol connection reuse and no automatic replay after uncertain requests."""
import json
import unittest
from unittest.mock import patch
from live import Client, ROOT, TITLE


class Connection:
    def __init__(self, lose=False, wrong_id=False):
        self.requests=[];self.response=b'';self.closed=False
        self.lose=lose;self.wrong_id=wrong_id
    def setsockopt(self,*args):pass
    def settimeout(self,*args):pass
    def sendall(self,data):
        row=json.loads(data);self.requests.append(row)
        self.response=json.dumps({'id':row['id'] + int(self.wrong_id),'result':{'ok':True}}).encode()+b'\n'
    def recv(self,size):
        if self.lose:raise TimeoutError('response lost')
        part,self.response=self.response[:7],self.response[7:]
        return part
    def close(self):self.closed=True


class ClientTest(unittest.TestCase):
    def test_capability_status_does_not_block_for_fps_sampling(self):
        c=Client()
        with patch.object(c,'call',return_value={'program_id':TITLE,'dump_dir':str(ROOT/'runtime/live-debug')} ) as call:
            c.status()
            call.assert_called_once_with('status',{'fps_window_ms':0})

    def test_continuous_polling_reuses_one_connection(self):
        connection=Connection()
        with patch('live.socket.create_connection',return_value=connection) as create:
            c=Client()
            for _ in range(100):self.assertTrue(c.call('status')['ok'])
            self.assertEqual(create.call_count,1)
            self.assertEqual([r['id'] for r in connection.requests],list(range(1,101)))
            c.close();self.assertTrue(connection.closed)
    def test_lost_write_response_does_not_reconnect_or_replay(self):
        connection=Connection(lose=True)
        with patch('live.socket.create_connection',return_value=connection) as create:
            c=Client()
            with self.assertRaises(TimeoutError):c.call('compare_write32',{'value':1})
            self.assertEqual(len(connection.requests),1)
            self.assertEqual(create.call_count,1)
            self.assertTrue(connection.closed)
    def test_wrong_response_id_closes_connection(self):
        connection=Connection(wrong_id=True)
        with patch('live.socket.create_connection',return_value=connection):
            c=Client()
            with self.assertRaisesRegex(ValueError,'response ID'):c.call('status')
            self.assertTrue(connection.closed)


if __name__=='__main__':unittest.main()
