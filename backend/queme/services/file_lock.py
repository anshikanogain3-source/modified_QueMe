"""Small cross-platform helpers for non-blocking process locks."""
import errno
import os

if os.name == "nt":
    import msvcrt
else:
    import fcntl


def try_lock(lock_file):
    """Acquire an exclusive non-blocking lock, raising BlockingIOError if busy."""
    if os.name == "nt":
        # msvcrt locks byte ranges, so ensure the shared lock file has a byte to lock.
        lock_file.seek(0, os.SEEK_END)
        if lock_file.tell() == 0:
            lock_file.write("\0")
            lock_file.flush()
        lock_file.seek(0)
        try:
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise BlockingIOError(*exc.args) from exc
            raise
    else:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def unlock(lock_file):
    """Release a lock previously acquired by try_lock."""
    if os.name == "nt":
        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
