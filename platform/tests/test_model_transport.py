"""Exercise the actual HTTP transport: liveness rather than total wall time."""
import http.server
import json
import socket
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-only/harness'))
import model_transport

class TransportTests(unittest.TestCase):
 def setUp(self):
  self.count=0;self.mode='ok'
  owner=self
  class Handler(http.server.BaseHTTPRequestHandler):
   def log_message(self,*a): pass
   def do_POST(self):
    owner.count+=1;owner.received_path=self.path;owner.received_header=self.headers.get('X-Test')
    self.rfile.read(int(self.headers.get('Content-Length','0')))
    try:
     if owner.mode=='headers':time.sleep(.18)
     if owner.mode in ('bad','busy'):
      self.send_response(400 if owner.mode=='bad' else 503);self.end_headers();return
     body=json.dumps({'choices':[{'message':{'content':'complete'}}]}).encode()
     if owner.mode=='invalid':body=b'bad json'
     self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.flush()
     if owner.mode=='stall':time.sleep(.18)
     if owner.mode=='trickle':
      for i in range(0,len(body),8):self.wfile.write(body[i:i+8]);self.wfile.flush();time.sleep(.025)
     else:self.wfile.write(body)
    except (BrokenPipeError,ConnectionResetError):pass
  self.server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
  self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
  self.request=urllib.request.Request('http://127.0.0.1:'+str(self.server.server_port)+'/v1/chat/completions',b'{"model":"test"}',{'Content-Type':'application/json'})
 def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join()
 def test_complete_json(self):self.assertEqual(model_transport.complete(self.request,1)['choices'][0]['message']['content'],'complete')
 def test_healthy_bytes_extend_beyond_timeout(self):
  self.mode='trickle';start=time.monotonic();model_transport.complete(self.request,.09);self.assertGreater(time.monotonic()-start,.09)
 def test_headers_timeout_is_distinct_and_not_internally_retried(self):
  self.mode='headers'
  with self.assertRaisesRegex(TimeoutError,'response_headers'):model_transport.complete(self.request,.04)
  self.assertEqual(self.count,1)
 def test_body_idle_timeout_is_distinct_and_not_retried(self):
  self.mode='stall'
  with self.assertRaisesRegex(TimeoutError,'response_body_idle'):model_transport.complete(self.request,.04)
  self.assertEqual(self.count,1)
 def test_permanent_http_error_not_retried(self):
  self.mode='bad'
  with self.assertRaises(urllib.error.HTTPError) as e:model_transport.complete(self.request,1)
  self.assertEqual(e.exception.code,400);self.assertEqual(self.count,1)
 def test_transient_http_backoff_bounded(self):
  self.mode='busy'
  with patch('model_transport.time.sleep') as sleep:
   with self.assertRaises(urllib.error.HTTPError):model_transport.complete(self.request,1)
  self.assertEqual(self.count,5);self.assertEqual([c.args[0] for c in sleep.call_args_list],[1,2,4,8])
 def test_invalid_json_not_retried(self):
  self.mode='invalid'
  with self.assertRaises(ValueError):model_transport.complete(self.request,1)
  self.assertEqual(self.count,1)
 def test_non_loopback_rejected(self):
  req=urllib.request.Request('http://example.com/v1',b'{}')
  with self.assertRaises(ValueError):model_transport.complete(req,1)

 def test_preserves_query_headers_and_method(self):
  req=urllib.request.Request(self.request.full_url+'?session=42',b'{}',{'X-Test':'preserved'},method='POST')
  model_transport.complete(req,1);self.assertEqual(self.received_path,'/v1/chat/completions?session=42');self.assertEqual(self.received_header,'preserved')

 def test_connection_refusal_has_bounded_retry(self):
  with patch('model_transport.http.client.HTTPConnection.connect',side_effect=ConnectionRefusedError('refused')) as connect,patch('model_transport.time.sleep') as sleep:
   with self.assertRaises(ConnectionRefusedError):model_transport.complete(self.request,1)
  self.assertEqual(connect.call_count,5);self.assertEqual([c.args[0] for c in sleep.call_args_list],[1,2,4,8])
 def test_cancel_is_never_retried(self):
  with patch('model_transport.http.client.HTTPConnection.connect',side_effect=KeyboardInterrupt()) as connect,patch('model_transport.time.sleep') as sleep:
   with self.assertRaises(KeyboardInterrupt):model_transport.complete(self.request,1)
  self.assertEqual(connect.call_count,1);sleep.assert_not_called()
 def test_connect_timeout_is_named_without_internal_retry(self):
  with patch('model_transport.http.client.HTTPConnection.connect',side_effect=TimeoutError()) as connect:
   with self.assertRaisesRegex(TimeoutError,'connect'):model_transport.complete(self.request,1)
  self.assertEqual(connect.call_count,1)
