import signal
import threading
import logging
from autonomy_runtime import Runner, StopLoop, BudgetEnd

logger = logging.getLogger("autonomy")

def run_supervised(args, harness_class) -> bool:
    args.stop_requested = False
    args.stop_cleanup_failed = False
    runner = Runner(args, harness_class)
    result = False
    old_sigterm = signal.getsignal(signal.SIGTERM)
    old_sigint = signal.getsignal(signal.SIGINT)

    def _handle_signal(signum, frame):
        if threading.current_thread() is threading.main_thread():
            if not args.stop_requested:
                args.stop_requested = True
                raise StopLoop()

    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)

    try:
        result = runner.run()
    except StopLoop:
        runner.h.log_event('autonomy.stopped',{})
        result = False
    except BudgetEnd:
        runner.h.log_event('autonomy.exhausted',{'rounds':runner.used})
        result = False
    except RuntimeError as exc:
        args.stop_cleanup_failed = True
        runner.h.log_event('autonomy.conflict',{'error':str(exc)})
        result = False
    except Exception as exc:
        args.stop_cleanup_failed = True
        runner.h.log_event('autonomy.error',{'error':str(exc)})
        result = False
    finally:
        try:
            if runner.cp.pending:
                paths = runner.cp.rollback()
                runner.h.log_event('autonomy.rollback',{'paths':paths,'reason':'unfinished operation'})
        except Exception:
            args.stop_cleanup_failed = True
            runner.h.log_event('autonomy.conflict',{'error':'rollback failed'})
            result = False

        try:
            intelligence = getattr(runner.h, '_code_intelligence', None)
            if intelligence is not None:
                intelligence.close()
        except Exception as exc:
            args.stop_cleanup_failed = True
            runner.h.log_event('autonomy.error', {'error': str(exc)})
            result = False

        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGTERM, old_sigterm)
            signal.signal(signal.SIGINT, old_sigint)

    return bool(result)
