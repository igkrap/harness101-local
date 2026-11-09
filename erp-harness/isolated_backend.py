import os
import uuid
import sys
from urllib.parse import urlparse

def run_backend(checker, callback) -> dict:
    """Runs the Maven checker with a dynamically created database."""
    db_url = os.environ.get("HARNESS_TEST_DB_URL", "jdbc:postgresql://mdi-db:5432/mdi_local_test")
    parsed = urlparse(db_url.replace("jdbc:", "", 1))
    
    if parsed.hostname != "mdi-db" or parsed.port != 5432:
        return {"success": False, "error": "Invalid HARNESS_TEST_DB_URL"}

    db_name = f"mdi_gate_{uuid.uuid4().hex[:16]}"
    create_cmd = ['docker', 'exec', 'mdi-db', 'psql', '-U', 'mdi', '-d', 'postgres', '-v', 'ON_ERROR_STOP=1', '-c', f'CREATE DATABASE {db_name}']
    
    create_res = checker._exec(create_cmd)
    if not create_res.get("success"):
        return {"success": False, "error": f"DB Creation failed: {create_res.get('stderr')}"}

    old_url = os.environ.get("HARNESS_TEST_DB_URL")
    os.environ["HARNESS_TEST_DB_URL"] = f"jdbc:postgresql://mdi-db:5432/{db_name}"
    
    result = None
    cleanup_failed = False
    try:
        result = callback()
    finally:
        if old_url is None:
            del os.environ["HARNESS_TEST_DB_URL"]
        else:
            os.environ["HARNESS_TEST_DB_URL"] = old_url

        active_exception = sys.exc_info()[0]
        drop_cmd = ['docker', 'exec', 'mdi-db', 'psql', '-U', 'mdi', '-d', 'postgres', '-c', f'DROP DATABASE IF EXISTS {db_name} WITH (FORCE)']
        drop_res = checker._exec(drop_cmd)
        
        if not drop_res.get("success"):
            if active_exception is None:
                result = {"success": False, "error": f"Cleanup failed: {drop_res.get('stderr')}"}
            cleanup_failed = True


    return result
