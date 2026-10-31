import urllib.request
import urllib.error
import json
import time
import subprocess
import os

def test_api():
    base_url = "http://localhost:8000/api/todos"
    
    print("--- Testing GET /api/todos ---")
    try:
        with urllib.request.urlopen(base_url) as response:
            data = json.loads(response.read().decode())
            print(f"GET /api/todos: {data}")
            assert "items" in data
            for item in data["items"]:
                assert isinstance(item["done"], bool), f"Expected bool for 'done', got {type(item['done'])}"
    except Exception as e:
        print(f"GET /api/todos failed: {e}")
        return False

    print("\n--- Testing POST /api/todos (Valid) ---")
    try:
        data = json.dumps({"title": "Test Todo"}).encode()
        req = urllib.request.Request(base_url, data=data, headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(req) as response:
            res_data = json.loads(response.read().decode())
            print(f"POST /api/todos (Valid): {res_data}")
            assert "item" in res_data
            assert isinstance(res_data["item"]["done"], bool)
    except Exception as e:
        print(f"POST /api/todos (Valid) failed: {e}")
        return False

    print("\n--- Testing POST /api/todos (Invalid - non-string title) ---")
    try:
        data = json.dumps({"title": 123}).encode()
        req = urllib.request.Request(base_url, data=data, headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(req) as response:
            print(f"POST /api/todos (Invalid) unexpected success: {response.status}")
            return False
    except urllib.error.HTTPError as e:
        res_data = json.loads(e.read().decode())
        print(f"POST /api/todos (Invalid) correctly failed with {e.code}: {res_data}")
        assert e.code == 422
        assert "title" in res_data.get("error", "").lower() or "string" in res_data.get("error", "").lower()
    except Exception as e:
        print(f"POST /api/todos (Invalid) failed with unexpected error: {e}")
        return False

    print("\n--- Testing PATCH /api/todos/<id> (Valid) ---")
    try:
        # Get the ID from the first todo
        with urllib.request.urlopen(base_url) as response:
            todos = json.loads(response.read().decode())["items"]
            if not todos:
                print("No todos found to patch.")
                return False
            todo_id = todos[0]["id"]
        
        patch_url = f"http://localhost:8000/api/todos/{todo_id}"
        data = json.dumps({"done": True}).encode()
        req = urllib.request.Request(patch_url, data=data, headers={'Content-Type': 'application/json'}, method='PATCH')
        with urllib.request.urlopen(req) as response:
            res_data = json.loads(response.read().decode())
            print(f"PATCH /api/todos/{todo_id} (Valid): {res_data}")
            assert res_data["item"]["done"] is True
            assert isinstance(res_data["item"]["done"], bool)
    except Exception as e:
        print(f"PATCH /api/todos (Valid) failed: {e}")
        return False

    print("\n--- Testing DELETE /api/todos/<id> (Valid) ---")
    try:
        with urllib.request.urlopen(base_url) as response:
            todos = json.loads(response.read().decode())["items"]
            if not todos:
                print("No todos found to delete.")
                return False
            todo_id = todos[0]["id"]
        
        del_url = f"http://localhost:8000/api/todos/{todo_id}"
        req = urllib.request.Request(del_url, method='DELETE')
        with urllib.request.urlopen(req) as response:
            print(f"DELETE /api/todos/{todo_id} (Valid): Status {response.status}")
            assert response.status == 204
    except Exception as e:
        print(f"DELETE /api/todos (Valid) failed: {e}")
        return False

    return True

def test_server_restart():
    print("\n--- Testing Server Restart (Address Reuse) ---")
    port = 8001
    db_file = "test_restart.sqlite3"
    if os.path.exists(db_file):
        os.remove(db_file)
        
    # Start server
    proc = subprocess.Popen(["python", "app.py", "--port", str(port), "--db", db_file])
    time.sleep(2)
    
    # Kill server
    proc.terminate()
    proc.wait()
    time.sleep(1)
    
    # Try to start again immediately
    try:
        proc2 = subprocess.Popen(["python", "app.py", "--port", str(port), "--db", db_file])
        time.sleep(2)
        if proc2.poll() is None:
            print("Server restarted successfully.")
            proc2.terminate()
            proc2.wait()
            return True
        else:
            print(f"Server failed to restart. Exit code: {proc2.returncode}")
            return False
    except Exception as e:
        print(f"Server restart test failed with error: {e}")
        return False

if __name__ == "__main__":
    print("Starting API tests...")
    api_success = test_api()
    
    print("\nStarting Restart tests...")
    restart_success = test_server_restart()
    
    if api_success and restart_success:
        print("\nALL TESTS PASSED!")
        exit(0)
    else:
        print("\nSOME TESTS FAILED!")
        exit(1)
