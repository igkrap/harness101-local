import http.server
import socketserver
import json
import sqlite3
import argparse
import sys
import os
import re
from urllib.parse import urlparse, parse_qs

class TodoDB:
    def __init__(self, db_path):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS todos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    done BOOLEAN NOT NULL DEFAULT 0
                )
            ''')
            conn.commit()

    def get_all(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute('SELECT id, title, done FROM todos ORDER BY id ASC')
            result = []
            for row in cursor.fetchall():
                d = dict(row)
                d['done'] = bool(d['done'])
                result.append(d)
            return result

    def add(self, title):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute('INSERT INTO todos (title, done) VALUES (?, 0)', (title,))
            new_id = cursor.lastrowid
            conn.commit()
            return {"id": new_id, "title": title, "done": False}

    def update_done(self, todo_id, done):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute('UPDATE todos SET done = ? WHERE id = ?', (int(done), todo_id))
            if cursor.rowcount == 0:
                return None
            conn.commit()
            row = conn.execute('SELECT id, title, done FROM todos WHERE id = ?', (todo_id,)).fetchone()
            if row:
                res = dict(row)
                res['done'] = bool(res['done'])
                return res
            return None

    def delete(self, todo_id):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute('DELETE FROM todos WHERE id = ?', (todo_id,))
            conn.commit()
            return cursor.rowcount > 0

    def get_by_id(self, todo_id):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute('SELECT id, title, done FROM todos WHERE id = ?', (todo_id,)).fetchone()
            if row:
                res = dict(row)
                res['done'] = bool(res['done'])
                return res
            return None

class TodoHandler(http.server.BaseHTTPRequestHandler):
    db = None

    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            with open('index.html', 'rb') as f:
                self.wfile.write(f.read())
        elif self.path == '/api/todos':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            todos = self.db.get_all()
            self.wfile.write(json.dumps({"items": todos}).encode())
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == '/api/todos':
            try:
                content_length = int(self.headers.get('Content-Length', 0))
            except (ValueError, TypeError):
                self.send_error_json(400, "Invalid Content-Length")
                return

            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data)
                title = data.get('title')
                
                if not isinstance(title, str):
                    self.send_error_json(422, "Title must be a string.")
                    return

                title = title.strip()
                if not (1 <= len(title) <= 100):
                    self.send_error_json(422, "Title must be between 1 and 100 characters.")
                    return
                
                new_todo = self.db.add(title)
                self.send_response(201)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"item": new_todo}).encode())
            except json.JSONDecodeError:
                self.send_error_json(422, "Invalid JSON.")
            except Exception as e:
                self.send_error_json(500, str(e))
        else:
            self.send_error(404)

    def do_PATCH(self):
        match = re.match(r'/api/todos/(\d+)', self.path)
        if match:
            todo_id = int(match.group(1))
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data)
                if 'done' not in data or not isinstance(data['done'], bool):
                    self.send_error_json(422, "Field 'done' must be a boolean.")
                    return
                
                updated_todo = self.db.update_done(todo_id, data['done'])
                if updated_todo:
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    updated_todo['done'] = bool(updated_todo['done'])
                    self.wfile.write(json.dumps({"item": updated_todo}).encode())
                else:
                    self.send_error_json(404, "Todo not found.")
            except json.JSONDecodeError:
                self.send_error_json(422, "Invalid JSON.")
            except Exception as e:
                self.send_error_json(500, str(e))
        else:
            self.send_error(404)

    def do_DELETE(self):
        match = re.match(r'/api/todos/(\d+)', self.path)
        if match:
            todo_id = int(match.group(1))
            success = self.db.delete(todo_id)
            if success:
                self.send_response(204)
                self.end_headers()
            else:
                self.send_error_json(404, "Todo not found.")
        else:
            self.send_error(404)

    def send_error_json(self, code, message):
        self.send_response(code)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({"error": message}).encode())

def run_server(port, db_path):
    TodoHandler.db = TodoDB(db_path)
    class ReusableTCPServer(socketserver.TCPServer):
        allow_reuse_address = True
    with ReusableTCPServer(("", port), TodoHandler) as httpd:
        print(f"Serving at port {port}")
        httpd.serve_forever()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--db', type=str, default='todo.sqlite3')
    args = parser.parse_args()
    run_server(args.port, args.db)
