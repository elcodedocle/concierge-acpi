# ============================================================================
# PERSISTENT DICTIONARY
# ============================================================================

import json, os, shelve, threading
from collections import OrderedDict
from shelve import Shelf
from typing import Any, Dict, List, Optional


class FullDictionaryError(Exception):
    pass


class OptionallyPersistentOrderedThreadSafeDict:
    """
    Thread-safe ordered dictionary with optional persistence and capacity management.
    Uses shelve for persistence, maintains order in separate metadata.
    Survives unexpected restarts.
    Useful for a small serializable collection without high concurrency or frequent updates
    *** not an actual db, not multiprocess safe, the whole thing locks on r/w ***
    """

    def __init__(self, filepath: Optional[str] = None, max_size: int = 0):
        self._filepath = filepath
        self._max_size = max_size
        self.lock = threading.RLock()
        self._metadata_file = f"{filepath}_metadata.json" if filepath else None
        self._load_metadata()

    def _load_metadata(self) -> None:
        if self._filepath and self._metadata_file and os.path.exists(self._metadata_file):
            with open(self._metadata_file, 'r') as fp:
                metadata = json.load(fp)
                self._order = metadata.get('order', [])
                self._tagged_for_removal = OrderedDict((key, None) for key in metadata.get('tagged', []))
        else:
            self._order = []
            self._tagged_for_removal = OrderedDict()

        if self._filepath:
            with shelve.open(self._filepath) as db:
                self._order = [key for key in self._order if key in db]
            self._save_metadata()
        else:
            self._db = OrderedDict()

    def _save_metadata(self) -> None:
        if self._metadata_file:
            metadata = {
                'order': self._order,
                'tagged': list(self._tagged_for_removal.keys())
            }
            with open(self._metadata_file, 'w') as fp:
                json.dump(metadata, fp, indent=2)

    def __setitem__(self, key: str, value: Any) -> None:
        with self.lock:
            if self._filepath:
                with shelve.open(self._filepath, writeback=True) as db:
                    self._set_item(db, key, value)
                self._save_metadata()
            else:
                self._set_item(self._db, key, value)

    def _set_item(self, db: Dict|Shelf, key: str, value: Any) -> None:
        if key in db:
            db[key] = value
            self._order.remove(key)
            self._order.append(key)
            self._tagged_for_removal.pop(key, None)
        else:
            if 0 < self._max_size <= len(self._order):
                if not self._tagged_for_removal:
                    raise FullDictionaryError("No entry tagged for removal")

                removal_key, _ = self._tagged_for_removal.popitem(last=False)
                del db[removal_key]
                self._order.remove(removal_key)

            db[key] = value
            self._order.append(key)

    def __getitem__(self, key: str) -> Any:
        with self.lock:
            if not self._filepath:
                return self._db[key]
            with shelve.open(self._filepath) as db:
                return db[key]

    def __delitem__(self, key: str) -> None:
        with self.lock:
            if self._filepath:
                with shelve.open(self._filepath, writeback=True) as db:
                    self._del_internal(db, key)
                self._save_metadata()
            else:
                self._del_internal(self._db, key)

    def _del_internal(self, db: Dict|Shelf, key: str) -> None:
        if key in db:
            del db[key]
            self._order.remove(key)
            self._tagged_for_removal.pop(key, None)

    def __len__(self) -> int:
        with self.lock:
            return len(self._order)

    def __contains__(self, key: str) -> bool:
        with self.lock:
            if key not in self._order:
                return False
            if not self._filepath:
                return key in self._db
            with shelve.open(self._filepath) as db:
                return key in db

    def tag_for_removal(self, key: str) -> None:
        with self.lock:
            if key in self._order and key not in self._tagged_for_removal:
                self._tagged_for_removal[key] = None
                if self._filepath:
                    self._save_metadata()

    def get_oldest_key(self) -> str:
        with self.lock:
            if not self._order:
                raise KeyError("Dictionary is empty")
            return self._order[0]

    def get_newest(self) -> Any:
        with self.lock:
            if not self._order:
                raise KeyError("Dictionary is empty")
            key = self._order[-1]
            if not self._filepath:
                return self._db[key]
            with shelve.open(self._filepath) as db:
                return db[key]

    def get(self, key: str, default: Any = None) -> Any:
        with self.lock:
            try:
                if not self._filepath:
                    return self._db.get(key, default)
                with shelve.open(self._filepath) as db:
                    return db.get(key, default)
            except Exception:
                return default

    def keys(self) -> List[str]:
        with self.lock:
            return self._order.copy()

    def get_items_reversed(self) -> List[Any]:
        with self.lock:
            if not self._filepath:
                return [self._db[key] for key in reversed(self._order)]
            with shelve.open(self._filepath) as db:
                return [db[key] for key in reversed(self._order)]
